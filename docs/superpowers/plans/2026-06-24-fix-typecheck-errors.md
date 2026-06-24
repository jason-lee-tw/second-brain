# Fix Type-Check Errors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `just type-check` exit 0 by fixing all 50 basedpyright errors across 12 backend files, with no use of `Any` in our own code.

**Architecture:** Fixes fall into three categories: (1) targeted `# type: ignore` comments for third-party library stub gaps where runtime works but stubs disagree; (2) proper TypedDicts for every node's return type in `state.py`; (3) a new `utils.py` with `get_str_content` to narrow `BaseMessage.content` (typed as `str | list`) to `str` with a `TypeError` guard. All decisions documented in `docs/tasks/001-fix-typecheck-error.md`.

**Tech Stack:** Python 3.12, basedpyright, LangGraph, LangChain-Anthropic, SQLModel, psycopg3, anthropic SDK, presidio

## Global Constraints

- `just type-check` must exit 0 after every task.
- `just test-unit` must stay green after every task.
- `just lint` must pass after every task.
- Never use `Any` in code we own; `cast(SomeType, ...)` is acceptable at system boundaries (DB reads).
- All targeted `# type: ignore` must include the specific error code, e.g. `# type: ignore[call-arg]`.
- Tests live under `apps/backend/tests/unit/` matching the source tree structure.
- Run tests with: `uv run --package second-brain pytest apps/backend/tests/unit -v`
- Run a single test file: `uv run --package second-brain pytest apps/backend/tests/unit/test_utils.py -v`

---

### Task 1: `utils.py` — `get_str_content` helper

**Files:**
- Create: `apps/backend/src/second_brain/utils.py`
- Create: `apps/backend/tests/unit/test_utils.py`

**Interfaces:**
- Produces: `get_str_content(msg: BaseMessage) -> str` — raises `TypeError` if content is not a `str`

- [ ] **Step 1: Write the failing tests**

```python
# apps/backend/tests/unit/test_utils.py
"""Tests for second_brain.utils."""

import pytest
from langchain_core.messages import HumanMessage

from second_brain.utils import get_str_content


def test_get_str_content_returns_str_content():
    """Returns the string content unchanged."""
    msg = HumanMessage(content="hello world")
    assert get_str_content(msg) == "hello world"


def test_get_str_content_returns_empty_string():
    """Empty string content is a valid string — returns it as-is."""
    msg = HumanMessage(content="")
    assert get_str_content(msg) == ""


def test_get_str_content_raises_on_list_content():
    """Raises TypeError when content is a multi-modal list, not a plain string."""
    msg = HumanMessage(content=[{"type": "text", "text": "hello"}])
    with pytest.raises(TypeError, match="Expected str content"):
        get_str_content(msg)


def test_get_str_content_error_message_includes_actual_type():
    """TypeError message names the actual type so callers can diagnose the problem."""
    msg = HumanMessage(content=[{"type": "image_url", "url": "..."}])
    with pytest.raises(TypeError, match="list"):
        get_str_content(msg)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run --package second-brain pytest apps/backend/tests/unit/test_utils.py -v
```

Expected: `ModuleNotFoundError: No module named 'second_brain.utils'`

- [ ] **Step 3: Implement `utils.py`**

```python
# apps/backend/src/second_brain/utils.py
from langchain_core.messages import BaseMessage


def get_str_content(msg: BaseMessage) -> str:
    """Extract the string content from a BaseMessage.

    LangChain types BaseMessage.content as str | list[...] to support
    multi-modal messages. In this app all user messages are plain text;
    this helper asserts that invariant and gives a clear error if it breaks.
    """
    if not isinstance(msg.content, str):
        raise TypeError(
            f"Expected str content, got {type(msg.content).__name__}"
        )
    return msg.content
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run --package second-brain pytest apps/backend/tests/unit/test_utils.py -v
```

Expected: 4 passed

- [ ] **Step 5: Lint and type-check**

```bash
just lint && just type-check
```

Expected: both pass

- [ ] **Step 6: Commit**

```bash
git add apps/backend/src/second_brain/utils.py apps/backend/tests/unit/test_utils.py
git commit -m "feat(types): add get_str_content util to narrow BaseMessage.content to str"
```

---

