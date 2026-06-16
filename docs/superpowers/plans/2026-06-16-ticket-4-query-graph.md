# Ticket 4: Query Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the full `POST /query` flow — PII guardrail (inbound + outbound), LLM orchestrator routing, RAG retrieval, web research, synthesis with confidence scoring, and session continuity via LangGraph checkpointing with PostgresSaver.

**Architecture:** A `StateGraph(SecondBrainState)` wires eight nodes sequentially with a fan-out step: `redact_inbound → retrieve_memory → orchestrator → (Send fan-out) → rag_retrieval / web_research → synthesis → redact_outbound`. The graph is checkpointed per `thread_id` (= `session_id`) in Postgres so conversation history persists across API calls. The `messages` field uses LangGraph's `add_messages` reducer so new messages are appended to the checkpoint rather than overwriting it.

**Tech Stack:** FastAPI, LangGraph (`StateGraph`, `Send`, `AsyncPostgresSaver`), `langchain-anthropic` (`claude-haiku-4-5`, `claude-sonnet-4-6`), `presidio-analyzer` + `presidio-anonymizer` + `spacy en_core_web_lg`, `pgvector-python` + `asyncpg`, Ollama `qwen3-embedding:0.6b`, Tavily Python SDK, `uuid6`, `psycopg-pool`, `pytest-asyncio`.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `apps/backend/src/second_brain/graphs/state.py` | Add `SecondBrainState` + supporting TypedDicts |
| Create | `apps/backend/src/second_brain/services/pii.py` | `redact_pii(text) -> str` using Presidio |
| Create | `apps/backend/src/second_brain/nodes/pii_redaction.py` | Inbound + outbound PII graph nodes |
| Create | `apps/backend/src/second_brain/nodes/memory_retrieval.py` | Stub: returns `retrieved_memory=[]` |
| Create | `apps/backend/src/second_brain/nodes/orchestrator.py` | LLM routing via `claude-haiku-4-5` |
| Create | `apps/backend/src/second_brain/nodes/rag_retrieval.py` | pgvector cosine similarity, top-k=5 |
| Create | `apps/backend/src/second_brain/nodes/web_research.py` | Tavily search, rate-limited |
| Create | `apps/backend/src/second_brain/nodes/synthesis.py` | `claude-sonnet-4-6`, confidence scoring |
| Create | `apps/backend/src/second_brain/graphs/query_graph.py` | Full LangGraph with PostgresSaver |
| Modify | `apps/backend/src/second_brain/api/schemas.py` | Add `QueryRequest`, `QueryResponse` |
| Create | `apps/backend/src/second_brain/api/routers/query.py` | `POST /query` handler |
| Modify | `apps/backend/src/second_brain/main.py` | Register `/query` router |
| Create | `apps/backend/tests/unit/conftest.py` | `make_state()` factory for all unit tests |
| Create | `apps/backend/tests/unit/test_services/test_pii.py` | Unit tests for PII service |
| Create | `apps/backend/tests/unit/test_nodes/test_pii_redaction.py` | Unit tests for PII nodes |
| Create | `apps/backend/tests/unit/test_nodes/test_orchestrator.py` | Unit tests for orchestrator |
| Create | `apps/backend/tests/unit/test_nodes/test_rag_retrieval.py` | Unit tests for RAG retrieval |
| Create | `apps/backend/tests/unit/test_nodes/test_web_research.py` | Unit tests for web research |
| Create | `apps/backend/tests/unit/test_nodes/test_synthesis.py` | Unit tests for synthesis |
| Create | `apps/backend/tests/integration/test_query_graph.py` | Integration tests: AC-5, AC-6, AC-10 |

---

### Task 1: SecondBrainState TypedDicts + Unit Test Conftest

**Files:**
- Modify: `apps/backend/src/second_brain/graphs/state.py`
- Create: `apps/backend/tests/unit/conftest.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/backend/tests/unit/test_state_types.py
from second_brain.graphs.state import (
    RagResult,
    WebResult,
    MemoryItem,
    FactUpdate,
    CorrectionUpdate,
    SecondBrainState,
)
from langchain_core.messages import HumanMessage


def test_rag_result_structure():
    item: RagResult = {
        "content": "some content",
        "score": 0.85,
        "chunk_index": 0,
        "metadata": {"source": "doc.md"},
    }
    assert item["score"] == 0.85


def test_second_brain_state_structure():
    state: SecondBrainState = {
        "session_id": "abc-123",
        "messages": [HumanMessage(content="Hello")],
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
    assert state["routing_decision"] == "neither"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd apps/backend && pytest tests/unit/test_state_types.py -v
```

Expected: `ImportError` — `SecondBrainState` not defined yet.

- [ ] **Step 3: Add SecondBrainState TypedDicts to `graphs/state.py`**

Open `apps/backend/src/second_brain/graphs/state.py`. Keep any existing content (e.g., `IngestionState`) and append the following:

```python
# apps/backend/src/second_brain/graphs/state.py
# --- append below existing IngestionState content ---

from typing import Annotated, Literal
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


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
    conflicts_with: list[str]  # IDs of conflicting existing facts


class CorrectionUpdate(TypedDict):
    original_answer: str  # from messages[-2] (prior assistant response)
    correction: str
    root_cause: str


class SecondBrainState(TypedDict):
    session_id: str
    # Annotated with add_messages so LangGraph appends new messages
    # to the checkpoint rather than overwriting — required for session continuity (AC-10)
    messages: Annotated[list[BaseMessage], add_messages]
    rag_results: list[RagResult]
    web_results: list[WebResult]
    retrieved_memory: list[MemoryItem]
    routing_decision: Literal["rag", "web", "both", "neither"]
    final_answer: str
    confidence: float
    is_uncertain: bool
    awaiting_correction: bool        # persisted across turns via LangGraph checkpointing
    awaiting_conflict_clarification: bool
    conflict_context: list[str]
    fact_updates: list[FactUpdate]   # populated by Memory Agent (Ticket 5)
    correction_updates: list[CorrectionUpdate]  # populated by Memory Agent (Ticket 5)
```

> **Note:** The `TypedDict` import must already be at the top of `state.py` from the `IngestionState` definitions in Ticket 3. If not, add `from typing import TypedDict` to the top.

- [ ] **Step 4: Create the unit test conftest with `make_state` factory**

```python
# apps/backend/tests/unit/conftest.py
import pytest
from langchain_core.messages import HumanMessage
from second_brain.graphs.state import SecondBrainState


def make_state(**overrides) -> SecondBrainState:
    """Factory for SecondBrainState with safe defaults. Pass keyword args to override."""
    defaults: SecondBrainState = {
        "session_id": "test-session-001",
        "messages": [HumanMessage(content="Hello")],
        "rag_results": [],
        "web_results": [],
        "retrieved_memory": [],
        "routing_decision": "neither",
        "final_answer": "",
        "confidence": 0.9,
        "is_uncertain": False,
        "awaiting_correction": False,
        "awaiting_conflict_clarification": False,
        "conflict_context": [],
        "fact_updates": [],
        "correction_updates": [],
    }
    defaults.update(overrides)  # type: ignore[typeddict-item]
    return defaults
```

- [ ] **Step 5: Run all state tests to verify they pass**

```bash
cd apps/backend && pytest tests/unit/test_state_types.py -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
cd apps/backend && git add \
  src/second_brain/graphs/state.py \
  tests/unit/conftest.py \
  tests/unit/test_state_types.py
git commit -m "feat(state): add SecondBrainState TypedDicts with add_messages reducer"
```

---

### Task 2: PII Service

**Files:**
- Create: `apps/backend/src/second_brain/services/__init__.py`
- Create: `apps/backend/src/second_brain/services/pii.py`
- Create: `apps/backend/tests/unit/test_services/__init__.py`
- Create: `apps/backend/tests/unit/test_services/test_pii.py`

