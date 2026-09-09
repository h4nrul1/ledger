import uuid
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from datetime import datetime

from app.database import Base


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    owner_name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    ledger_entries: Mapped[list["LedgerEntry"]] = relationship(back_populates="account")


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    # Hash of (from_account_id, to_account_id, amount) used for conflict detection.
    request_hash: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    from_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    to_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    ledger_entries: Mapped[list["LedgerEntry"]] = relationship(back_populates="transaction")

    __table_args__ = (
        CheckConstraint("status IN ('pending', 'completed', 'failed')", name="ck_transaction_status"),
        CheckConstraint("amount > 0", name="ck_transaction_amount_positive"),
        Index("idx_transactions_idempotency_key", "idempotency_key"),
    )


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transactions.id"), nullable=False
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    entry_type: Mapped[str] = mapped_column(String, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    transaction: Mapped["Transaction"] = relationship(back_populates="ledger_entries")
    account: Mapped["Account"] = relationship(back_populates="ledger_entries")

    __table_args__ = (
        CheckConstraint("entry_type IN ('debit', 'credit')", name="ck_ledger_entry_type"),
        CheckConstraint("amount > 0", name="ck_ledger_entry_amount_positive"),
        Index("idx_ledger_entries_account_id", "account_id"),
    )