### Task 2: Node output TypedDicts + `ChunkMetadata`

Add all per-node output TypedDicts to `state.py` (so nodes never return bare `dict`) and add `ChunkMetadata` to `chunking.py` so that `Chunk.metadata` has precisely typed keys.

**Files:**
- Modify: `apps/backend/src/second_brain/graphs/state.py`
- Modify: `apps/backend/src/second_brain/services/chunking.py` (add `ChunkMetadata`, update `Chunk.metadata`)
- Modify: `apps/backend/tests/unit/test_state_types.py` (update metadata fixtures; add output TypedDict tests)

**Interfaces:**
- Produces (from `state.py`):
  - `PickFileOutput`, `IngestionAgentOutput` — for ingestion graph nodes
  - `RedactInboundOutput`, `RedactOutboundOutput`, `RetrieveMemoryOutput`, `RouteQueryOutput`, `RagRetrievalOutput`, `WebResearchOutput`, `SynthesisNodeOutput` — for query graph nodes
- Produces (from `chunking.py`): `ChunkMetadata` TypedDict with keys `source`, `heading_path`, `content_type`, `char_count`

- [ ] **Step 1: Write the failing tests**

Add to `apps/backend/tests/unit/test_state_types.py`:

```python
import typing
# (add to the existing imports at top of the file)
from second_brain.graphs.state import (
    # existing imports…
    PickFileOutput,
    IngestionAgentOutput,
    RedactInboundOutput,
    RedactOutboundOutput,
    RetrieveMemoryOutput,
    RouteQueryOutput,
    RagRetrievalOutput,
    WebResearchOutput,
    SynthesisNodeOutput,
)
from second_brain.services.chunking import ChunkMetadata


# ── ChunkMetadata ────────────────────────────────────────────────────────────

def test_chunk_metadata_construction():
    """ChunkMetadata TypedDict has all four required keys."""
    meta: ChunkMetadata = {
        "source": "intro.md",
        "heading_path": "Getting Started > Install",
        "content_type": "article",
        "char_count": 512,
    }
    assert meta["source"] == "intro.md"
    assert meta["char_count"] == 512


# ── Ingestion node outputs ────────────────────────────────────────────────────

def test_pick_file_output_with_files():
    """PickFileOutput covers the dequeue-from-files branch."""
    out: PickFileOutput = {"in_progress": "doc.md", "files": ["b.md"]}
    assert out["in_progress"] == "doc.md"


def test_pick_file_output_without_files():
    """PickFileOutput covers the retry/idle branch (files key absent)."""
    out: PickFileOutput = {"in_progress": None}
    assert out["in_progress"] is None


def test_ingestion_agent_output_success():
    """IngestionAgentOutput covers the happy-path return shape."""
    out: IngestionAgentOutput = {
        "processed": ["doc.md"],
        "in_progress": None,
        "retry_queue": [],
    }
    assert out["processed"] == ["doc.md"]


def test_ingestion_agent_output_terminal_failure():
    """IngestionAgentOutput covers the terminal-failure return shape."""
    from second_brain.graphs.state import FailedFile
    entry: FailedFile = {"filename": "bad.md", "error": "boom", "retry_count": 3}
    out: IngestionAgentOutput = {
        "in_progress": None,
        "retry_queue": [],
        "failed": [entry],
    }
    assert out["failed"][0]["filename"] == "bad.md"


# ── Query graph node outputs ──────────────────────────────────────────────────

def test_redact_inbound_output():
    from langchain_core.messages import HumanMessage
    out: RedactInboundOutput = {"messages": [HumanMessage(content="hi")]}
    assert len(out["messages"]) == 1


def test_redact_outbound_output():
    out: RedactOutboundOutput = {"final_answer": "safe answer"}
    assert out["final_answer"] == "safe answer"


def test_retrieve_memory_output():
    out: RetrieveMemoryOutput = {"retrieved_memory": []}
    assert out["retrieved_memory"] == []


def test_route_query_output():
    out: RouteQueryOutput = {"routing_decision": "rag"}
    assert out["routing_decision"] == "rag"


def test_rag_retrieval_output():
    from second_brain.graphs.state import RagResult
    result: RagResult = {
        "content": "chunk",
        "score": 0.9,
        "chunk_index": 0,
        "metadata": {"source": "f.md", "heading_path": "", "content_type": "article", "char_count": 100},
    }
    out: RagRetrievalOutput = {"rag_results": [result]}
    assert len(out["rag_results"]) == 1


def test_web_research_output():
    from second_brain.graphs.state import WebResult
    r: WebResult = {"title": "T", "url": "https://x.com", "content": "body"}
    out: WebResearchOutput = {"web_results": [r]}
    assert len(out["web_results"]) == 1


def test_synthesis_node_output():
    out: SynthesisNodeOutput = {
        "final_answer": "42",
        "confidence": 0.9,
        "is_uncertain": False,
    }
    assert out["final_answer"] == "42"
    assert not out["is_uncertain"]


def test_rag_result_metadata_is_typed():
    """RagResult.metadata is annotated with str | int value type — not bare dict."""
    hints = typing.get_type_hints(RagResult)
    # dict[str, str | int] — origin is dict
    assert hints["metadata"].__origin__ is dict


def test_pick_file_output_files_is_not_required():
    """'files' key on PickFileOutput must be NotRequired."""
    hints = typing.get_type_hints(PickFileOutput, include_extras=True)
    assert typing.get_origin(hints["files"]) is typing.NotRequired
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run --package second-brain pytest apps/backend/tests/unit/test_state_types.py -v
```