**Dependency:** Install `presidio-analyzer presidio-anonymizer spacy` and download the spaCy model before running tests:
```bash
pip install presidio-analyzer presidio-anonymizer spacy
python -m spacy download en_core_web_lg
```

- [ ] **Step 1: Write the failing tests**

```python
# apps/backend/tests/unit/test_services/test_pii.py
import pytest
from second_brain.services.pii import redact_pii


def test_redact_person_name():
    result = redact_pii("Hello, my name is John Smith.")
    assert "[NAME]" in result
    assert "John Smith" not in result


def test_redact_email():
    result = redact_pii("Contact me at alice@example.com for details.")
    assert "[EMAIL]" in result
    assert "alice@example.com" not in result


def test_redact_phone_number():
    result = redact_pii("Call me at 555-867-5309 anytime.")
    assert "[PHONE]" in result
    assert "867-5309" not in result


def test_no_pii_passthrough():
    text = "The weather in Tokyo is sunny today."
    result = redact_pii(text)
    # Non-PII text must not be mangled
    assert "weather" in result
    assert "sunny" in result


def test_multiple_pii_types_in_one_string():
    text = "Jane Doe's email is jane.doe@corp.com and her phone is +1-800-555-0199."
    result = redact_pii(text)
    assert "Jane Doe" not in result
    assert "jane.doe@corp.com" not in result
    assert "[NAME]" in result
    assert "[EMAIL]" in result


def test_empty_string():
    result = redact_pii("")
    assert result == ""


def test_credit_card_redaction():
    result = redact_pii("My card number is 4111111111111111.")
    assert "4111111111111111" not in result
    assert "[CARD]" in result
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd apps/backend && pytest tests/unit/test_services/test_pii.py -v
```

Expected: `ModuleNotFoundError` for `second_brain.services.pii`.

- [ ] **Step 3: Implement the PII service**

```python
# apps/backend/src/second_brain/services/__init__.py
# (empty)
```

```python
# apps/backend/src/second_brain/services/pii.py
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

_ENTITIES = [
    "PERSON",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "LOCATION",
    "DATE_TIME",
    "CREDIT_CARD",
    "IBAN_CODE",
    "MEDICAL_LICENSE",
    "NRP",
    "US_SSN",
    "US_PASSPORT",
    "IP_ADDRESS",
]

_OPERATORS: dict[str, OperatorConfig] = {
    "PERSON": OperatorConfig("replace", {"new_value": "[NAME]"}),
    "EMAIL_ADDRESS": OperatorConfig("replace", {"new_value": "[EMAIL]"}),
    "PHONE_NUMBER": OperatorConfig("replace", {"new_value": "[PHONE]"}),
    "LOCATION": OperatorConfig("replace", {"new_value": "[ADDRESS]"}),
    "DATE_TIME": OperatorConfig("replace", {"new_value": "[DATE]"}),
    "CREDIT_CARD": OperatorConfig("replace", {"new_value": "[CARD]"}),
    "IBAN_CODE": OperatorConfig("replace", {"new_value": "[CARD]"}),
    "MEDICAL_LICENSE": OperatorConfig("replace", {"new_value": "[MEDICAL]"}),
    "NRP": OperatorConfig("replace", {"new_value": "[ID]"}),
    "US_SSN": OperatorConfig("replace", {"new_value": "[ID]"}),
    "US_PASSPORT": OperatorConfig("replace", {"new_value": "[ID]"}),
    "IP_ADDRESS": OperatorConfig("replace", {"new_value": "[IP]"}),
}

# Module-level singletons — spaCy load is expensive, do it once
_analyzer = AnalyzerEngine()
_anonymizer = AnonymizerEngine()


def redact_pii(text: str) -> str:
    """Detect and redact PII from text using Presidio + spaCy en_core_web_lg.

    Returns the redacted text with typed placeholders such as [NAME], [EMAIL],
    [PHONE], [ADDRESS], [CARD], [MEDICAL], [ID], [DATE], [IP].
    """
    if not text:
        return text

    results = _analyzer.analyze(text=text, entities=_ENTITIES, language="en")
    if not results:
        return text

    anonymized = _anonymizer.anonymize(
        text=text,
        analyzer_results=results,
        operators=_OPERATORS,
    )
    return anonymized.text
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd apps/backend && pytest tests/unit/test_services/test_pii.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd apps/backend && git add \
  src/second_brain/services/__init__.py \
  src/second_brain/services/pii.py \
  tests/unit/test_services/__init__.py \
  tests/unit/test_services/test_pii.py
git commit -m "feat(pii): add PII redaction service using Presidio + spaCy"
```

---

### Task 3: PIIRedactionNode (Inbound + Outbound)

**Files:**
- Create: `apps/backend/src/second_brain/nodes/__init__.py`
- Create: `apps/backend/src/second_brain/nodes/pii_redaction.py`
- Create: `apps/backend/tests/unit/test_nodes/__init__.py`
- Create: `apps/backend/tests/unit/test_nodes/test_pii_redaction.py`

- [ ] **Step 1: Write the failing tests**

```python
# apps/backend/tests/unit/test_nodes/test_pii_redaction.py
import pytest
from langchain_core.messages import HumanMessage, AIMessage
from second_brain.nodes.pii_redaction import redact_inbound, redact_outbound
from tests.unit.conftest import make_state


def test_redact_inbound_replaces_pii_in_last_message():
    state = make_state(
        messages=[HumanMessage(content="Hi, I'm Alice Johnson at alice@test.com")]
    )
    result = redact_inbound(state)
    updated_content = result["messages"][-1].content
    assert "[NAME]" in updated_content
    assert "[EMAIL]" in updated_content
    assert "Alice Johnson" not in updated_content
    assert "alice@test.com" not in updated_content


def test_redact_inbound_preserves_earlier_messages():
    earlier = HumanMessage(content="What is Python?")
    current = HumanMessage(content="My name is Bob Smith.")
    state = make_state(messages=[earlier, current])
    result = redact_inbound(state)
    # The returned dict only contains the last message update
    # Earlier messages are preserved in the LangGraph checkpoint
    assert len(result["messages"]) == 1
    assert "[NAME]" in result["messages"][-1].content


def test_redact_inbound_no_pii_message_unchanged():
    state = make_state(messages=[HumanMessage(content="What is the capital of France?")])
    result = redact_inbound(state)
    # Content should not be mangled when there is no PII
    assert "capital of France" in result["messages"][-1].content


def test_redact_outbound_replaces_pii_in_final_answer():
    state = make_state(final_answer="You should contact Dr. Sarah Connor at s.connor@clinic.com.")
    result = redact_outbound(state)
    assert "[NAME]" in result["final_answer"]
    assert "[EMAIL]" in result["final_answer"]
    assert "Sarah Connor" not in result["final_answer"]
    assert "s.connor@clinic.com" not in result["final_answer"]


def test_redact_outbound_empty_answer_unchanged():
    state = make_state(final_answer="")
    result = redact_outbound(state)
    assert result["final_answer"] == ""
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd apps/backend && pytest tests/unit/test_nodes/test_pii_redaction.py -v
```

Expected: `ModuleNotFoundError` for `second_brain.nodes.pii_redaction`.

- [ ] **Step 3: Implement the PII redaction nodes**

```python
# apps/backend/src/second_brain/nodes/__init__.py
# (empty)
```

