from contextlib import asynccontextmanager

from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from second_brain.config import settings
from second_brain.observability.tracing import setup_tracing


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_tracing(phoenix_collection_endpoint=settings.phoenix_collection_endpoint)
    yield


app = FastAPI(title="Second Brain", version="0.1.0", lifespan=lifespan)

# Instrument at module level to decouple ASGI middleware wiring (pure Python, no I/O)
# from setup_tracing() which connects to Phoenix. Middleware is added before requests.
FastAPIInstrumentor.instrument_app(app)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