Expected: `ImportError` for the new symbols

- [ ] **Step 3: Add `ChunkMetadata` to `chunking.py`**

Add at the top of `apps/backend/src/second_brain/services/chunking.py`, before the `Chunk` dataclass:

```python
from typing import TypedDict

class ChunkMetadata(TypedDict):
    source: str
    heading_path: str
    content_type: str
    char_count: int
```

Then update the `Chunk` dataclass field:

```python
# Before
@dataclass
class Chunk:
    content: str
    chunk_index: int
    metadata: dict  # {source, heading_path, content_type, char_count}

# After
@dataclass
class Chunk:
    content: str
    chunk_index: int
    metadata: ChunkMetadata
```

Also update `_make_chunk` inside `chunk_document` — the literal already matches `ChunkMetadata`, no code change needed; the type annotation on the dataclass field is enough for pyright to infer correctly.

- [ ] **Step 4: Add node output TypedDicts to `state.py`**

In `apps/backend/src/second_brain/graphs/state.py`, add after the existing `CorrectionUpdate` TypedDict:

```python
# ── Ingestion node output TypedDicts ─────────────────────────────────────────


class PickFileOutput(TypedDict, total=False):
    in_progress: str | None  # type: ignore[misc]  # always-set key in partial TypedDict
    files: NotRequired[list[str]]


class IngestionAgentOutput(TypedDict):
    in_progress: str | None
    retry_queue: list[FailedFile]
    processed: NotRequired[list[str]]
    failed: NotRequired[list[FailedFile]]


# ── Query graph node output TypedDicts ───────────────────────────────────────


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
```

Also fix `RagResult.metadata` to use typed dict values:

```python
# Before
class RagResult(TypedDict):
    content: str
    score: float
    chunk_index: int
    metadata: dict

# After
class RagResult(TypedDict):
    content: str
    score: float
    chunk_index: int
    metadata: dict[str, str | int]
```

Add missing imports at top of `state.py`:

```python
from langchain_core.messages import BaseMessage  # add if not already present
```

`NotRequired` is already imported; `Literal` is already imported.

Also update the exports in `state.py` — update `__all__` if one exists, or just leave the new names importable.

**Note on `PickFileOutput`:** Python's `TypedDict` does not allow mixing required and `NotRequired` with `total=False` cleanly. Use `total=False` on the whole class and mark `in_progress` as always present via a comment. Alternatively use a simpler pattern:

```python
class PickFileOutput(TypedDict, total=False):
    in_progress: str | None
    files: list[str]
```

Since `total=False` makes all keys optional (matching LangGraph partial-update semantics), this is acceptable — LangGraph merges partial dicts into state.

- [ ] **Step 5: Update existing metadata fixtures in `test_state_types.py`**

The existing tests use bare `{}` or `{"source": "file.md"}` for `RagResult.metadata`. Update them to match the new `dict[str, str | int]` annotation:

