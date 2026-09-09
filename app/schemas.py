import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class AccountCreate(BaseModel):
    owner_name: str


class AccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_name: str
    created_at: datetime
    balance: Decimal


class TransactionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    from_account_id: uuid.UUID
    to_account_id: uuid.UUID
    amount: Decimal
    created_at: datetime


class TransferCreate(BaseModel):
    from_account_id: uuid.UUID
    to_account_id: uuid.UUID
    amount: Decimal = Field(gt=0)


class TransferResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    idempotency_key: str
    status: str
    from_account_id: uuid.UUID
    to_account_id: uuid.UUID
    amount: Decimal
    created_at: datetime
