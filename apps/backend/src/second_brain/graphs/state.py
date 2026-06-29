from enum import StrEnum
from typing import Annotated, Literal, NotRequired, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel

from second_brain.services.chunking import ChunkMetadata


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
# SecondBrainState -- query graph state
# ---------------------------------------------------------------------------


class RagResult(TypedDict):
    content: str
    score: float
    chunk_index: int
    metadata: ChunkMetadata | None


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


class ConflictContext(TypedDict):
    existing: str  # text of the existing fact
    existing_id: str  # UUID of the existing learned_fact row
    new: str  # text of the proposed new fact


class MemoryCase(StrEnum):
    FACT_EXTRACTION = "fact_extraction"
    CORRECTION = "correction"
    CONFLICT_RESOLUTION = "conflict_resolution"


class MemoryAgentOutput(BaseModel):
    case: MemoryCase
    fact_updates: list[FactUpdate] = []
    correction_updates: list[CorrectionUpdate] = []


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
    awaiting_correction: NotRequired[bool]  # Ticket 5: memory-correction
    awaiting_conflict_clarification: NotRequired[bool]  # Ticket 5: memory-correction
    conflict_context: NotRequired[list[ConflictContext]]  # Ticket 5: memory-correction
    fact_updates: NotRequired[list[FactUpdate]]  # Ticket 5: memory-correction
    correction_updates: NotRequired[list[CorrectionUpdate]]  # T5: memory-correction


# ---------------------------------------------------------------------------
# Per-node output TypedDicts
# ---------------------------------------------------------------------------


class PickFileOutput(TypedDict):
    in_progress: str | None
    files: NotRequired[list[str]]


class IngestionAgentOutput(TypedDict, total=False):
    in_progress: str | None
    retry_queue: list[FailedFile]
    processed: list[str]
    failed: list[FailedFile]


class RedactInboundOutput(TypedDict):
    messages: list[BaseMessage]


class RedactOutboundOutput(TypedDict):
    final_answer: str


class RetrieveMemoryOutput(TypedDict):
    retrieved_memory: list[MemoryItem]


class RouteQueryOutput(TypedDict):
    routing_decision: Literal["rag", "web", "both", "neither"]


class RagRetrievalOutput(TypedDict):
    rag_results: list[RagResult]


class WebResearchOutput(TypedDict):
    web_results: list[WebResult]


class SynthesisNodeOutput(TypedDict):
    final_answer: str
    confidence: float
    is_uncertain: bool