```python
# apps/backend/src/second_brain/nodes/pii_redaction.py
from langchain_core.messages import HumanMessage
from second_brain.graphs.state import SecondBrainState
from second_brain.services.pii import redact_pii


def redact_inbound(state: SecondBrainState) -> dict:
    """Graph node: redact PII from the last (current) user message.

    Returns a dict with only the redacted last message. LangGraph's add_messages
    reducer will merge this into the checkpoint, replacing the last message content
    without touching the rest of the message history.
    """
    last_message = state["messages"][-1]
    redacted_content = redact_pii(last_message.content)
    redacted_message = HumanMessage(
        content=redacted_content,
        id=last_message.id,  # preserve message id so add_messages replaces in-place
    )
    return {"messages": [redacted_message]}


def redact_outbound(state: SecondBrainState) -> dict:
    """Graph node: redact PII from the final_answer before it is persisted."""
    return {"final_answer": redact_pii(state["final_answer"])}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd apps/backend && pytest tests/unit/test_nodes/test_pii_redaction.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd apps/backend && git add \
  src/second_brain/nodes/__init__.py \
  src/second_brain/nodes/pii_redaction.py \
  tests/unit/test_nodes/__init__.py \
  tests/unit/test_nodes/test_pii_redaction.py
git commit -m "feat(nodes): add PIIRedactionNode for inbound and outbound PII scrubbing"
```

---

### Task 4: MemoryRetrievalNode Stub

**Files:**
- Create: `apps/backend/src/second_brain/nodes/memory_retrieval.py`

> This is a stub for Ticket 4. The full pgvector similarity search across `learned_facts` and `model_corrections` is implemented in Ticket 5. The stub wires the node into the graph so Ticket 5 can drop in the real implementation with no graph changes.

- [ ] **Step 1: Write a minimal test**

```python
# Add to apps/backend/tests/unit/test_nodes/test_pii_redaction.py
# (or create a separate file — add to the existing test_nodes module)

# apps/backend/tests/unit/test_nodes/test_memory_retrieval.py
import pytest
from second_brain.nodes.memory_retrieval import retrieve_memory
from tests.unit.conftest import make_state


@pytest.mark.asyncio
async def test_retrieve_memory_stub_returns_empty_list():
    state = make_state()
    result = await retrieve_memory(state)
    assert result == {"retrieved_memory": []}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd apps/backend && pytest tests/unit/test_nodes/test_memory_retrieval.py -v
```

Expected: `ModuleNotFoundError` for `second_brain.nodes.memory_retrieval`.

- [ ] **Step 3: Implement the stub**

```python
# apps/backend/src/second_brain/nodes/memory_retrieval.py
from second_brain.graphs.state import SecondBrainState


async def retrieve_memory(state: SecondBrainState) -> dict:
    """Stub: returns empty list. Full implementation in Ticket 5.

    Ticket 5 will implement cosine similarity search on `learned_facts`
    and `model_corrections` tables, populating `retrieved_memory` with
    relevant MemoryItem entries for the current query.
    """
    return {"retrieved_memory": []}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd apps/backend && pytest tests/unit/test_nodes/test_memory_retrieval.py -v
```

Expected: 1 test PASS.

- [ ] **Step 5: Commit**

```bash
cd apps/backend && git add \
  src/second_brain/nodes/memory_retrieval.py \
  tests/unit/test_nodes/test_memory_retrieval.py
git commit -m "feat(nodes): add MemoryRetrievalNode stub (full impl in Ticket 5)"
```

---

### Task 5: Orchestrator Node

**Files:**
- Create: `apps/backend/src/second_brain/nodes/orchestrator.py`
- Create: `apps/backend/tests/unit/test_nodes/test_orchestrator.py`

**Dependency:** `pip install langchain-anthropic` — and ensure `ANTHROPIC_API_KEY` is set in `.env`.

- [ ] **Step 1: Write the failing tests**

```python
# apps/backend/tests/unit/test_nodes/test_orchestrator.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.messages import HumanMessage
from second_brain.nodes.orchestrator import route_query
from tests.unit.conftest import make_state


def _mock_routing(decision: str):
    """Helper: create a mock RoutingOutput with the given routing_decision."""
    mock_result = MagicMock()
    mock_result.routing_decision = decision
    return mock_result


@pytest.mark.asyncio
async def test_routes_to_rag_for_personal_knowledge_query():
    state = make_state(
        messages=[HumanMessage(content="What are my notes on machine learning?")],
        retrieved_memory=[],
    )
    with patch("second_brain.nodes.orchestrator._structured_llm") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=_mock_routing("rag"))
        result = await route_query(state)
    assert result["routing_decision"] == "rag"


@pytest.mark.asyncio
async def test_routes_to_web_for_current_events():
    state = make_state(
        messages=[HumanMessage(content="What happened in the tech industry this week?")],
        retrieved_memory=[],
    )
    with patch("second_brain.nodes.orchestrator._structured_llm") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=_mock_routing("web"))
        result = await route_query(state)
    assert result["routing_decision"] == "web"


@pytest.mark.asyncio
async def test_routes_to_both_for_mixed_query():
    state = make_state(
        messages=[HumanMessage(content="Compare my notes on Python with the latest Python 4 news.")],
        retrieved_memory=[],
    )
    with patch("second_brain.nodes.orchestrator._structured_llm") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=_mock_routing("both"))
        result = await route_query(state)
    assert result["routing_decision"] == "both"


@pytest.mark.asyncio
async def test_routes_to_neither_for_conversational_query():
    state = make_state(
        messages=[HumanMessage(content="Thanks, that helps!")],
        retrieved_memory=[],
    )
    with patch("second_brain.nodes.orchestrator._structured_llm") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=_mock_routing("neither"))
        result = await route_query(state)
    assert result["routing_decision"] == "neither"


@pytest.mark.asyncio
async def test_includes_memory_context_in_prompt():
    """Verify that retrieved_memory facts are passed to the LLM."""
    state = make_state(
        messages=[HumanMessage(content="What do I know about Rust?")],
        retrieved_memory=[
            {"id": "1", "fact": "User prefers Rust for systems programming", "confidence": 0.9, "type": "learned_fact"}
        ],
    )
    captured_prompts = []

    async def capture_invoke(prompt):
        captured_prompts.append(prompt)
        return _mock_routing("rag")

    with patch("second_brain.nodes.orchestrator._structured_llm") as mock_llm:
        mock_llm.ainvoke = capture_invoke
        await route_query(state)

    assert len(captured_prompts) == 1
    assert "User prefers Rust for systems programming" in captured_prompts[0]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd apps/backend && pytest tests/unit/test_nodes/test_orchestrator.py -v
```

Expected: `ModuleNotFoundError` for `second_brain.nodes.orchestrator`.

- [ ] **Step 3: Implement the orchestrator**

```python
# apps/backend/src/second_brain/nodes/orchestrator.py
from typing import Literal
from pydantic import BaseModel
from langchain_anthropic import ChatAnthropic
from second_brain.graphs.state import SecondBrainState

_ROUTING_PROMPT = """\
You are a query router for a personal knowledge management system (Second Brain).

Given the user's query and any relevant memory context retrieved from long-term storage,
decide the best retrieval strategy:

  "rag"     — query asks about the user's personal notes, documents, or ingested knowledge
  "web"     — query requires current/real-time information from the internet
  "both"    — query benefits from both personal knowledge and web search
  "neither" — query is purely conversational and can be answered from context alone

User memory context (from long-term storage):
{memory_context}

User query: {query}

Choose the routing_decision that best serves the user."""


class _RoutingOutput(BaseModel):
    routing_decision: Literal["rag", "web", "both", "neither"]
    reasoning: str


_structured_llm = ChatAnthropic(model="claude-haiku-4-5").with_structured_output(_RoutingOutput)


async def route_query(state: SecondBrainState) -> dict:
    """Graph node: LLM-powered routing using claude-haiku-4-5.

    Reads messages[-1].content and retrieved_memory, outputs routing_decision.
    """
    query = state["messages"][-1].content
    memory = state.get("retrieved_memory", [])
    memory_context = (
        "\n".join(f"- {m['fact']}" for m in memory)
        if memory
        else "No memory context available."
    )
    prompt = _ROUTING_PROMPT.format(memory_context=memory_context, query=query)
    result: _RoutingOutput = await _structured_llm.ainvoke(prompt)
    return {"routing_decision": result.routing_decision}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd apps/backend && pytest tests/unit/test_nodes/test_orchestrator.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd apps/backend && git add \
  src/second_brain/nodes/orchestrator.py \
  tests/unit/test_nodes/test_orchestrator.py
git commit -m "feat(nodes): add Orchestrator node with claude-haiku-4-5 structured routing"
```

