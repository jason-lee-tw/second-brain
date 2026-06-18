from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    ollama_base_url: str = "http://localhost:11434"
    # Access via .get_secret_value() when passing to SDK clients
    anthropic_api_key: SecretStr
    tavily_api_key: SecretStr
    phoenix_collection_endpoint: str

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
