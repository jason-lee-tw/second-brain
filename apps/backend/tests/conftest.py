import os

# Set env vars before any second_brain module is imported.
# pydantic-settings reads env vars at Settings() instantiation time (module level).
# pytest processes conftest.py before importing test files, so these are set first.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg2://second_brain:secret@localhost:5432/second_brain",
)
os.environ.setdefault("OLLAMA_BASE_URL", "http://localhost:11434")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-api-key")
os.environ.setdefault("TAVILY_API_KEY", "test-tavily-key")
os.environ.setdefault("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006/v1/traces")
