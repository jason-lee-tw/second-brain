from typing import Annotated, Literal, NotRequired, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class FailedFile(TypedDict):
    filename: str
    error: str
    retry_count: int


class IngestionState(TypedDict):
    files: list[str]  # original input queue (first-attempt files)
    in_progress: str | None  # in-flight file (None when idle)
    processed: list[str]  # successfully ingested filenames
    retry_queue: list[FailedFile]  # retry_count < 3 (terminal threshold)
    failed: list[FailedFile]  # terminal failures: retry_count >= 3
    # filename -> original URL; router always sets this key
    # (empty dict for local-file ingestion)
    source_urls: NotRequired[dict[str, str]]


# ---------------------------------------------------------------------------
# SecondBrainState — query graph state
# ---------------------------------------------------------------------------


class RagResult(TypedDict):
    content: str
    score: float
    chunk_index: int
    metadata: dict


class WebResult(TypedDict):
    title: str
    url: str
    content: str


class MemoryItem(TypedDict):
    id: str
    fact: str
    confidence: float
    type: Literal["learned_fact", "model_correction"]


class FactUpdate(TypedDict):
    fact: str
    confidence: float
    conflicts_with: list[str]


class CorrectionUpdate(TypedDict):
    original_answer: str
    correction: str
    root_cause: str


class SecondBrainState(TypedDict):
    session_id: str
    messages: Annotated[list[BaseMessage], add_messages]
    rag_results: list[RagResult]
    web_results: list[WebResult]
    retrieved_memory: list[MemoryItem]
    routing_decision: Literal["rag", "web", "both", "neither"]
    final_answer: str
    confidence: float
    is_uncertain: bool
    awaiting_correction: bool
    awaiting_conflict_clarification: bool
    conflict_context: list[str]
    fact_updates: list[FactUpdate]
    correction_updates: list[CorrectionUpdate]
