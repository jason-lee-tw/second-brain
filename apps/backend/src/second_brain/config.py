import os
from typing import Any

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    ollama_base_url: str = "http://localhost:11434"
    # SecretStr fields — access via .get_secret_value() when passing to SDK clients
    anthropic_api_key: SecretStr
    tavily_api_key: SecretStr
    phoenix_collection_endpoint: str = "http://localhost:4317"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="before")
    @classmethod
    def _reject_deprecated_phoenix_key(cls, values: Any) -> Any:
        if os.environ.get("PHOENIX_COLLECTOR_ENDPOINT"):
            raise ValueError(
                "PHOENIX_COLLECTOR_ENDPOINT has been renamed to "
                "PHOENIX_COLLECTION_ENDPOINT. Update your .env file."
            )
        return values


settings = Settings()
