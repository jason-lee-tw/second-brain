from fastapi import FastAPI

from second_brain.config import settings  # noqa: F401 — validates config at startup

app = FastAPI(title="Second Brain", version="0.1.0")


@app.get("/health")
async def health_check() -> dict:
    return {"status": "ok"}
