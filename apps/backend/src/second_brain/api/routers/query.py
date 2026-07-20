import logging

from fastapi import APIRouter, HTTPException
from langchain_core.messages import HumanMessage
from uuid6 import uuid7

from second_brain.api.schemas import QueryRequest, QueryResponse
from second_brain.config import settings
from second_brain.graphs.query_graph import build_query_graph

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/query", tags=["query"])

# Module-level compiled graph singleton — initialised once on first request
_graph = None


async def _get_graph():
    global _graph
    if _graph is None:
        # build_query_graph() does not strip the SQLAlchemy dialect suffix itself —
        # the caller must pass a clean psycopg-compatible DSN.
        postgres_url = settings.database_url.replace("+psycopg2", "")
        _graph = await build_query_graph(postgres_url)
    return _graph


async def shutdown() -> None:
    """Close the query graph's checkpoint connection pool, if one was opened.

    Called from the FastAPI lifespan (wired in a later task). build_query_graph()
    does not return the AsyncConnectionPool it opens, so this reaches it via the
    compiled graph's checkpointer.conn — the only handle available without
    modifying query_graph.py.
    """
    global _graph
    if _graph is None:
        return
    pool = getattr(_graph.checkpointer, "conn", None)
    if pool is not None:
        await pool.close()
    _graph = None


@router.post("", response_model=QueryResponse)
async def query_endpoint(request: QueryRequest) -> QueryResponse:
    """Chat with the Second Brain.

    - sessionId=null -> creates a new conversation thread (new UUID7 returned)
    - sessionId=<UUID7> -> continues an existing thread (history loaded from checkpoint)

    PII in the message is redacted before reaching any LLM node (AC-5).
    PII in the final answer is redacted before being persisted (AC-6).
    """
    session_id: str = request.sessionId or str(uuid7())

    graph = await _get_graph()

    # Pass the new user message; LangGraph's add_messages reducer appends it
    # to the existing checkpoint history for this thread_id (AC-10)
    input_state = {
        "session_id": session_id,
        "messages": [HumanMessage(content=request.message)],
        "rag_results": [],
        "web_results": [],
        "retrieved_memory": [],
        "routing_decision": "neither",
        "final_answer": "",
        "confidence": 0.0,
        "is_uncertain": False,
        "awaiting_correction": False,
        "awaiting_conflict_clarification": False,
        "conflict_context": [],
        "fact_updates": [],
        "correction_updates": [],
    }
    config = {"configurable": {"thread_id": session_id}}

    try:
        result = await graph.ainvoke(input_state, config=config)
    except Exception as exc:
        _logger.error("Query graph error", exc_info=True)
        raise HTTPException(
            status_code=500, detail="Query graph error — see server logs"
        ) from exc

    conflict_context: list[str] = result.get("conflict_context", [])

    return QueryResponse(
        answer=result["final_answer"],
        sessionId=session_id,
        confidence=result["confidence"],
        isUncertain=result["is_uncertain"],
        conflictDetected=bool(conflict_context),
        conflictContext=conflict_context,
    )