```python
# In test_rag_result_construction — update metadata value:
"metadata": {"source": "file.md", "heading_path": "", "content_type": "article", "char_count": 42},

# In test_second_brain_state_with_rag_results — update metadata:
rag: RagResult = {
    "content": "chunk text",
    "score": 0.92,
    "chunk_index": 0,
    "metadata": {"source": "file.md", "heading_path": "", "content_type": "article", "char_count": 10},
}
```

- [ ] **Step 6: Run tests**

```bash
uv run --package second-brain pytest apps/backend/tests/unit/test_state_types.py -v
```

Expected: all pass

- [ ] **Step 7: Lint and type-check**

```bash
just lint && just type-check
```

Note: type-check will still fail on other files — that's fine at this stage; it must not introduce NEW errors compared to before this task.

- [ ] **Step 8: Commit**

```bash
git add apps/backend/src/second_brain/graphs/state.py \
        apps/backend/src/second_brain/services/chunking.py \
        apps/backend/tests/unit/test_state_types.py
git commit -m "feat(types): add node output TypedDicts and ChunkMetadata"
```

---

### Task 3: Annotation fixes — `db/models.py`, `config.py`, `services/pii.py`

Pure annotation / targeted-ignore changes. No behavior change. Verification is `just type-check` showing no errors in these three files.

**Files:**
- Modify: `apps/backend/src/second_brain/db/models.py`
- Modify: `apps/backend/src/second_brain/config.py`
- Modify: `apps/backend/src/second_brain/services/pii.py`

**Interfaces:** None (no new public symbols)

- [ ] **Step 1: Fix `db/models.py`**

Add `ClassVar` import and annotate all `__tablename__` attributes:

```python
# Add to imports at top of models.py:
from typing import ClassVar, Optional  # Optional likely already there
```

Replace every `__tablename__ = "..."` with `__tablename__: ClassVar[str] = "..."`:

```python
# ChatHistory
__tablename__: ClassVar[str] = "chat_history"

# IngestedDocument
__tablename__: ClassVar[str] = "ingested_documents"

# DocumentChunk
__tablename__: ClassVar[str] = "document_chunks"

# LearnedFact
__tablename__: ClassVar[str] = "learned_facts"

# ModelCorrection
__tablename__: ClassVar[str] = "model_corrections"
```

Fix bare `dict` fields:

```python
# ChatHistory.thread_data — LangGraph manages this structure; use object for JSONB
thread_data: dict[str, object] = Field(
    default_factory=dict, sa_column=Column(JSONB, nullable=False)
)

# DocumentChunk.chunk_metadata
chunk_metadata: Optional[dict[str, str | int]] = Field(
    default=None, sa_column=Column("metadata", JSONB, nullable=True)
)
```

- [ ] **Step 2: Fix `config.py`**

```python
# Before (line 43)
settings = Settings()

# After
settings = Settings()  # type: ignore[call-arg]
```

- [ ] **Step 3: Fix `services/pii.py`**

```python
# Before (line 51-53)
    return _anonymizer.anonymize(
        text=text, analyzer_results=results, operators=_OPERATORS
    ).text

# After
    return _anonymizer.anonymize(  # type: ignore[arg-type]
        text=text, analyzer_results=results, operators=_OPERATORS
    ).text
```

- [ ] **Step 4: Run unit tests to check for regressions**

```bash
uv run --package second-brain pytest apps/backend/tests/unit/test_models.py \
    apps/backend/tests/unit/test_settings/ \
    apps/backend/tests/unit/test_services/test_pii.py -v
```

Expected: all pass

- [ ] **Step 5: Lint and type-check**

```bash
just lint && just type-check
```

- [ ] **Step 6: Commit**

```bash
git add apps/backend/src/second_brain/db/models.py \
        apps/backend/src/second_brain/config.py \
        apps/backend/src/second_brain/services/pii.py
git commit -m "fix(types): add ClassVar annotations and targeted type-ignores for stub gaps"
```

---

### Task 4: Graph typing — `ingestion_graph.py` + `query_graph.py`

Fix graph builder return types and add targeted ignores for `AsyncPostgresSaver`.

