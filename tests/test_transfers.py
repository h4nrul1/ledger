import asyncio
import uuid
import pytest
from decimal import Decimal
from sqlalchemy import select, func

from app.models import LedgerEntry, Transaction


async def _make_accounts(client, *names):
    return [
        (await client.post("/accounts", json={"owner_name": n})).json()
        for n in names
    ]


async def _seed_balance(client, db_session, account_id: str, amount: str):
    """
    Directly insert a credit ledger entry to seed an account balance,
    bypassing the transfer API (no external funding source in tests).
    """
    from app.models import Transaction as Txn, LedgerEntry as LE
    import uuid as _uuid

    txn = Txn(
        idempotency_key=f"seed-{_uuid.uuid4()}",
        request_hash="seed",
        status="completed",
        from_account_id=account_id,
        to_account_id=account_id,
        amount=amount,
    )
    db_session.add(txn)
    await db_session.flush()
    db_session.add(LE(
        transaction_id=txn.id,
        account_id=account_id,
        entry_type="credit",
        amount=amount,
    ))
    await db_session.commit()


# --- Happy path ---

@pytest.mark.asyncio
async def test_transfer_success(client, db_session):
    alice, bob = await _make_accounts(client, "Alice", "Bob")
    await _seed_balance(client, db_session, alice["id"], "100.00")

    r = await client.post(
        "/transfers",
        json={"from_account_id": alice["id"], "to_account_id": bob["id"], "amount": "50.00"},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert r.status_code == 201
    data = r.json()
    assert data["status"] == "completed"
    assert Decimal(data["amount"]) == Decimal("50.00")

    alice_balance = (await client.get(f"/accounts/{alice['id']}")).json()["balance"]
    bob_balance = (await client.get(f"/accounts/{bob['id']}")).json()["balance"]
    assert Decimal(alice_balance) == Decimal("50.00")
    assert Decimal(bob_balance) == Decimal("50.00")


# --- Insufficient funds ---

@pytest.mark.asyncio
async def test_insufficient_funds(client, db_session):
    alice, bob = await _make_accounts(client, "Alice", "Bob")
    await _seed_balance(client, db_session, alice["id"], "30.00")

    r = await client.post(
        "/transfers",
        json={"from_account_id": alice["id"], "to_account_id": bob["id"], "amount": "50.00"},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert r.status_code == 422
    assert "Insufficient" in r.json()["detail"]


@pytest.mark.asyncio
async def test_zero_balance_rejected(client):
    alice, bob = await _make_accounts(client, "Alice", "Bob")
    r = await client.post(
        "/transfers",
        json={"from_account_id": alice["id"], "to_account_id": bob["id"], "amount": "1.00"},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert r.status_code == 422


# --- Idempotency ---

@pytest.mark.asyncio
async def test_idempotent_replay_same_body(client, db_session):
    alice, bob = await _make_accounts(client, "Alice", "Bob")
    await _seed_balance(client, db_session, alice["id"], "100.00")

    key = str(uuid.uuid4())
    payload = {"from_account_id": alice["id"], "to_account_id": bob["id"], "amount": "40.00"}

    r1 = await client.post("/transfers", json=payload, headers={"Idempotency-Key": key})
    assert r1.status_code == 201

    r2 = await client.post("/transfers", json=payload, headers={"Idempotency-Key": key})
    assert r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]

    # Balance must not have changed on the second call.
    alice_balance = (await client.get(f"/accounts/{alice['id']}")).json()["balance"]
    assert Decimal(alice_balance) == Decimal("60.00")


@pytest.mark.asyncio
async def test_idempotency_conflict_different_body(client, db_session):
    alice, bob = await _make_accounts(client, "Alice", "Bob")
    await _seed_balance(client, db_session, alice["id"], "100.00")

    key = str(uuid.uuid4())
    r1 = await client.post(
        "/transfers",
        json={"from_account_id": alice["id"], "to_account_id": bob["id"], "amount": "40.00"},
        headers={"Idempotency-Key": key},
    )
    assert r1.status_code == 201

    r2 = await client.post(
        "/transfers",
        json={"from_account_id": alice["id"], "to_account_id": bob["id"], "amount": "99.00"},
        headers={"Idempotency-Key": key},
    )
    assert r2.status_code == 409


# --- Same-account transfer ---

@pytest.mark.asyncio
async def test_same_account_transfer_rejected(client, db_session):
    alice, = await _make_accounts(client, "Alice")
    await _seed_balance(client, db_session, alice["id"], "100.00")
    r = await client.post(
        "/transfers",
        json={"from_account_id": alice["id"], "to_account_id": alice["id"], "amount": "10.00"},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert r.status_code == 422


# --- Concurrency ---

@pytest.mark.asyncio
async def test_concurrent_transfers_no_overdraft(client, db_session):
    """
    Fire 10 concurrent $15 transfers from an account with $100.
    Only 6 should succeed (6 * 15 = 90 <= 100; 7 * 15 = 105 > 100).
    Final balance must be >= 0.
    """
    alice, bob = await _make_accounts(client, "Alice", "Bob")
    await _seed_balance(client, db_session, alice["id"], "100.00")

    async def do_transfer(n):
        return await client.post(
            "/transfers",
            json={"from_account_id": alice["id"], "to_account_id": bob["id"], "amount": "15.00"},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )

    results = await asyncio.gather(*[do_transfer(i) for i in range(10)])
    statuses = [r.status_code for r in results]
    successes = statuses.count(201)
    failures = statuses.count(422)

    assert successes + failures == 10
    assert successes <= 6  # can't spend more than $100 at $15 each

    final_balance = Decimal((await client.get(f"/accounts/{alice['id']}")).json()["balance"])
    assert final_balance >= Decimal("0")
    assert final_balance == Decimal("100.00") - (successes * Decimal("15.00"))


# --- Account not found ---

@pytest.mark.asyncio
async def test_transfer_unknown_source_account(client):
    bob, = await _make_accounts(client, "Bob")
    r = await client.post(
        "/transfers",
        json={
            "from_account_id": str(uuid.uuid4()),
            "to_account_id": bob["id"],
            "amount": "10.00",
        },
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_transfer_unknown_dest_account(client, db_session):
    alice, = await _make_accounts(client, "Alice")
    await _seed_balance(client, db_session, alice["id"], "100.00")
    r = await client.post(
        "/transfers",
        json={
            "from_account_id": alice["id"],
            "to_account_id": str(uuid.uuid4()),
            "amount": "10.00",
        },
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert r.status_code == 404


# --- GET /transfers/{id} ---

@pytest.mark.asyncio
async def test_get_transfer(client, db_session):
    alice, bob = await _make_accounts(client, "Alice", "Bob")
    await _seed_balance(client, db_session, alice["id"], "50.00")

    r = await client.post(
        "/transfers",
        json={"from_account_id": alice["id"], "to_account_id": bob["id"], "amount": "25.00"},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    txn_id = r.json()["id"]

    r2 = await client.get(f"/transfers/{txn_id}")
    assert r2.status_code == 200
    assert r2.json()["id"] == txn_id


@pytest.mark.asyncio
async def test_get_transfer_not_found(client):
    r = await client.get(f"/transfers/{uuid.uuid4()}")
    assert r.status_code == 404
