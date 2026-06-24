# Task 001 — Fix Type-Check Errors

## Context

Running `just type-check` (basedpyright) exits with code 1 across 12 files.
50 actual errors identified; remainder are warnings that also block the check.

---

## Decisions Made (grilling session 2026-06-24)

### D1 — Library stub gaps → targeted `# type: ignore[<code>]`

Applies to:

- `ChatAnthropic(model=...)` — works at runtime; stubs only know `model_name`
- `Settings()` — pydantic-settings injects env vars; pyright sees missing required args
- `__tablename__ = "..."` in SQLModel — valid pattern; stubs type it as `declared_attr[Unknown]`
- `AsyncPostgresSaver(pool)` — psycopg pool type doesn't match LangGraph's `Conn` stub
- `with_structured_output().ainvoke()` → returns `dict | BaseModel`, not the specific Pydantic class
- presidio `RecognizerResult` list type mismatch

**Why:** These are stub gaps, not real bugs. Casts/wrappers add noise for zero runtime benefit.

---

### D2 — `response.content[0].text` in `ingestion_agent.py` → isinstance narrowing

```python
# Before
return response.content[0].text.strip()

# After
from anthropic.types import TextBlock
return next(b for b in response.content if isinstance(b, TextBlock)).text.strip()
```

**Why:** Safer than a cast — raises `StopIteration` immediately if the API ever returns a non-TextBlock first, rather than a confusing `AttributeError`.

---

### D3 — `asyncio.gather` narrowing in `ingest.py` → `isinstance(result, BaseException)`

```python
# Before
if isinstance(result, Exception):

# After
if isinstance(result, BaseException):
```

**Why:** `gather(return_exceptions=True)` returns `BaseException`, not just `Exception`. `isinstance(..., Exception)` doesn't narrow `BaseException` away in the else branch.

---

### D4 — `ingestion_graph.py` return type → `CompiledStateGraph[...]`

```python
# Before
def build_ingestion_graph() -> StateGraph:

# After
def build_ingestion_graph() -> CompiledStateGraph[IngestionState, None, IngestionState, IngestionState]:
```

**Why:** Correct type, and fixes the downstream `ainvoke` error in `ingest.py` for free.

---

### D5 — Node `dict` return types → per-node output TypedDicts in `state.py`

No `Any`. Each node function's return type is a TypedDict that exactly matches the keys it writes.

TypedDicts to add to `state.py`:

| TypedDict              | Fields                                                                                                                                    |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `PickFileOutput`       | `files: NotRequired[list[str]]`, `in_progress: str \| None`                                                                               |
| `IngestionAgentOutput` | `processed: NotRequired[list[str]]`, `in_progress: str \| None`, `retry_queue: list[FailedFile]`, `failed: NotRequired[list[FailedFile]]` |
| `RedactInboundOutput`  | `messages: list[BaseMessage]`                                                                                                             |
| `RedactOutboundOutput` | `final_answer: str`                                                                                                                       |
| `RetrieveMemoryOutput` | `retrieved_memory: list[MemoryItem]`                                                                                                      |
| `RouteQueryOutput`     | `routing_decision: Literal["rag", "web", "both", "neither"]`                                                                              |
| `RagRetrievalOutput`   | `rag_results: list[RagResult]`                                                                                                            |
| `WebResearchOutput`    | `web_results: list[WebResult]`                                                                                                            |
| `SynthesisNodeOutput`  | `final_answer: str`, `confidence: float`, `is_uncertain: bool`                                                                            |

**Why:** We know what our nodes return; TypedDicts make the contract explicit and avoid `Any`.

---

### D6 — `messages[-1].content` typed as `str | list[...]` → util helper with `TypeError`

New file: `apps/backend/src/second_brain/utils.py`

```python
def get_str_content(msg: BaseMessage) -> str:
    if not isinstance(msg.content, str):
        raise TypeError(f"Expected str content, got {type(msg.content)}")
    return msg.content
```

**Why:** Repeated in 4+ nodes; a util function is the single change point. Raises `TypeError` (option C) rather than a bare `assert` for a clearer error message.
**Location:** Dedicated `utils.py` (not `state.py`) since it is a utility, not state definition.

---

### D7 — presidio `RecognizerResult` mismatch → `# type: ignore[arg-type]`

Same runtime class, different stub import paths. Targeted ignore on the `anonymize()` call.

---

### D8 — `AsyncConnectionPool` type param `Any` is acceptable

`query_graph.py` returns `tuple[CompiledStateGraph[...], AsyncConnectionPool[Any]]`.
The `Any` is the psycopg row-factory type parameter — imposed by the library, not our code.
This is the one approved exception to the no-`Any` rule.

---

### D9 — `__tablename__` in `db/models.py` → `ClassVar[str]`

```python
from typing import ClassVar
__tablename__: ClassVar[str] = "chat_history"
```

Not a `# type: ignore` — this is the correct SQLAlchemy annotation.

---

### D10 — `ChatAnthropic(model=...)` → `model_name=`

`model=` is a runtime alias that works but is invisible to the stubs. Change to `model_name=` in `orchestrator.py` and `synthesis.py`.

---

## Files to Touch

| File                        | Change                                                              |
| --------------------------- | ------------------------------------------------------------------- |
| `utils.py` (new)            | `get_str_content` helper                                            |
| `graphs/state.py`           | Add 9 node output TypedDicts; fix `RagResult.metadata: dict`        |
| `services/chunking.py`      | `Chunk.metadata: dict` → `dict[str, str \| int]`                    |
| `db/models.py`              | `ClassVar[str]` for all `__tablename__`; fix bare `dict` fields     |
| `config.py`                 | `# type: ignore[call-arg]` on `Settings()`                          |
| `graphs/ingestion_graph.py` | Fix return type; `pick_file_node` → `PickFileOutput`                |
| `graphs/query_graph.py`     | Fix return type; `# type: ignore[arg-type]` on `AsyncPostgresSaver` |
| `nodes/ingestion_agent.py`  | `IngestionAgentOutput`; fix `.text` narrowing                       |
| `nodes/orchestrator.py`     | `model_name=`; `RouteQueryOutput`; `# type: ignore[assignment]`     |
| `nodes/synthesis.py`        | `model_name=`; `SynthesisNodeOutput`; `# type: ignore[assignment]`  |
| `nodes/pii_redaction.py`    | Typed returns; `get_str_content`                                    |
| `nodes/rag_retrieval.py`    | Typed returns; `get_str_content`; `list[RagResult]`                 |
| `nodes/web_research.py`     | `WebResearchOutput`; `get_str_content`                              |
| `nodes/memory_retrieval.py` | `RetrieveMemoryOutput`                                              |
| `services/pii.py`           | `# type: ignore[arg-type]`                                          |