---

### Task 6: RAG Retrieval Node

**Files:**
- Create: `apps/backend/src/second_brain/nodes/rag_retrieval.py`
- Create: `apps/backend/tests/unit/test_nodes/test_rag_retrieval.py`

**Dependencies:** `pip install asyncpg pgvector httpx`

**Assumption:** `settings.app_postgres_url` (e.g. `postgresql://user:pass@localhost:5432/second_brain`) and `settings.ollama_base_url` (e.g. `http://localhost:11434`) exist in `second_brain/core/config.py` from Ticket 1.

- [ ] **Step 1: Write the failing tests**

```python
# apps/backend/tests/unit/test_nodes/test_rag_retrieval.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.messages import HumanMessage
from second_brain.nodes.rag_retrieval import retrieve_from_rag
from tests.unit.conftest import make_state


@pytest.mark.asyncio
async def test_returns_rag_results_list():
    state = make_state(messages=[HumanMessage(content="What is LangGraph?")])

    fake_rows = [
        {"content": "LangGraph is a library for building stateful agents.", "score": 0.92, "chunk_index": 0, "metadata": {"source": "langchain.md"}},
        {"content": "LangGraph uses StateGraph to manage state.", "score": 0.88, "chunk_index": 1, "metadata": {"source": "langchain.md"}},
    ]

    with patch("second_brain.nodes.rag_retrieval._embed_query", new_callable=AsyncMock) as mock_embed, \
         patch("second_brain.nodes.rag_retrieval._query_pgvector", new_callable=AsyncMock) as mock_db:
        mock_embed.return_value = [0.1] * 1024
        mock_db.return_value = fake_rows

        result = await retrieve_from_rag(state)

    assert "rag_results" in result
    assert len(result["rag_results"]) == 2
    assert result["rag_results"][0]["score"] == 0.92
    assert result["rag_results"][0]["chunk_index"] == 0
    assert result["rag_results"][0]["content"] == "LangGraph is a library for building stateful agents."


@pytest.mark.asyncio
async def test_returns_empty_list_when_no_results():
    state = make_state(messages=[HumanMessage(content="What is the meaning of life?")])

    with patch("second_brain.nodes.rag_retrieval._embed_query", new_callable=AsyncMock) as mock_embed, \
         patch("second_brain.nodes.rag_retrieval._query_pgvector", new_callable=AsyncMock) as mock_db:
        mock_embed.return_value = [0.0] * 1024
        mock_db.return_value = []

        result = await retrieve_from_rag(state)

    assert result["rag_results"] == []


@pytest.mark.asyncio
async def test_embeds_last_message_content():
    """Verify the query used for embedding is messages[-1].content."""
    state = make_state(messages=[HumanMessage(content="Tell me about Python.")])
    captured_queries = []

    async def capture_embed(query, base_url):
        captured_queries.append(query)
        return [0.1] * 1024

    with patch("second_brain.nodes.rag_retrieval._embed_query", side_effect=capture_embed), \
         patch("second_brain.nodes.rag_retrieval._query_pgvector", new_callable=AsyncMock) as mock_db:
        mock_db.return_value = []
        await retrieve_from_rag(state)

    assert captured_queries == ["Tell me about Python."]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd apps/backend && pytest tests/unit/test_nodes/test_rag_retrieval.py -v
```

Expected: `ModuleNotFoundError` for `second_brain.nodes.rag_retrieval`.

- [ ] **Step 3: Implement the RAG retrieval node**

```python
# apps/backend/src/second_brain/nodes/rag_retrieval.py
import asyncpg
import httpx
from pgvector.asyncpg import register_vector

from second_brain.core.config import settings
from second_brain.graphs.state import RagResult, SecondBrainState


async def _embed_query(query: str, base_url: str) -> list[float]:
    """Call Ollama to embed the query using qwen3-embedding:0.6b (dim=1024)."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{base_url}/api/embeddings",
            json={"model": "qwen3-embedding:0.6b", "prompt": query},
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()["embedding"]


async def _query_pgvector(
    embedding: list[float], postgres_url: str, top_k: int = 5
) -> list[dict]:
    """Run cosine similarity search against document_chunks in pgvector."""
    conn = await asyncpg.connect(postgres_url)
    try:
        await register_vector(conn)
        rows = await conn.fetch(
            """
            SELECT content,
                   1 - (embedding <=> $1) AS score,
                   chunk_index,
                   metadata
            FROM document_chunks
            ORDER BY embedding <=> $1
            LIMIT $2
            """,
            embedding,
            top_k,
        )
        return [
            {
                "content": row["content"],
                "score": float(row["score"]),
                "chunk_index": row["chunk_index"],
                "metadata": dict(row["metadata"]) if row["metadata"] else {},
            }
            for row in rows
        ]
    finally:
        await conn.close()


async def retrieve_from_rag(state: SecondBrainState) -> dict:
    """Graph node: embed query via Ollama, cosine similarity search on document_chunks, top-k=5.

    Returns rag_results populated with RagResult items sorted by descending score.
    """
    query = state["messages"][-1].content
    embedding = await _embed_query(query, settings.ollama_base_url)
    rows = await _query_pgvector(embedding, settings.app_postgres_url)

    rag_results: list[RagResult] = [
        {
            "content": row["content"],
            "score": row["score"],
            "chunk_index": row["chunk_index"],
            "metadata": row["metadata"],
        }
        for row in rows
    ]
    return {"rag_results": rag_results}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd apps/backend && pytest tests/unit/test_nodes/test_rag_retrieval.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd apps/backend && git add \
  src/second_brain/nodes/rag_retrieval.py \
  tests/unit/test_nodes/test_rag_retrieval.py
git commit -m "feat(nodes): add RAG retrieval node with pgvector cosine similarity"
```

---

### Task 7: Web Research Node

**Files:**
- Create: `apps/backend/src/second_brain/nodes/web_research.py`
- Create: `apps/backend/tests/unit/test_nodes/test_web_research.py`

**Dependencies:** `pip install tavily-python` — and ensure `TAVILY_API_KEY` is set in `.env` and exposed via `settings.tavily_api_key`.

- [ ] **Step 1: Write the failing tests**

