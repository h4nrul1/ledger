import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Account, LedgerEntry, Transaction
from app.schemas import AccountCreate, AccountResponse, TransactionSummary

router = APIRouter(prefix="/accounts", tags=["accounts"])


async def _derive_balance(session: AsyncSession, account_id: uuid.UUID) -> Decimal:
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


@router.post("", response_model=AccountResponse, status_code=201)
async def create_account(body: AccountCreate, db: AsyncSession = Depends(get_db)):
    account = Account(owner_name=body.owner_name)
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return AccountResponse(
        id=account.id,
        owner_name=account.owner_name,
        created_at=account.created_at,
        balance=Decimal("0"),
    )


@router.get("/{account_id}", response_model=AccountResponse)
async def get_account(account_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    account = await db.scalar(select(Account).where(Account.id == account_id))
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found.")
    balance = await _derive_balance(db, account_id)
    return AccountResponse(
        id=account.id,
        owner_name=account.owner_name,
        created_at=account.created_at,
        balance=balance,
    )


@router.get("/{account_id}/transactions", response_model=list[TransactionSummary])
async def get_account_transactions(account_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    account = await db.scalar(select(Account).where(Account.id == account_id))
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found.")

    result = await db.execute(
        select(Transaction)
        .where(
            (Transaction.from_account_id == account_id)
            | (Transaction.to_account_id == account_id)
        )
        .order_by(Transaction.created_at.desc())
    )
    return result.scalars().all()
