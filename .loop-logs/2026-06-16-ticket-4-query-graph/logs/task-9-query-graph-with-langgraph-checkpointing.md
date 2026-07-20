# Task 9 Log: Query Graph with LangGraph Checkpointing

## Task Context

### Plan Section
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

Note: this is the graph wiring task — no direct numbered AC in the plan; ACs 5/6/10 (orchestrator routing, retrieval fan-out, `/query` endpoint) depend on this graph existing.

---

## Attempt 1 — 2026-07-20T05:13:55Z

### Implementation Plan
- Write failing smoke test at `apps/backend/tests/unit/test_graphs/test_query_graph.py` (nested under `test_graphs/`, matching `test_ingestion_graph.py`), patching `AsyncConnectionPool`/`AsyncPostgresSaver` in `second_brain.graphs.query_graph`
- Run `just test-unit` to confirm it fails because `second_brain.graphs.query_graph` does not exist yet
- Implement `build_query_graph(postgres_url)` in `apps/backend/src/second_brain/graphs/query_graph.py` per plan Step 3, wiring all 7 existing nodes with a `Send`-based conditional fan-out on `routing_decision`
- Run `just lint` then `just test-unit`, fix any issues found

### Files Changed
- created `apps/backend/src/second_brain/graphs/query_graph.py` — `build_query_graph()` compiling the full query LangGraph with `AsyncPostgresSaver` checkpointing and `Send`-based fan-out
- created `apps/backend/tests/unit/test_graphs/test_query_graph.py` — smoke test asserting the compiled graph exposes `ainvoke`

### New Tests
- `test_build_query_graph_returns_compiled_graph`

### Key Decisions
- Confirmed installed package versions (`langgraph 0.6.11`, `langgraph-checkpoint-postgres 3.0.5`, `psycopg-pool 3.3.1`) expose the exact import paths the plan specifies (`langgraph.checkpoint.postgres.aio.AsyncPostgresSaver`, `psycopg_pool.AsyncConnectionPool`) — no path adjustment needed there.
- Imported `Send` from `langgraph.types` instead of the plan's `langgraph.constants` — the installed `langgraph==0.6.11` emits a `LangGraphDeprecatedSinceV10` warning for the `constants` path in favor of `langgraph.types`; switched to avoid shipping a deprecated import on day one.
- The plan's literal smoke test only patches `AsyncPostgresSaver.setup` as an `AsyncMock`, leaving `AsyncConnectionPool`'s `.open()` as a bare `MagicMock`. Running it against the real implementation raised `TypeError: object MagicMock can't be used in 'await' expression` on `await pool.open()`. Fixed by also configuring the mocked pool instance's `.open` as an `AsyncMock` — a correction to the test's mock setup, not a change to `build_query_graph`'s implementation.
- `build_query_graph` takes the DSN as-is (no `+psycopg2` stripping inside the function) — stripping is deferred to the Task 10 caller per instructions, keeping this a pure "DSN in, compiled graph out" function.

### Lint Output
PASS

### Test Output
PASS (121 passed, 1 new)

### Commit
`84efd28`

### Outcome: success
