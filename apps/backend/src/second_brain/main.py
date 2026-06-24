import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from second_brain.api.routers.ingest import router as ingest_router
from second_brain.api.routers.query import router as query_router
from second_brain.api.routers.query import shutdown_query_graph
from second_brain.config import settings
from second_brain.nodes import ingestion_agent
from second_brain.nodes.rag_retrieval import shutdown_rag_pool
from second_brain.observability.tracing import setup_tracing
from second_brain.services import embeddings

_logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
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
        await embeddings.shutdown()
    except Exception:
        _logger.warning("embeddings.shutdown() raised an exception", exc_info=True)
    try:
        await ingestion_agent.shutdown()
    except Exception:
        _logger.warning("ingestion_agent.shutdown() raised an exception", exc_info=True)
    try:
        await shutdown_query_graph()
    except Exception:
        _logger.warning("shutdown_query_graph() raised an exception", exc_info=True)
    try:
        await shutdown_rag_pool()
    except Exception:
        _logger.warning("shutdown_rag_pool() raised an exception", exc_info=True)


app = FastAPI(title="Second Brain", version="0.1.0", lifespan=lifespan)

# Instrument at module level to decouple ASGI middleware wiring (pure Python, no I/O)
# from setup_tracing() which connects to Phoenix. Middleware is added before requests.
FastAPIInstrumentor.instrument_app(app)

app.include_router(ingest_router)
app.include_router(query_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
