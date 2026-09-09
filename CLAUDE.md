# Project: Transaction Ledger & Payments Engine

## What this is

A simulated banking backend that models the correctness problems real payment
infrastructure has to solve: guaranteeing money is never silently created or
destroyed on a transfer (double-entry ledger accounting), guaranteeing a
network retry can't double-charge someone (idempotency), and keeping account
balances correct when multiple transfers hit the same account concurrently
(concurrency control). This is a portfolio project for backend/software
engineering internship applications — correctness and defensibility matter
more than feature breadth.

## Tech stack (decided — do not deviate without asking)

- **Language/framework:** Python 3.11+, FastAPI
- **Database:** PostgreSQL, accessed via SQLAlchemy (async) + Alembic for migrations
- **Testing:** pytest, pytest-asyncio, httpx for API-level tests
- **CI:** GitHub Actions
- **Containerization:** Docker + docker-compose (app + Postgres)

Rationale for Python over Java/C#: a later phase of this project adds a
PyTorch-based anomaly-detection worker, and keeping the whole system in one
language avoids unnecessary context-switching during a tight timeline. If
asked to switch to Java/Spring Boot instead, that's a valid alternative — just
flag the tradeoff before doing it.

## Scope for this session: Phase 0 only

Build the core ledger engine end to end. Do **not** build the following yet,
even if they seem like natural next steps — they are later phases and adding
them now creates premature complexity: Pub/Sub or any message queue, the
React dashboard, the PyTorch fraud model, authentication/authorization, or
the order book / matching engine. If you find yourself wanting to add one of
these while working on Phase 0, stop and ask first.

### Data model

- `accounts`: id (uuid pk), owner_name, created_at
- `transactions`: id (uuid pk), idempotency_key (unique, indexed), status
  (pending/completed/failed), from_account_id, to_account_id, amount,
  created_at
- `ledger_entries`: id (uuid pk), transaction_id (fk), account_id (fk),
  entry_type (debit/credit), amount, created_at

A transfer of $50 from account A to account B produces exactly two
ledger_entries: a debit of 50 on A and a credit of 50 on B. An account's
balance is always derived as `SUM(credits) - SUM(debits)` for that account —
never store balance as a mutable column, or you lose the auditability that's
the whole point of double-entry accounting.

### Endpoints

- `POST /accounts` — create an account
- `GET /accounts/{id}` — fetch account + derived balance
- `GET /accounts/{id}/transactions` — transaction history for an account
- `POST /transfers` — body: `{from_account_id, to_account_id, amount}`,
  header: `Idempotency-Key: <client-generated key>`
- `GET /transfers/{id}` — fetch transfer status

### Business rules to implement carefully

1. **Double-entry invariant:** every completed transfer has exactly one debit
   and one credit ledger entry, and they must be equal in amount. Add a test
   that asserts this invariant holds after any sequence of transfers.
2. **Insufficient funds:** reject a transfer if it would take the source
   account's derived balance below zero. Return a clear 4xx error, not a 500.
3. **Idempotency:** if a request arrives with an `Idempotency-Key` that's
   been seen before, return the original response instead of processing
   again — do not create a second set of ledger entries. If the same key
   arrives with a *different* request body, that's a conflict (409), not a
   silent replay.
4. **Concurrency:** two simultaneous transfers debiting the same account must
   not both pass the balance check and overdraw it. Use `SELECT ... FOR
   UPDATE` on the source account row inside the transaction, or an
   equivalent locking/optimistic-concurrency strategy — but pick one
   deliberately and be able to explain why. Write a test that fires
   concurrent transfers at the same account and asserts the final balance is
   correct.

### Testing requirements

- Unit tests for the ledger math (debit/credit creation, balance derivation)
- Integration tests for: insufficient funds rejection, idempotent replay
  (same key, same body), idempotency conflict (same key, different body),
  and concurrent transfers on one account
- Target meaningful coverage on the transfer logic specifically — coverage
  on trivial CRUD endpoints matters much less

### CI/CD

- GitHub Actions workflow that spins up Postgres as a service container and
  runs the full pytest suite on every push
- Should fail loudly if any test fails — no soft-fail steps

### Definition of done for this phase

- `docker-compose up` brings up the app and database and it's usable locally
- All endpoints above work and are covered by tests
- CI is green on the repo's default branch
- A `README.md` exists explaining the schema and, specifically, the
  concurrency and idempotency design decisions and why they were made —
  this doubles as interview prep, so don't skip it or make it generic

## Working style

- Work in small, reviewable increments — schema first, then core transfer
  logic, then idempotency, then concurrency, then tests, then CI. Don't
  jump ahead to later steps before earlier ones are solid.
- Write tests alongside the code they cover, not as an afterthought pass at
  the end.
- Explain non-obvious design decisions in code comments or the README as you
  go, particularly around locking strategy and idempotency handling — I need
  to be able to defend these choices in interviews without re-deriving them.
- If a design decision has a real tradeoff (e.g. row locking vs. optimistic
  concurrency), briefly state the tradeoff before implementing rather than
  silently picking one.

## Later phases (context only — not in scope now)

For awareness so nothing built now conflicts with it later: Phase 1 adds a
Pub/Sub event layer between the API and ledger posting; Phase 2 adds a React
dashboard; Phase 3 adds a PyTorch-based anomaly-detection worker consuming
the same event stream; Phase 4 (optional) adds an order book / matching
engine that settles trades through this ledger. None of this affects Phase 0
except: keep the transfer-processing logic reasonably separable from the API
layer, since it will later be invoked from an async worker instead of
directly from the endpoint.

---

**First task:** Read this whole file, then propose the initial project
structure and schema before writing any code. Wait for confirmation before
proceeding to implementation.