**Files:**
- Modify: `apps/backend/src/second_brain/graphs/ingestion_graph.py`
- Modify: `apps/backend/src/second_brain/graphs/query_graph.py`

**Interfaces:**
- `build_ingestion_graph() -> CompiledStateGraph[IngestionState, None, IngestionState, IngestionState]`
- `build_query_graph(postgres_url: str) -> tuple[CompiledStateGraph[SecondBrainState, None, SecondBrainState, SecondBrainState], AsyncConnectionPool[Any]]`

- [ ] **Step 1: Fix `ingestion_graph.py`**

```python
# Before
from langgraph.graph import END, StateGraph

def pick_file_node(state: IngestionState) -> dict:
    ...

def build_ingestion_graph() -> StateGraph:
    builder = StateGraph(IngestionState)
    ...
    return builder.compile()
```

```python
# After
from typing import Any

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from second_brain.graphs.state import IngestionState, PickFileOutput

def pick_file_node(state: IngestionState) -> PickFileOutput:
    """Move the next pending or retry file into in_progress.
    ...
    """
    if state["files"]:
        return {
            "files": state["files"][1:],
            "in_progress": state["files"][0],
        }
    if state["retry_queue"]:
        return {
            "in_progress": state["retry_queue"][0]["filename"],
        }
    return {"in_progress": None}


def build_ingestion_graph() -> CompiledStateGraph[IngestionState, None, IngestionState, IngestionState]:
    builder = StateGraph(IngestionState)

    builder.add_node("pick_file", pick_file_node)
    builder.add_node("ingest", ingestion_agent_node)

    builder.set_entry_point("pick_file")
    builder.add_edge("pick_file", "ingest")
    builder.add_conditional_edges("ingest", _route_after_ingest)

    return builder.compile()
```

- [ ] **Step 2: Fix `query_graph.py`**

```python
# Before
async def build_query_graph(postgres_url: str) -> tuple:
    ...
    checkpointer = AsyncPostgresSaver(pool)

# After
from typing import Any

from langgraph.graph.state import CompiledStateGraph

async def build_query_graph(
    postgres_url: str,
) -> tuple[
    CompiledStateGraph[SecondBrainState, None, SecondBrainState, SecondBrainState],
    AsyncConnectionPool[Any],  # ponytail: Any is psycopg row-factory type param — not our code
]:
    ...
    checkpointer = AsyncPostgresSaver(pool)  # type: ignore[arg-type]
```

- [ ] **Step 3: Run graph unit tests**

```bash
uv run --package second-brain pytest \
    apps/backend/tests/unit/test_graphs/ \
    apps/backend/tests/unit/test_api/test_routers/test_ingest.py -v
```

Expected: all pass

- [ ] **Step 4: Lint and type-check**

```bash
just lint && just type-check
```

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/second_brain/graphs/ingestion_graph.py \
        apps/backend/src/second_brain/graphs/query_graph.py
git commit -m "fix(types): annotate graph builder return types with CompiledStateGraph"
```

---

### Task 5: `nodes/ingestion_agent.py` — TextBlock narrowing + return type

**Files:**
- Modify: `apps/backend/src/second_brain/nodes/ingestion_agent.py`

**Interfaces:**
- `ingestion_agent_node(state: IngestionState) -> IngestionAgentOutput`

- [ ] **Step 1: Fix `_generate_contextual_header` — narrow content block to TextBlock**

```python
# Before (line 89)
    return response.content[0].text.strip()

# After
    from anthropic.types import TextBlock
    text_block = next(b for b in response.content if isinstance(b, TextBlock))
    return text_block.text.strip()
```

Move the import to the top of the file (with other anthropic imports):

```python
import anthropic
from anthropic.types import TextBlock  # add this line
```

- [ ] **Step 2: Fix the node return type**

```python
# Before (line 145)
async def ingestion_agent_node(state: IngestionState) -> dict:

# After
from second_brain.graphs.state import FailedFile, IngestionAgentOutput, IngestionState

async def ingestion_agent_node(state: IngestionState) -> IngestionAgentOutput:
```

The three return literals inside the function already match `IngestionAgentOutput` — no body changes needed.

- [ ] **Step 3: Run ingestion agent tests**

```bash
uv run --package second-brain pytest apps/backend/tests/unit/test_nodes/test_ingestion_agent.py -v
```

Expected: all pass

- [ ] **Step 4: Lint and type-check**

```bash
just lint && just type-check
```

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/second_brain/nodes/ingestion_agent.py
git commit -m "fix(types): narrow Anthropic TextBlock and type ingestion_agent_node return"
```

