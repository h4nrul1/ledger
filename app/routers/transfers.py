import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Transaction
from app.schemas import TransferCreate, TransferResponse
from app.services.transfer import process_transfer

router = APIRouter(prefix="/transfers", tags=["transfers"])


@router.post("", response_model=TransferResponse)
async def create_transfer(
    body: TransferCreate,
    response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
):
    txn, status_code = await process_transfer(db, body, idempotency_key)
    response.status_code = status_code
    return txn


@router.get("/{transfer_id}", response_model=TransferResponse)
async def get_transfer(transfer_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    txn = await db.scalar(select(Transaction).where(Transaction.id == transfer_id))
    if txn is None:
        raise HTTPException(status_code=404, detail="Transfer not found.")
    return txn