```python
# apps/backend/tests/unit/test_nodes/test_web_research.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.messages import HumanMessage
from second_brain.nodes.web_research import search_web
from tests.unit.conftest import make_state


_FAKE_TAVILY_RESPONSE = {
    "results": [
        {"title": "Python 4 Released", "url": "https://python.org/news", "content": "Python 4 adds new features..."},
        {"title": "PEP 999", "url": "https://peps.python.org/pep-0999", "content": "PEP 999 proposes..."},
    ]
}


@pytest.mark.asyncio
async def test_returns_web_results():
    state = make_state(messages=[HumanMessage(content="What is new in Python 4?")])

    with patch("second_brain.nodes.web_research.TavilyClient") as MockClient, \
         patch("second_brain.nodes.web_research.asyncio.sleep", new_callable=AsyncMock):
        mock_instance = MagicMock()
        mock_instance.search.return_value = _FAKE_TAVILY_RESPONSE
        MockClient.return_value = mock_instance

        result = await search_web(state)

    assert "web_results" in result
    assert len(result["web_results"]) == 2
    assert result["web_results"][0]["title"] == "Python 4 Released"
    assert result["web_results"][0]["url"] == "https://python.org/news"
    assert "Python 4 adds" in result["web_results"][0]["content"]


@pytest.mark.asyncio
async def test_rate_limit_sleep_called():
    """Verify asyncio.sleep(1) is called for rate limiting — max 1 call/second."""
    state = make_state(messages=[HumanMessage(content="Latest AI news?")])

    with patch("second_brain.nodes.web_research.TavilyClient") as MockClient, \
         patch("second_brain.nodes.web_research.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        mock_instance = MagicMock()
        mock_instance.search.return_value = {"results": []}
        MockClient.return_value = mock_instance

        await search_web(state)

    mock_sleep.assert_called_once_with(1)


@pytest.mark.asyncio
async def test_returns_empty_list_when_no_results():
    state = make_state(messages=[HumanMessage(content="Something very obscure??")])

    with patch("second_brain.nodes.web_research.TavilyClient") as MockClient, \
         patch("second_brain.nodes.web_research.asyncio.sleep", new_callable=AsyncMock):
        mock_instance = MagicMock()
        mock_instance.search.return_value = {"results": []}
        MockClient.return_value = mock_instance

        result = await search_web(state)

    assert result["web_results"] == []


@pytest.mark.asyncio
async def test_searches_with_last_message_content():
    """Verify the query passed to Tavily is messages[-1].content."""
    state = make_state(messages=[HumanMessage(content="Rust 2025 edition features?")])
    captured_queries: list[str] = []

    with patch("second_brain.nodes.web_research.TavilyClient") as MockClient, \
         patch("second_brain.nodes.web_research.asyncio.sleep", new_callable=AsyncMock):
        mock_instance = MagicMock()

        def capture_search(query, max_results=3):
            captured_queries.append(query)
            return {"results": []}

        mock_instance.search.side_effect = capture_search
        MockClient.return_value = mock_instance

        await search_web(state)

    assert captured_queries == ["Rust 2025 edition features?"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd apps/backend && pytest tests/unit/test_nodes/test_web_research.py -v
```

Expected: `ModuleNotFoundError` for `second_brain.nodes.web_research`.

- [ ] **Step 3: Implement the web research node**

```python
# apps/backend/src/second_brain/nodes/web_research.py
import asyncio
from tavily import TavilyClient

from second_brain.core.config import settings
from second_brain.graphs.state import SecondBrainState, WebResult


async def search_web(state: SecondBrainState) -> dict:
    """Graph node: search the web via Tavily, max 3 results.

    Rate-limited to 1 call/second via asyncio.sleep(1).
    TavilyClient.search is synchronous; it runs in the default thread executor.
    """
    query = state["messages"][-1].content

    # Rate limit: max 1 Tavily call per second
    await asyncio.sleep(1)

    client = TavilyClient(api_key=settings.tavily_api_key)

    # Tavily SDK is synchronous — offload to executor to avoid blocking the event loop
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        lambda: client.search(query, max_results=3),
    )

    web_results: list[WebResult] = [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": r.get("content", ""),
        }
        for r in response.get("results", [])
    ]
    return {"web_results": web_results}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd apps/backend && pytest tests/unit/test_nodes/test_web_research.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd apps/backend && git add \
  src/second_brain/nodes/web_research.py \
  tests/unit/test_nodes/test_web_research.py
git commit -m "feat(nodes): add Web Research node with Tavily search, rate-limited to 1 rps"
```

---

### Task 8: Synthesis Node

**Files:**
- Create: `apps/backend/src/second_brain/nodes/synthesis.py`
- Create: `apps/backend/tests/unit/test_nodes/test_synthesis.py`

- [ ] **Step 1: Write the failing tests**

```python
# apps/backend/tests/unit/test_nodes/test_synthesis.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.messages import HumanMessage, AIMessage
from second_brain.nodes.synthesis import synthesize_answer
from tests.unit.conftest import make_state


def _mock_synthesis(answer: str, confidence: float):
    mock = MagicMock()
    mock.final_answer = answer
    mock.confidence = confidence
    return mock


@pytest.mark.asyncio
async def test_returns_final_answer_and_confidence():
    state = make_state(
        messages=[HumanMessage(content="What is LangGraph?")],
        rag_results=[{"content": "LangGraph is a graph-based agent framework.", "score": 0.9, "chunk_index": 0, "metadata": {}}],
        web_results=[],
        retrieved_memory=[],
        routing_decision="rag",
    )
    with patch("second_brain.nodes.synthesis._structured_llm") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=_mock_synthesis("LangGraph is a framework for agents.", 0.85))
        result = await synthesize_answer(state)

    assert result["final_answer"] == "LangGraph is a framework for agents."
    assert result["confidence"] == 0.85
    assert result["is_uncertain"] is False


@pytest.mark.asyncio
async def test_is_uncertain_true_when_confidence_below_07():
    state = make_state(
        messages=[HumanMessage(content="What is the best diet?")],
        rag_results=[],
        web_results=[],
        retrieved_memory=[],
        routing_decision="neither",
    )
    with patch("second_brain.nodes.synthesis._structured_llm") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=_mock_synthesis("It depends on the individual.", 0.65))
        result = await synthesize_answer(state)

    assert result["is_uncertain"] is True
    assert result["confidence"] == 0.65


@pytest.mark.asyncio
async def test_neither_routing_applies_confidence_floor_of_05():
    """AC: when routing_decision == 'neither', confidence is floored at 0.5."""
    state = make_state(
        messages=[HumanMessage(content="Hey there!")],
        rag_results=[],
        web_results=[],
        retrieved_memory=[],
        routing_decision="neither",
    )
    with patch("second_brain.nodes.synthesis._structured_llm") as mock_llm:
        # LLM returns very low confidence (e.g. 0.2) — should be raised to 0.5
        mock_llm.ainvoke = AsyncMock(return_value=_mock_synthesis("Hello! How can I help?", 0.2))
        result = await synthesize_answer(state)

    assert result["confidence"] == 0.5
    assert result["is_uncertain"] is True  # 0.5 < 0.7, still uncertain
    assert result["final_answer"] == "Hello! How can I help?"


@pytest.mark.asyncio
async def test_neither_routing_does_not_lower_confidence_above_floor():
    """If LLM returns confidence > 0.5 on 'neither' routing, keep the LLM value."""
    state = make_state(
        messages=[HumanMessage(content="What is 2 + 2?")],
        routing_decision="neither",
    )
    with patch("second_brain.nodes.synthesis._structured_llm") as mock_llm:
        mock_llm.ainvoke = AsyncMock(return_value=_mock_synthesis("4", 0.99))
        result = await synthesize_answer(state)

    assert result["confidence"] == 0.99


@pytest.mark.asyncio
async def test_trims_messages_to_last_10():
    """Verify only the last 10 messages are included in the synthesis prompt."""
    messages = [HumanMessage(content=f"Message {i}") for i in range(15)]
    state = make_state(
        messages=messages,
        routing_decision="neither",
    )
    captured_prompts: list[str] = []

    async def capture_invoke(prompt):
        captured_prompts.append(prompt)
        return _mock_synthesis("answer", 0.8)

    with patch("second_brain.nodes.synthesis._structured_llm") as mock_llm:
        mock_llm.ainvoke = capture_invoke
        await synthesize_answer(state)

    # "Message 0" through "Message 4" should NOT be in the prompt
    assert "Message 0" not in captured_prompts[0]
    assert "Message 5" in captured_prompts[0]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd apps/backend && pytest tests/unit/test_nodes/test_synthesis.py -v
```

