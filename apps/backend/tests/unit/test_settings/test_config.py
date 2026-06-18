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


class TestApiKeyMasking:
    """API key fields must be masked in repr and str to prevent secret leakage.

    str() is the more common logging surface; repr() is also covered.
    Parameterized per field so adding a new SecretStr field only requires one entry.
    """

    @pytest.mark.parametrize("field,secret", [
        ("anthropic_api_key", "super-secret-anthropic-key"),
        ("tavily_api_key", "super-secret-tavily-key"),
    ])
    def test_api_key_masked_and_retrievable(self, field: str, secret: str) -> None:
        """API key must be masked in repr/str but readable via get_secret_value()."""
        settings = _make_settings()
        assert secret not in repr(settings)
        assert secret not in str(settings)
        assert getattr(settings, field).get_secret_value() == secret
