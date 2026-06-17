from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    ollama_base_url: str = "http://localhost:11434"
    anthropic_api_key: SecretStr
    tavily_api_key: SecretStr
    phoenix_collector_endpoint: str = "http://localhost:6006/v1/traces"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
