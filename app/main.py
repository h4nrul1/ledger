from fastapi import FastAPI

from app.routers import accounts, transfers

app = FastAPI(title="Ledger API")

app.include_router(accounts.router)
app.include_router(transfers.router)
