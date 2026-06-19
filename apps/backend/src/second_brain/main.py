import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from second_brain.api.routers.ingest import router as ingest_router
from second_brain.config import settings
from second_brain.nodes import ingestion_agent
from second_brain.observability.tracing import setup_tracing
from second_brain.services import embeddings

_logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    provider = setup_tracing(
        phoenix_collection_endpoint=settings.phoenix_collection_endpoint
    )
    yield
    try:
        provider.shutdown()
    # ponytail: teardown broad-catch — shutdown errors are unactionable at exit;
    # exc_info=True preserves visibility without propagating into ASGI teardown
    except Exception:
        _logger.warning("TracerProvider shutdown raised an exception", exc_info=True)
    try:
        await embeddings._client.aclose()
    except Exception:
        _logger.warning(
            "embeddings._client.aclose() raised an exception", exc_info=True
        )
    try:
        await ingestion_agent._anthropic.close()
    except Exception:
        _logger.warning(
            "ingestion_agent._anthropic.close() raised an exception", exc_info=True
        )


app = FastAPI(title="Second Brain", version="0.1.0", lifespan=lifespan)

# Instrument at module level to decouple ASGI middleware wiring (pure Python, no I/O)
# from setup_tracing() which connects to Phoenix. Middleware is added before requests.
FastAPIInstrumentor.instrument_app(app)

app.include_router(ingest_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
