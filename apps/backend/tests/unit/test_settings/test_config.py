"""Tests for Settings security — API keys must never appear in repr or str output."""

import pytest

from second_brain.config import Settings


def _make_settings() -> Settings:
    """Instantiate Settings with known test values."""
    return Settings(
        database_url="postgresql+psycopg2://second_brain:secret@localhost:5432/second_brain",
        anthropic_api_key="super-secret-anthropic-key",
        tavily_api_key="super-secret-tavily-key",
        phoenix_collection_endpoint="http://localhost:4317",
    )


class TestPhoenixEndpointDefault:
    def test_settings_uses_localhost_default_when_env_not_set(self, monkeypatch):
        """Settings has a localhost default so startup doesn't fail without the env var.

        Passes _env_file=None and removes the env var to simulate a clean environment
        — the field must carry its own default, not rely on .env.
        """
        monkeypatch.delenv("PHOENIX_COLLECTION_ENDPOINT", raising=False)
        settings = Settings(
            database_url="postgresql+psycopg2://second_brain:secret@localhost:5432/second_brain",
            anthropic_api_key="key",
            tavily_api_key="key",
            # phoenix_collection_endpoint not provided — must use default
            _env_file=None,
        )
        assert settings.phoenix_collection_endpoint == "http://localhost:4317"


class TestDeprecatedPhoenixKey:
    def test_raises_on_old_env_var_name(self, monkeypatch):
        """Settings raises ValueError when the deprecated key is present."""
        monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://old:4317")
        monkeypatch.delenv("PHOENIX_COLLECTION_ENDPOINT", raising=False)
        with pytest.raises(ValueError, match="PHOENIX_COLLECTOR_ENDPOINT"):
            Settings(
                database_url="postgresql+psycopg2://u:p@localhost/db",
                anthropic_api_key="key",
                tavily_api_key="key",
                _env_file=None,
            )


class TestPostgresUrl:
    """postgres_url must strip any +driver suffix regardless of driver name."""

    @pytest.mark.parametrize(
        "database_url,expected",
        [
            (
                "postgresql+psycopg2://user:pass@host/db",
                "postgresql://user:pass@host/db",
            ),
            (
                "postgresql+asyncpg://user:pass@host/db",
                "postgresql://user:pass@host/db",
            ),
            (
                "postgresql+psycopg://user:pass@host/db",
                "postgresql://user:pass@host/db",
            ),
            (
                "postgresql://user:pass@host/db",
                "postgresql://user:pass@host/db",
            ),
        ],
    )
    def test_strips_driver_suffix(self, database_url: str, expected: str) -> None:
        """postgres_url strips any +driver component from DATABASE_URL."""
        s = Settings(
            database_url=database_url,
            anthropic_api_key="key",
            tavily_api_key="key",
            _env_file=None,
        )
        assert s.postgres_url == expected


class TestApiKeyMasking:
    """API key fields must be masked in repr and str to prevent secret leakage.

    str() is the more common logging surface; repr() is also covered.
    Parameterized per field so adding a new SecretStr field only requires one entry.
    """

    @pytest.mark.parametrize(
        "field,secret",
        [
            ("anthropic_api_key", "super-secret-anthropic-key"),
            ("tavily_api_key", "super-secret-tavily-key"),
        ],
    )
    def test_api_key_masked_and_retrievable(self, field: str, secret: str) -> None:
        """API key must be masked in repr/str but readable via get_secret_value()."""
        settings = _make_settings()
        assert secret not in repr(settings)
        assert secret not in str(settings)
        assert getattr(settings, field).get_secret_value() == secret
