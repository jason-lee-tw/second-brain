# apps/backend/src/second_brain/api/routers/query.py
"""POST /query router — invokes the SecondBrain query graph."""

import asyncio

from fastapi import APIRouter
from langchain_core.messages import HumanMessage
from uuid6 import uuid7

from second_brain.api.schemas import QueryRequest, QueryResponse
from second_brain.config import settings
from second_brain.graphs.query_graph import build_query_graph

router = APIRouter(prefix="/query", tags=["query"])

# ponytail: deferred — refactor to FastAPI DI (app.state + Depends) to eliminate
# global mutation
_graph = None
_pool = None
_init_lock = asyncio.Lock()


async def _get_graph():
  global _graph, _pool
  async with _init_lock:
    if _graph is None:
      pg_url = settings.postgres_url
      _graph, _pool = await build_query_graph(pg_url)
  return _graph


async def shutdown_query_graph() -> None:
  global _graph, _pool
  if _pool is not None:
    await _pool.close()
    _pool = None
    _graph = None


@router.post("", response_model=QueryResponse)
async def query_endpoint(request: QueryRequest) -> QueryResponse:
  """Invoke the SecondBrain query graph and return a structured response."""
  session_id = request.sessionId or str(uuid7())
  graph = await _get_graph()
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
    "context_used": [],
  }
  result = await graph.ainvoke(
    input_state,  # pyright: ignore[reportArgumentType]
    config={"configurable": {"thread_id": session_id}},
  )

  conflict_context = result.get("conflict_context", [])
  retrieved_contexts = result["context_used"]
  return QueryResponse(
    answer=result["final_answer"],
    sessionId=session_id,
    confidence=result["confidence"],
    isUncertain=result["is_uncertain"],
    conflictDetected=bool(conflict_context),
    conflictContext=conflict_context,
    retrievedContexts=retrieved_contexts,
  )
