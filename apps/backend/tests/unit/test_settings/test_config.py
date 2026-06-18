"""Tests for Settings security properties — API keys must never appear in repr."""

from second_brain.config import Settings


def _make_settings() -> Settings:
    """Instantiate Settings with known test values."""
    return Settings(
        database_url="postgresql+psycopg2://second_brain:secret@localhost:5432/second_brain",
        anthropic_api_key="super-secret-anthropic-key",
        tavily_api_key="super-secret-tavily-key",
        phoenix_collection_endpoint="http://localhost:4317",
    )


class TestApiKeyMasking:
    """API key fields must be masked in repr to prevent accidental secret leakage."""

    def test_anthropic_api_key_not_exposed_in_repr(self) -> None:
        """repr(settings) must not contain the raw anthropic_api_key value."""
        settings = _make_settings()
        assert "super-secret-anthropic-key" not in repr(settings)

    def test_tavily_api_key_not_exposed_in_repr(self) -> None:
        """repr(settings) must not contain the raw tavily_api_key value."""
        settings = _make_settings()
        assert "super-secret-tavily-key" not in repr(settings)

    def test_anthropic_api_key_value_retrievable_via_get_secret_value(self) -> None:
        """The actual key must still be accessible when explicitly requested."""
        settings = _make_settings()
        assert settings.anthropic_api_key.get_secret_value() == (
            "super-secret-anthropic-key"
        )

    def test_tavily_api_key_value_retrievable_via_get_secret_value(self) -> None:
        """The actual key must still be accessible when explicitly requested."""
        settings = _make_settings()
        assert settings.tavily_api_key.get_secret_value() == "super-secret-tavily-key"