---

### Task 6: `nodes/orchestrator.py` + `nodes/synthesis.py`

Fix `model=` → `model_name=`, type the structured-output assignment, return proper TypedDicts.

**Files:**
- Modify: `apps/backend/src/second_brain/nodes/orchestrator.py`
- Modify: `apps/backend/src/second_brain/nodes/synthesis.py`

**Interfaces:**
- `route_query(state: SecondBrainState) -> RouteQueryOutput`
- `synthesize_answer(state: SecondBrainState) -> SynthesisNodeOutput`

- [ ] **Step 1: Fix `orchestrator.py`**

```python
# Before
from second_brain.graphs.state import SecondBrainState

_structured_llm = ChatAnthropic(model="claude-haiku-4-5").with_structured_output(
    _RoutingOutput
)

async def route_query(state: SecondBrainState) -> dict:
    ...
    result: _RoutingOutput = await _structured_llm.ainvoke(prompt)
    return {"routing_decision": result.routing_decision}
```

```python
# After
from second_brain.graphs.state import RouteQueryOutput, SecondBrainState

_structured_llm = ChatAnthropic(model_name="claude-haiku-4-5").with_structured_output(
    _RoutingOutput
)

async def route_query(state: SecondBrainState) -> RouteQueryOutput:
    ...
    result: _RoutingOutput = await _structured_llm.ainvoke(prompt)  # type: ignore[assignment]
    return {"routing_decision": result.routing_decision}
```

- [ ] **Step 2: Fix `synthesis.py`**

```python
# Before
from second_brain.graphs.state import SecondBrainState

_structured_llm = ChatAnthropic(model="claude-sonnet-4-6").with_structured_output(
    _SynthesisOutput
)

async def synthesize_answer(state: SecondBrainState) -> dict:
    ...
    output: _SynthesisOutput = await _structured_llm.ainvoke(prompt)
    ...
    return {
        "final_answer": output.final_answer,
        "confidence": confidence,
        "is_uncertain": confidence < _UNCERTAINTY_THRESHOLD,
    }
```

```python
# After
from second_brain.graphs.state import SecondBrainState, SynthesisNodeOutput

_structured_llm = ChatAnthropic(model_name="claude-sonnet-4-6").with_structured_output(
    _SynthesisOutput
)

async def synthesize_answer(state: SecondBrainState) -> SynthesisNodeOutput:
    ...
    output: _SynthesisOutput = await _structured_llm.ainvoke(prompt)  # type: ignore[assignment]
    ...
    return {
        "final_answer": output.final_answer,
        "confidence": confidence,
        "is_uncertain": confidence < _UNCERTAINTY_THRESHOLD,
    }
```

- [ ] **Step 3: Run node tests**

```bash
uv run --package second-brain pytest \
    apps/backend/tests/unit/test_nodes/test_orchestrator.py \
    apps/backend/tests/unit/test_nodes/test_synthesis.py -v
```

Expected: all pass

- [ ] **Step 4: Lint and type-check**

```bash
just lint && just type-check
```

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/second_brain/nodes/orchestrator.py \
        apps/backend/src/second_brain/nodes/synthesis.py
git commit -m "fix(types): use model_name= and type node returns for orchestrator and synthesis"
```

---

### Task 7: Remaining nodes + `ingest.py` — apply `get_str_content` and typed returns

Apply `get_str_content` in the four nodes that access `messages[-1].content`, fix their return types, and fix the `isinstance(result, BaseException)` guard in the ingest router.

**Files:**
- Modify: `apps/backend/src/second_brain/nodes/pii_redaction.py`
- Modify: `apps/backend/src/second_brain/nodes/rag_retrieval.py`
- Modify: `apps/backend/src/second_brain/nodes/web_research.py`
- Modify: `apps/backend/src/second_brain/nodes/memory_retrieval.py`
- Modify: `apps/backend/src/second_brain/api/routers/ingest.py`

**Interfaces:** All changed node signatures below.

- [ ] **Step 1: Fix `pii_redaction.py`**

```python
# Before
from second_brain.graphs.state import SecondBrainState
from second_brain.services.pii import redact_pii

