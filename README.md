# Transaction Ledger & Payments Engine

A simulated banking backend demonstrating correctness guarantees required by real payment infrastructure: double-entry accounting, idempotency, and concurrency control.

## Running locally

```bash
cp .env.example .env
docker-compose up --build
```

The API is available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

## Running tests

```bash
# Requires a running Postgres instance accessible at localhost:5432
# (docker-compose up db, or use a local install)
pip install -r requirements.txt
pytest -v
```

## Schema

```
accounts
  id           uuid  PK
  owner_name   text
  created_at   timestamptz

transactions
  id               uuid  PK
  idempotency_key  text  UNIQUE
  request_hash     text           -- SHA-256 of (from, to, amount) for conflict detection
  status           text           -- pending | completed | failed
  from_account_id  uuid  FK
  to_account_id    uuid  FK
  amount           numeric(18,4)
  created_at       timestamptz

ledger_entries
  id              uuid  PK
  transaction_id  uuid  FK
  account_id      uuid  FK
  entry_type      text           -- debit | credit
  amount          numeric(18,4)
  created_at      timestamptz
```

**Account balance is never stored as a column.** It is always derived as `SUM(credits) - SUM(debits)` from `ledger_entries`. This preserves a complete, auditable history — you can reconstruct any account's balance at any point in time by filtering `created_at`.

## API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/accounts` | Create account |
| GET | `/accounts/{id}` | Fetch account + derived balance |
| GET | `/accounts/{id}/transactions` | Transaction history |
| POST | `/transfers` | Initiate transfer (requires `Idempotency-Key` header) |
| GET | `/transfers/{id}` | Fetch transfer status |

## Design decisions

### Concurrency: `SELECT FOR UPDATE` row locking

When processing a transfer, the source account row is locked with `SELECT ... FOR UPDATE` before the balance check. This serialises all concurrent debits against the same source account — only one transfer at a time holds the lock, so two simultaneous requests cannot both see a sufficient balance and both post.

**Why not optimistic concurrency (compare-and-swap on a version column)?** Optimistic concurrency works well when conflicts are rare. For a payments account that could receive many concurrent debits, the retry loop on conflict adds latency and complexity. Row locking is simpler to reason about, its correctness is obvious, and the performance overhead only materialises under genuinely high contention on a single account.

**Tradeoff:** Row locking reduces throughput on a single hot-source account. If this engine needed to sustain thousands of concurrent debits from one account, a queue-per-account or optimistic-with-retry approach would scale better. For a portfolio project where correctness explainability matters, row locking is the right call.

### Idempotency

Every `POST /transfers` request must include an `Idempotency-Key` header (client-generated, e.g. a UUID).

- If the key is **new**: process normally, persist the transaction, return 201.
- If the key is **seen before with the same body** (matched by SHA-256 of `from_account_id:to_account_id:amount`): return the original transaction, status 200. No second ledger entries are created.
- If the key is **seen before with a different body**: return 409 Conflict. This prevents a client from accidentally reusing a key for a different payment.

The `transactions` table itself is the idempotency store — no separate response cache table is needed. The `idempotency_key` column has a `UNIQUE` constraint enforced at the database level, so even a race between two identical first-time requests will result in one succeeding and one receiving a unique-constraint violation (which is surfaced as an internal error; clients should treat any non-2xx on a first-time key as needing a new key and retry).

### Double-entry invariant

Every completed transfer produces exactly two `ledger_entries`:
- A **debit** of `amount` on `from_account_id`
- A **credit** of `amount` on `to_account_id`

Both entries are created inside the same database transaction as the `transactions` row, so they either all commit or all roll back. There is no intermediate state where money is in flight.

The test suite (`tests/test_invariants.py`) asserts this invariant holds after any sequence of transfers.
