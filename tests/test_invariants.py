"""
Double-entry invariant tests: every completed transfer has exactly one debit
and one credit ledger entry, both equal in amount.
"""
import uuid
import pytest
from decimal import Decimal
from sqlalchemy import select

from app.models import LedgerEntry, Transaction


async def _seed(client, db_session, account_id, amount):
    from app.models import Transaction as Txn, LedgerEntry as LE

    txn = Txn(
        idempotency_key=f"seed-{uuid.uuid4()}",
        request_hash="seed",
        status="completed",
        from_account_id=account_id,
        to_account_id=account_id,
        amount=amount,
    )
    db_session.add(txn)
    await db_session.flush()
    db_session.add(LE(transaction_id=txn.id, account_id=account_id, entry_type="credit", amount=amount))
    await db_session.commit()


@pytest.mark.asyncio
async def test_double_entry_invariant_after_transfers(client, db_session):
    """
    After a sequence of transfers, every completed non-seed transaction must have
    exactly one debit entry and one credit entry with equal amounts.
    """
    alice = (await client.post("/accounts", json={"owner_name": "Alice"})).json()
    bob = (await client.post("/accounts", json={"owner_name": "Bob"})).json()
    carol = (await client.post("/accounts", json={"owner_name": "Carol"})).json()

    await _seed(client, db_session, alice["id"], "200.00")

    transfers = [
        (alice["id"], bob["id"], "50.00"),
        (alice["id"], carol["id"], "30.00"),
        (alice["id"], bob["id"], "20.00"),
    ]
    for src, dst, amt in transfers:
        r = await client.post(
            "/transfers",
            json={"from_account_id": src, "to_account_id": dst, "amount": amt},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        assert r.status_code == 201

    # Fetch all non-seed transactions (request_hash != "seed").
    result = await db_session.execute(
        select(Transaction).where(Transaction.request_hash != "seed")
    )
    txns = result.scalars().all()
    assert len(txns) == 3

    for txn in txns:
        entries_result = await db_session.execute(
            select(LedgerEntry).where(LedgerEntry.transaction_id == txn.id)
        )
        entries = entries_result.scalars().all()

        debits = [e for e in entries if e.entry_type == "debit"]
        credits = [e for e in entries if e.entry_type == "credit"]

        assert len(debits) == 1, f"Transaction {txn.id} has {len(debits)} debits, expected 1"
        assert len(credits) == 1, f"Transaction {txn.id} has {len(credits)} credits, expected 1"
        assert debits[0].amount == credits[0].amount == txn.amount, (
            f"Entry amounts {debits[0].amount}, {credits[0].amount} don't match transaction amount {txn.amount}"
        )

        # Debit is on source account, credit on destination.
        assert debits[0].account_id == txn.from_account_id
        assert credits[0].account_id == txn.to_account_id


@pytest.mark.asyncio
async def test_failed_transfer_produces_no_ledger_entries(client, db_session):
    alice = (await client.post("/accounts", json={"owner_name": "Alice"})).json()
    bob = (await client.post("/accounts", json={"owner_name": "Bob"})).json()

    r = await client.post(
        "/transfers",
        json={"from_account_id": alice["id"], "to_account_id": bob["id"], "amount": "999.00"},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert r.status_code == 422

    result = await db_session.execute(select(LedgerEntry))
    assert result.scalars().all() == []
