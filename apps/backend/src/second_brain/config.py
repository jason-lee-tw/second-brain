from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    ollama_base_url: str = "http://localhost:11434"
    anthropic_api_key: str
    tavily_api_key: str
    phoenix_endpoint: str = "http://host.docker.internal:6006/v1/traces"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