Expected: `ModuleNotFoundError` for `second_brain.nodes.synthesis`.

- [ ] **Step 3: Implement the synthesis node**

```python
# apps/backend/src/second_brain/nodes/synthesis.py
from pydantic import BaseModel, Field
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage

from second_brain.graphs.state import SecondBrainState

_SYNTHESIS_PROMPT = """\
You are a knowledgeable Second Brain assistant. Synthesize a comprehensive, accurate answer
from the available context. Be clear about what you know and don't know.

--- Retrieved documents ---
{rag_context}

--- Web search results ---
{web_context}

--- Long-term memory ---
{memory_context}

--- Conversation history (last 10 turns) ---
{conversation_history}

--- Current question ---
{query}

Provide a helpful answer and rate your confidence from 0.0 (no idea) to 1.0 (certain).
Base confidence on the quality and relevance of the above context."""


class _SynthesisOutput(BaseModel):
    final_answer: str
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score 0.0–1.0")
    reasoning: str


_UNCERTAINTY_THRESHOLD = 0.7
_NEITHER_CONFIDENCE_FLOOR = 0.5

_structured_llm = ChatAnthropic(model="claude-sonnet-4-6").with_structured_output(_SynthesisOutput)


def _format_messages(messages: list[BaseMessage]) -> str:
    parts = []
    for m in messages:
        role = "Human" if isinstance(m, HumanMessage) else "Assistant"
        parts.append(f"{role}: {m.content}")
    return "\n".join(parts) if parts else "(no prior conversation)"


async def synthesize_answer(state: SecondBrainState) -> dict:
    """Graph node: synthesize final answer using claude-sonnet-4-6.

    Combines rag_results + web_results + retrieved_memory + last 10 messages.
    Applies confidence floor of 0.5 when routing_decision == 'neither'.
    Sets is_uncertain=True when confidence < 0.7.
    """
    query = state["messages"][-1].content
    rag_results = state.get("rag_results", [])
    web_results = state.get("web_results", [])
    memory = state.get("retrieved_memory", [])
    routing = state.get("routing_decision", "neither")

    # Use last 10 messages, excluding the current query (which is the last one)
    history_messages = state["messages"][-10:-1]

    rag_context = (
        "\n\n".join(f"[Score: {r['score']:.2f}]\n{r['content']}" for r in rag_results)
        if rag_results
        else "No document context retrieved."
    )
    web_context = (
        "\n\n".join(f"[{r['title']}]({r['url']})\n{r['content']}" for r in web_results)
        if web_results
        else "No web results retrieved."
    )
    memory_context = (
        "\n".join(f"- {m['fact']}" for m in memory)
        if memory
        else "No memory context."
    )
    conversation_history = _format_messages(history_messages)

    prompt = _SYNTHESIS_PROMPT.format(
        rag_context=rag_context,
        web_context=web_context,
        memory_context=memory_context,
        conversation_history=conversation_history,
        query=query,
    )

    output: _SynthesisOutput = await _structured_llm.ainvoke(prompt)

    confidence = output.confidence
    # Apply floor for conversational turns where no external context was retrieved
    if routing == "neither":
        confidence = max(confidence, _NEITHER_CONFIDENCE_FLOOR)

    return {
        "final_answer": output.final_answer,
        "confidence": confidence,
        "is_uncertain": confidence < _UNCERTAINTY_THRESHOLD,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd apps/backend && pytest tests/unit/test_nodes/test_synthesis.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd apps/backend && git add \
  src/second_brain/nodes/synthesis.py \
  tests/unit/test_nodes/test_synthesis.py
git commit -m "feat(nodes): add Synthesis node with claude-sonnet-4-6 and confidence floor for 'neither' routing"
```

---

### Task 9: Query Graph with LangGraph Checkpointing

**Files:**
- Create: `apps/backend/src/second_brain/graphs/query_graph.py`

**Dependencies:** `pip install langgraph langgraph-checkpoint-postgres psycopg psycopg-pool`

- [ ] **Step 1: Write a smoke test for graph construction**

```python
# apps/backend/tests/unit/test_query_graph_build.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_build_query_graph_returns_compiled_graph():
    """Graph construction should succeed with a mocked checkpointer."""
    with patch("second_brain.graphs.query_graph.AsyncConnectionPool"), \
         patch("second_brain.graphs.query_graph.AsyncPostgresSaver") as MockSaver:
        mock_saver_instance = MagicMock()
        mock_saver_instance.setup = AsyncMock()
        MockSaver.return_value = mock_saver_instance

        from second_brain.graphs.query_graph import build_query_graph
        graph = await build_query_graph("postgresql://fake:fake@localhost:5432/test")

    # Compiled graph must have an ainvoke method
    assert hasattr(graph, "ainvoke")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd apps/backend && pytest tests/unit/test_query_graph_build.py -v
```

Expected: `ModuleNotFoundError` for `second_brain.graphs.query_graph`.

- [ ] **Step 3: Implement the query graph**

```python
# apps/backend/src/second_brain/graphs/query_graph.py
from langgraph.graph import StateGraph, END
from langgraph.constants import Send
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

from second_brain.graphs.state import SecondBrainState
from second_brain.nodes.pii_redaction import redact_inbound, redact_outbound
from second_brain.nodes.memory_retrieval import retrieve_memory
from second_brain.nodes.orchestrator import route_query
from second_brain.nodes.rag_retrieval import retrieve_from_rag
from second_brain.nodes.web_research import search_web
from second_brain.nodes.synthesis import synthesize_answer


def _route_retrieval(state: SecondBrainState):
    """Conditional edge: fan-out based on orchestrator routing_decision.

    Returns:
      - list[Send] for "rag", "web", "both" — parallel or single branch
      - "synthesis" string for "neither" — routes directly, skipping retrieval
    """
    decision = state["routing_decision"]
    if decision == "both":
        return [Send("rag_retrieval", state), Send("web_research", state)]
    elif decision == "rag":
        return [Send("rag_retrieval", state)]
    elif decision == "web":
        return [Send("web_research", state)]
    else:  # "neither"
        return "synthesis"


async def build_query_graph(postgres_url: str):
    """Build and compile the SecondBrain query graph with PostgresSaver checkpointing.

    threadId = session_id. Each session maintains its own conversation checkpoint
    so messages accumulate across turns (via add_messages reducer on SecondBrainState).

    Call once at app startup; the returned compiled graph is thread-safe for concurrent use.
    """
    pool = AsyncConnectionPool(conninfo=postgres_url, open=False)
    await pool.open()

    checkpointer = AsyncPostgresSaver(pool)
    await checkpointer.setup()  # creates LangGraph checkpoint tables if absent

    workflow = StateGraph(SecondBrainState)

    # Register nodes
    workflow.add_node("redact_inbound", redact_inbound)
    workflow.add_node("retrieve_memory", retrieve_memory)
    workflow.add_node("orchestrator", route_query)
    workflow.add_node("rag_retrieval", retrieve_from_rag)
    workflow.add_node("web_research", search_web)
    workflow.add_node("synthesis", synthesize_answer)
    workflow.add_node("redact_outbound", redact_outbound)

    # Linear flow
    workflow.set_entry_point("redact_inbound")
    workflow.add_edge("redact_inbound", "retrieve_memory")
    workflow.add_edge("retrieve_memory", "orchestrator")

    # Fan-out: orchestrator → rag_retrieval and/or web_research (parallel via Send)
    # For "neither": routes directly to synthesis
    workflow.add_conditional_edges(
        "orchestrator",
        _route_retrieval,
        ["rag_retrieval", "web_research", "synthesis"],
    )

    # Both retrieval branches converge on synthesis
    workflow.add_edge("rag_retrieval", "synthesis")
    workflow.add_edge("web_research", "synthesis")

    # Final outbound PII scrub then done
    workflow.add_edge("synthesis", "redact_outbound")
    workflow.add_edge("redact_outbound", END)

    return workflow.compile(checkpointer=checkpointer)
```