def redact_inbound(state: SecondBrainState) -> dict:
    ...
    redacted = HumanMessage(content=redact_pii(last.content), id=last.id)
    return {"messages": [redacted]}

def redact_outbound(state: SecondBrainState) -> dict:
    return {"final_answer": redact_pii(state["final_answer"])}
```

```python
# After
from second_brain.graphs.state import RedactInboundOutput, RedactOutboundOutput, SecondBrainState
from second_brain.services.pii import redact_pii
from second_brain.utils import get_str_content

def redact_inbound(state: SecondBrainState) -> RedactInboundOutput:
    if not state["messages"]:
        raise ValueError("redact_inbound requires at least one message in state")
    last = state["messages"][-1]
    redacted = HumanMessage(content=redact_pii(get_str_content(last)), id=last.id)
    return {"messages": [redacted]}

def redact_outbound(state: SecondBrainState) -> RedactOutboundOutput:
    return {"final_answer": redact_pii(state["final_answer"])}
```

- [ ] **Step 2: Fix `rag_retrieval.py`**

```python
# Before
from second_brain.graphs.state import SecondBrainState

async def _query_pgvector(
    embedding: list[float], postgres_url: str, top_k: int = 5
) -> list[dict]:
    ...
    return [
        {
            "content": r["content"],
            "score": float(r["score"]),
            "chunk_index": r["chunk_index"],
            "metadata": dict(r["metadata"]) if r["metadata"] else {},
        }
        for r in rows
    ]

async def retrieve_from_rag(state: SecondBrainState) -> dict:
    query = state["messages"][-1].content
    embedding = await _embed_query(query, settings.ollama_base_url)
    rows = await _query_pgvector(embedding, settings.postgres_url)
    return {"rag_results": rows}
```

```python
# After
from typing import cast

from second_brain.graphs.state import RagResult, RagRetrievalOutput, SecondBrainState
from second_brain.utils import get_str_content

async def _query_pgvector(
    embedding: list[float], postgres_url: str, top_k: int = 5
) -> list[RagResult]:
    ...
    return [
        {
            "content": r["content"],
            "score": float(r["score"]),
            "chunk_index": r["chunk_index"],
            "metadata": cast(
                "dict[str, str | int]",
                dict(r["metadata"]) if r["metadata"] else {},
            ),
        }
        for r in rows
    ]

async def retrieve_from_rag(state: SecondBrainState) -> RagRetrievalOutput:
    query = get_str_content(state["messages"][-1])
    embedding = await _embed_query(query, settings.ollama_base_url)
    rows = await _query_pgvector(embedding, settings.postgres_url)
    return {"rag_results": rows}
```

- [ ] **Step 3: Fix `web_research.py`**

```python
# Before
async def search_web(state: SecondBrainState) -> dict:
    query = state["messages"][-1].content
    client = TavilyClient(api_key=settings.tavily_api_key.get_secret_value())
    response = await asyncio.to_thread(lambda: client.search(query, max_results=3))

# After
from second_brain.graphs.state import SecondBrainState, WebResearchOutput
from second_brain.utils import get_str_content

async def search_web(state: SecondBrainState) -> WebResearchOutput:
    query = get_str_content(state["messages"][-1])
    client = TavilyClient(api_key=settings.tavily_api_key.get_secret_value())
    response = await asyncio.to_thread(lambda: client.search(query, max_results=3))
    web_results = [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": r.get("content", ""),
        }
        for r in response.get("results", [])
    ]
    return {"web_results": web_results}
```

- [ ] **Step 4: Fix `memory_retrieval.py`**

```python
# Before
async def retrieve_memory(state: SecondBrainState) -> dict:
    return {"retrieved_memory": []}

# After
from second_brain.graphs.state import RetrieveMemoryOutput, SecondBrainState

async def retrieve_memory(state: SecondBrainState) -> RetrieveMemoryOutput:
    return {"retrieved_memory": []}
```

- [ ] **Step 5: Fix `ingest.py` — `BaseException` narrowing**

```python
# Before (line 62)
    for url, result in zip(request.urls, results):
        if isinstance(result, Exception):

