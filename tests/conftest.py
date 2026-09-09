import asyncio
import os
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.database import Base, get_db
from app.main import app

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://ledger:ledger@localhost:5432/ledger_test",
)

# Kill connections that sit idle-in-transaction for > 5s, preventing deadlocks
# in TRUNCATE teardown if a session was not properly closed.
_CONNECT_ARGS = {
    "server_settings": {"idle_in_transaction_session_timeout": "5000"}
}


def make_engine():
    # NullPool: no connection reuse — each operation gets a fresh asyncpg
    # connection, ensuring connections are always created in the current
    # event loop and never bleed across tests.
    return create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        poolclass=NullPool,
        connect_args=_CONNECT_ARGS,
    )


async def _setup_schema():
    eng = make_engine()
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await eng.dispose()


async def _teardown_schema():
    eng = make_engine()
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest.fixture(scope="session", autouse=True)
def create_schema():
    # Use asyncio.run() (not pytest-asyncio) so this has its own isolated event
    # loop entirely separate from the per-test function-scoped loops below.
    asyncio.run(_setup_schema())
    yield
    asyncio.run(_teardown_schema())


@pytest_asyncio.fixture(autouse=True)
async def clean_tables():
    yield
    eng = make_engine()
    async with eng.begin() as conn:
        await conn.execute(
            text("TRUNCATE ledger_entries, transactions, accounts RESTART IDENTITY CASCADE")
        )
    await eng.dispose()


@pytest_asyncio.fixture
async def db_session():
    eng = make_engine()
    factory = async_sessionmaker(eng, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        await session.rollback()
        await session.close()
    await eng.dispose()


@pytest_asyncio.fixture
async def client():
    eng = make_engine()
    factory = async_sessionmaker(eng, expire_on_commit=False)

    async def override_get_db():
        session = factory()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
    await eng.dispose()