- [ ] **Step 4: Run the smoke test to verify it passes**

```bash
cd apps/backend && pytest tests/unit/test_query_graph_build.py -v
```

Expected: 1 test PASS.

- [ ] **Step 5: Commit**

```bash
cd apps/backend && git add \
  src/second_brain/graphs/query_graph.py \
  tests/unit/test_query_graph_build.py
git commit -m "feat(graph): wire full query LangGraph with PostgresSaver checkpointing and fan-out via Send"
```

---

### Task 10: API Schemas and `/query` Router

**Files:**
- Modify: `apps/backend/src/second_brain/api/schemas.py`
- Create: `apps/backend/src/second_brain/api/routers/query.py`

**Dependencies:** `pip install uuid6` (provides `uuid7()`).

- [ ] **Step 1: Write the failing tests**

```python
# apps/backend/tests/unit/test_query_router.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from second_brain.api.schemas import QueryRequest, QueryResponse


def test_query_request_with_null_session_id():
    req = QueryRequest(message="Hello", sessionId=None)
    assert req.message == "Hello"
    assert req.sessionId is None


def test_query_request_with_session_id():
    req = QueryRequest(message="Hello", sessionId="01900000-0000-7000-8000-000000000001")
    assert req.sessionId == "01900000-0000-7000-8000-000000000001"


def test_query_response_shape():
    resp = QueryResponse(
        answer="The answer is 42.",
        sessionId="01900000-0000-7000-8000-000000000001",
        confidence=0.88,
        isUncertain=False,
        conflictDetected=False,
        conflictContext=[],
    )
    assert resp.answer == "The answer is 42."
    assert resp.isUncertain is False
    assert resp.conflictDetected is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd apps/backend && pytest tests/unit/test_query_router.py -v
```

Expected: `ImportError` — `QueryRequest`/`QueryResponse` not in schemas yet.

- [ ] **Step 3: Add schemas to `api/schemas.py`**

Open `apps/backend/src/second_brain/api/schemas.py` and append the following (keep all existing ingestion schemas):

```python
# --- append to apps/backend/src/second_brain/api/schemas.py ---

from typing import Optional
from pydantic import BaseModel


class QueryRequest(BaseModel):
    message: str
    sessionId: Optional[str] = None  # UUID7 or null for new session


class QueryResponse(BaseModel):
    answer: str
    sessionId: str        # UUID7 — use this in the next call to continue the session
    confidence: float     # 0.0–1.0
    isUncertain: bool     # True when confidence < 0.7; prompts user to optionally correct
    conflictDetected: bool  # True when a new fact conflicts with existing memory
    conflictContext: list[str]  # Descriptions of detected conflicts, if any
```

- [ ] **Step 4: Create the `/query` router**

```python
# apps/backend/src/second_brain/api/routers/query.py
from uuid6 import uuid7
from fastapi import APIRouter, HTTPException
from langchain_core.messages import HumanMessage

from second_brain.api.schemas import QueryRequest, QueryResponse
from second_brain.core.config import settings
from second_brain.graphs.query_graph import build_query_graph

router = APIRouter(prefix="/query", tags=["query"])

# Module-level compiled graph singleton — initialised once on first request
_graph = None


async def _get_graph():
    global _graph
    if _graph is None:
        _graph = await build_query_graph(settings.app_postgres_url)
    return _graph


@router.post("", response_model=QueryResponse)
async def query_endpoint(request: QueryRequest) -> QueryResponse:
    """Chat with the Second Brain.

    - sessionId=null → creates a new conversation thread (new UUID7 returned)
    - sessionId=<UUID7> → continues an existing thread (history loaded from checkpoint)

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
        raise HTTPException(status_code=500, detail=f"Query graph error: {exc}") from exc

    conflict_context: list[str] = result.get("conflict_context", [])

    return QueryResponse(
        answer=result["final_answer"],
        sessionId=session_id,
        confidence=result["confidence"],
        isUncertain=result["is_uncertain"],
        conflictDetected=bool(conflict_context),
        conflictContext=conflict_context,
    )
```

- [ ] **Step 5: Run schema tests to verify they pass**

```bash
cd apps/backend && pytest tests/unit/test_query_router.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 6: Commit**

```bash
cd apps/backend && git add \
  src/second_brain/api/schemas.py \
  src/second_brain/api/routers/query.py \
  tests/unit/test_query_router.py
git commit -m "feat(api): add QueryRequest/QueryResponse schemas and POST /query router"
```

---

### Task 11: Register Router in `main.py`

**Files:**
- Modify: `apps/backend/src/second_brain/main.py`

- [ ] **Step 1: Write a test that the `/query` route exists on the app**

```python
# apps/backend/tests/unit/test_app_routes.py
from fastapi.testclient import TestClient
from second_brain.main import app


def test_query_route_registered():
    """Verify /query is registered — a POST with no body returns 422, not 404."""
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post("/query", json={})
    # 422 = validation error (missing 'message' field) = route exists
    # 404 = route not registered
    assert response.status_code != 404
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd apps/backend && pytest tests/unit/test_app_routes.py::test_query_route_registered -v
```

Expected: FAIL — response is 404 because the router is not yet registered.

- [ ] **Step 3: Register the router in `main.py`**

Open `apps/backend/src/second_brain/main.py`. Find the block where other routers are included (look for `app.include_router(...)` calls). Add the following import and registration:

```python
# In apps/backend/src/second_brain/main.py
# Add this import alongside existing router imports:
from second_brain.api.routers.query import router as query_router

# Add this alongside existing include_router calls:
app.include_router(query_router)
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd apps/backend && pytest tests/unit/test_app_routes.py::test_query_route_registered -v
```

Expected: 1 test PASS (status code 422, not 404).

- [ ] **Step 5: Commit**

```bash
cd apps/backend && git add \
  src/second_brain/main.py \
  tests/unit/test_app_routes.py
