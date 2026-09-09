from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://ledger:ledger@localhost:5432/ledger"

    model_config = {"env_file": ".env"}


settings = Settings()
