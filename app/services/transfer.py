import hashlib
import uuid
from decimal import Decimal

from sqlalchemy import case, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, LedgerEntry, Transaction
from app.schemas import TransferCreate


def _request_hash(body: TransferCreate) -> str:
    raw = f"{body.from_account_id}:{body.to_account_id}:{body.amount}"
    return hashlib.sha256(raw.encode()).hexdigest()


async def _get_balance(session: AsyncSession, account_id: uuid.UUID) -> Decimal:
    result = await session.execute(
        select(
            func.coalesce(
                func.sum(
                    case(
                        (LedgerEntry.entry_type == "credit", LedgerEntry.amount),
                        else_=LedgerEntry.amount * -1,
                    )
                ),
                Decimal("0"),
            )
        ).where(LedgerEntry.account_id == account_id)
    )
    return result.scalar_one()


async def process_transfer(
    session: AsyncSession,
    body: TransferCreate,
    idempotency_key: str,
) -> tuple[Transaction, int]:
    """
    Returns (transaction, http_status_code).
    http_status_code is 200 on idempotent replay, 201 on new transfer.
    Raises HTTPException for business rule violations.
    """
    from fastapi import HTTPException

    req_hash = _request_hash(body)

    # Check for an existing transaction with this idempotency key.
    existing = await session.scalar(
        select(Transaction).where(Transaction.idempotency_key == idempotency_key)
    )
    if existing is not None:
        if existing.request_hash != req_hash:
            raise HTTPException(
                status_code=409,
                detail="Idempotency key reused with a different request body.",
            )
        return existing, 200

    # Validate accounts exist and lock the source account row to prevent
    # concurrent overdrafts. SELECT FOR UPDATE ensures only one transfer
    # at a time can hold the lock on a given source account.
    from_account = await session.scalar(
        select(Account)
        .where(Account.id == body.from_account_id)
        .with_for_update()
    )
    if from_account is None:
        raise HTTPException(status_code=404, detail="Source account not found.")

    to_account = await session.scalar(
        select(Account).where(Account.id == body.to_account_id)
    )
    if to_account is None:
        raise HTTPException(status_code=404, detail="Destination account not found.")

    if body.from_account_id == body.to_account_id:
        raise HTTPException(status_code=422, detail="Cannot transfer to the same account.")

    balance = await _get_balance(session, body.from_account_id)
    if balance < body.amount:
        raise HTTPException(
            status_code=422,
            detail=f"Insufficient funds. Available: {balance}, requested: {body.amount}.",
        )

    txn = Transaction(
        idempotency_key=idempotency_key,
        request_hash=req_hash,
        status="completed",
        from_account_id=body.from_account_id,
        to_account_id=body.to_account_id,
        amount=body.amount,
    )
    session.add(txn)
    await session.flush()  # populate txn.id before creating entries

    session.add(LedgerEntry(
        transaction_id=txn.id,
        account_id=body.from_account_id,
        entry_type="debit",
        amount=body.amount,
    ))
    session.add(LedgerEntry(
        transaction_id=txn.id,
        account_id=body.to_account_id,
        entry_type="credit",
        amount=body.amount,
    ))

    await session.commit()
    await session.refresh(txn)
    return txn, 201