git commit -m "feat(main): register /query router in FastAPI app"
```

---

### Task 12: Integration Tests — AC-5, AC-6, AC-10

**Files:**
- Create: `apps/backend/tests/integration/__init__.py`
- Create: `apps/backend/tests/integration/test_query_graph.py`

**Prerequisites:**
- Docker services running: `docker compose up -d app_postgres`
- `ANTHROPIC_API_KEY`, `TAVILY_API_KEY` in `.env` (LLM calls are mocked in these tests)
- `DATABASE_URL` env var pointing to the running test Postgres (same as `settings.app_postgres_url`)

These tests build the real graph with PostgresSaver against a running Postgres instance but mock all LLM + Tavily calls to avoid external API costs and ensure determinism.

- [ ] **Step 1: Write the failing integration tests**

```python
# apps/backend/tests/integration/test_query_graph.py
"""
Integration tests for the query graph.

Acceptance criteria covered:
  AC-5  — PII in user messages is redacted before reaching any LLM node
  AC-6  — PII in final_answer is redacted before being persisted
  AC-10 — sessionId=null creates a new thread; subsequent call with returned UUID7 continues it
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.messages import HumanMessage

from second_brain.core.config import settings
from second_brain.graphs.query_graph import build_query_graph


# ---------------------------------------------------------------------------
# Shared mock helpers
# ---------------------------------------------------------------------------

def _make_routing_mock(decision: str = "neither"):
    m = MagicMock()
    m.routing_decision = decision
    return m


def _make_synthesis_mock(answer: str, confidence: float = 0.85):
    m = MagicMock()
    m.final_answer = answer
    m.confidence = confidence
    return m


# ---------------------------------------------------------------------------
# AC-5: PII is redacted before any LLM node sees the message
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.integration
async def test_ac5_pii_redacted_before_llm_sees_message():
    """PII in the user message must be stripped before the orchestrator LLM is called."""
    graph = await build_query_graph(settings.app_postgres_url)

    session_id = "ac5-test-session-" + __import__("uuid").uuid4().hex[:8]
    pii_message = "My name is Eleanor Vance and my email is eleanor@secret.com"

    orchestrator_inputs: list[str] = []

    async def capture_orchestrator_invoke(prompt):
        orchestrator_inputs.append(prompt)
        return _make_routing_mock("neither")

    async def mock_synthesis_invoke(prompt):
        return _make_synthesis_mock("Got your message.")

    with patch("second_brain.nodes.orchestrator._structured_llm") as mock_orch, \
         patch("second_brain.nodes.synthesis._structured_llm") as mock_synth:
        mock_orch.ainvoke = capture_orchestrator_invoke
        mock_synth.ainvoke = mock_synthesis_invoke

        await graph.ainvoke(
            {
                "session_id": session_id,
                "messages": [HumanMessage(content=pii_message)],
                "rag_results": [], "web_results": [], "retrieved_memory": [],
                "routing_decision": "neither", "final_answer": "",
                "confidence": 0.0, "is_uncertain": False,
                "awaiting_correction": False, "awaiting_conflict_clarification": False,
                "conflict_context": [], "fact_updates": [], "correction_updates": [],
            },
            config={"configurable": {"thread_id": session_id}},
        )

    assert len(orchestrator_inputs) == 1
    # The real PII must not appear in what the orchestrator LLM received
    assert "Eleanor Vance" not in orchestrator_inputs[0]
    assert "eleanor@secret.com" not in orchestrator_inputs[0]
    assert "[NAME]" in orchestrator_inputs[0] or "[EMAIL]" in orchestrator_inputs[0]


# ---------------------------------------------------------------------------
# AC-6: PII in final_answer is redacted before being persisted
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.integration
async def test_ac6_pii_redacted_in_final_answer():
    """PII that appears in the synthesized final_answer must be scrubbed before the graph ends."""
    graph = await build_query_graph(settings.app_postgres_url)

    session_id = "ac6-test-session-" + __import__("uuid").uuid4().hex[:8]

    # LLM synthesis returns an answer that contains PII
    pii_in_answer = "Based on the context, Dr. Marcus Holt at m.holt@hospital.org is your contact."

    with patch("second_brain.nodes.orchestrator._structured_llm") as mock_orch, \
         patch("second_brain.nodes.synthesis._structured_llm") as mock_synth:
        mock_orch.ainvoke = AsyncMock(return_value=_make_routing_mock("neither"))
        mock_synth.ainvoke = AsyncMock(return_value=_make_synthesis_mock(pii_in_answer, 0.8))

        result = await graph.ainvoke(
            {
                "session_id": session_id,
                "messages": [HumanMessage(content="Who should I contact?")],
                "rag_results": [], "web_results": [], "retrieved_memory": [],
                "routing_decision": "neither", "final_answer": "",
                "confidence": 0.0, "is_uncertain": False,
                "awaiting_correction": False, "awaiting_conflict_clarification": False,
                "conflict_context": [], "fact_updates": [], "correction_updates": [],
            },
            config={"configurable": {"thread_id": session_id}},
        )

    # Raw PII must be absent from the persisted final_answer
    assert "Marcus Holt" not in result["final_answer"]
    assert "m.holt@hospital.org" not in result["final_answer"]
    assert "[NAME]" in result["final_answer"] or "[EMAIL]" in result["final_answer"]


# ---------------------------------------------------------------------------
# AC-10: sessionId=null creates new thread; UUID7 continues that thread
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.integration
async def test_ac10_null_session_id_creates_new_thread_uuid7_continues():
    """
    First call: sessionId=null → new thread created, UUID7 returned.
    Second call: same UUID7 → graph loads checkpoint, message history has both turns.
    """
    from uuid6 import uuid7
    from second_brain.api.schemas import QueryRequest, QueryResponse
    from second_brain.api.routers.query import query_endpoint

    call_count = [0]

    async def mock_orch(prompt):
        return _make_routing_mock("neither")

    async def mock_synth(prompt):
        call_count[0] += 1
        if call_count[0] == 1:
            return _make_synthesis_mock("Turn 1 answer: I see you.")
        else:
            # On turn 2, synthesis should have access to the prior turn in messages
            return _make_synthesis_mock("Turn 2 answer: Continuing our chat.")

    with patch("second_brain.nodes.orchestrator._structured_llm") as mock_orch_llm, \
         patch("second_brain.nodes.synthesis._structured_llm") as mock_synth_llm, \
         patch("second_brain.api.routers.query._graph", None):
        mock_orch_llm.ainvoke = mock_orch
        mock_synth_llm.ainvoke = mock_synth

        # First call — no sessionId
        response1: QueryResponse = await query_endpoint(
            QueryRequest(message="Hello, start a new session.", sessionId=None)
        )
        assert response1.sessionId is not None
        returned_session_id = response1.sessionId

        # Second call — use returned UUID7 to continue the thread
        response2: QueryResponse = await query_endpoint(
            QueryRequest(message="Continue the conversation.", sessionId=returned_session_id)
        )

    # Both calls must use the same session_id (thread continues)
    assert response2.sessionId == returned_session_id
    assert "Turn 2 answer" in response2.answer
    # Both LLM calls were made (one per turn)
    assert call_count[0] == 2
```

- [ ] **Step 2: Run integration tests to verify they fail**

```bash
cd apps/backend && pytest tests/integration/test_query_graph.py -v -m integration
```

Expected: tests fail (graph not wired correctly, or modules not importable). Fix any import errors before proceeding.

- [ ] **Step 3: Run the full unit + integration test suite**

```bash
cd apps/backend && pytest tests/ -v --tb=short
```

Expected: all unit tests PASS; integration tests that require a running Postgres may be skipped or fail if Postgres is not up. Bring up Postgres first if needed:

```bash
docker compose up -d app_postgres
cd apps/backend && pytest tests/ -v --tb=short
```

Expected: all tests PASS.

- [ ] **Step 4: Run all unit tests one final time to confirm nothing regressed**

```bash
cd apps/backend && pytest tests/unit/ -v
```

Expected: all unit tests PASS.

- [ ] **Step 5: Commit**

```bash
cd apps/backend && git add \
  tests/integration/__init__.py \
  tests/integration/test_query_graph.py
git commit -m "test(integration): add AC-5, AC-6, AC-10 integration tests for query graph"
```

---

## Done Checklist

Ticket 4 is complete when all of the following are true:

- [ ] `POST /query` with `sessionId=null` returns a UUID7 `sessionId` and a grounded answer
- [ ] Calling `POST /query` again with the returned UUID7 continues the same conversation thread
- [ ] PII (names, emails, phones, etc.) in inbound messages is replaced with `[NAME]`, `[EMAIL]`, `[PHONE]`, etc. **before** any LLM node receives the message (AC-5)
- [ ] PII in `final_answer` is redacted **before** it is returned and persisted to the LangGraph checkpoint (AC-6)
- [ ] Confidence < 0.7 sets `isUncertain: true` in the response
- [ ] `routing_decision == "neither"` applies a confidence floor of 0.5 to the synthesis output
- [ ] All unit tests pass: `pytest tests/unit/ -v`
- [ ] All integration tests pass against a running Postgres: `pytest tests/integration/ -v -m integration`