# After
    for url, result in zip(request.urls, results):
        if isinstance(result, BaseException):
```

- [ ] **Step 6: Run all affected node tests and ingest router tests**

```bash
uv run --package second-brain pytest \
    apps/backend/tests/unit/test_nodes/test_pii_redaction.py \
    apps/backend/tests/unit/test_nodes/test_rag_retrieval.py \
    apps/backend/tests/unit/test_nodes/test_web_research.py \
    apps/backend/tests/unit/test_nodes/test_memory_retrieval.py \
    apps/backend/tests/unit/test_api/test_routers/test_ingest.py -v
```

Expected: all pass

- [ ] **Step 7: Full unit test suite**

```bash
just test-unit
```

Expected: all pass

- [ ] **Step 8: Lint and full type-check**

```bash
just lint && just type-check
```

Expected: `just type-check` exits 0 — **this is the milestone**

- [ ] **Step 9: Commit**

```bash
git add apps/backend/src/second_brain/nodes/pii_redaction.py \
        apps/backend/src/second_brain/nodes/rag_retrieval.py \
        apps/backend/src/second_brain/nodes/web_research.py \
        apps/backend/src/second_brain/nodes/memory_retrieval.py \
        apps/backend/src/second_brain/api/routers/ingest.py
git commit -m "fix(types): apply get_str_content and typed returns across remaining nodes"
```

---

### Task 8: Final verification

Confirm all quality gates pass end-to-end before opening a PR.

**Files:** None

- [ ] **Step 1: Full lint + format + type-check**

```bash
just lint && just format && just type-check
```

Expected: all exit 0, `just format` produces no changes (or commit any formatting diff)

- [ ] **Step 2: Full unit test suite**

```bash
just test-unit
```

Expected: all pass, no regressions

- [ ] **Step 3: Confirm `just type-check` reports zero errors and zero warnings**

Scan the output — any remaining `error:` lines mean a task was missed. Any remaining `warning:` lines that cause exit 1 must be addressed. The run must exit 0.

- [ ] **Step 4: Invoke enhanced-review skill**

Use the `enhanced-review` skill on the diff to catch any issues before creating the PR.

- [ ] **Step 5: Open PR**

```bash
git push origin fix/typecheck-errors
gh pr create \
  --title "fix(types): resolve all 50 basedpyright errors" \
  --body "Fixes all type-check errors across 12 backend files.

## Changes
- New \`utils.py\`: \`get_str_content\` helper narrows \`BaseMessage.content\` to \`str\`
- New node output TypedDicts in \`state.py\`: 9 TypedDicts replacing bare \`dict\` returns
- \`ChunkMetadata\` TypedDict in \`chunking.py\` for precise chunk metadata shape
- \`ClassVar[str]\` on all SQLModel \`__tablename__\` attributes
- \`CompiledStateGraph\` return types on both graph builders
- \`isinstance(result, BaseException)\` in \`ingest.py\` URL handler
- \`TextBlock\` narrowing in \`ingestion_agent.py\`
- \`model_name=\` in ChatAnthropic calls (stub-visible alias for \`model=\`)
- Targeted \`# type: ignore[<code>]\` for 5 third-party stub gaps

## Verification
- \`just type-check\` exits 0
- \`just test-unit\` passes
- \`just lint\` passes"
```

---

## Self-Review

**Spec coverage check:**

| Error group from `docs/tasks/001-fix-typecheck-error.md` | Task |
|---|---|
| D1 — library stub gaps (`type: ignore`) | Tasks 3, 4, 6 |
| D2 — TextBlock narrowing | Task 5 |
| D3 — `isinstance(result, BaseException)` | Task 7 |
| D4 — `CompiledStateGraph` return type | Task 4 |
| D5 — node output TypedDicts | Task 2 |
| D6 — `get_str_content` util | Tasks 1, 7 |
| D7 — presidio `RecognizerResult` ignore | Task 3 |
| D8 — `AsyncConnectionPool[Any]` exception | Task 4 |
| D9 — `ClassVar[str]` for `__tablename__` | Task 3 |
| D10 — `model_name=` in ChatAnthropic | Task 6 |

All 10 decisions covered. No gaps found.
