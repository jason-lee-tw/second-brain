# Task 11 Log: Convert ingestion_agent.py to IngestionAgentNode

## Task Context

### Plan Section

### Task 11: Convert `ingestion_agent.py` to `IngestionAgentNode`, remove `shutdown()`, drop dead config

**Files:**
- Modify: `apps/backend/src/second_brain/nodes/ingestion_agent.py`
- Modify: `apps/backend/src/second_brain/config.py`
- Modify: `apps/backend/src/second_brain/main.py`
- Modify: `apps/backend/tests/unit/test_nodes/test_ingestion_agent.py`
- Modify: `apps/backend/tests/integration/test_ingestion_graph.py`

**Interfaces:**
- Consumes: `CLAUDE_MODEL_NAME`, `ClaudeAgent` (Task 1).
- Produces: `ingestion_agent_node` (instance of `IngestionAgentNode`, `async def __call__`), with a `_model` instance attribute (`ClaudeAgent(HAIKU).get_model()`, a plain `ChatAnthropic`, no structured output). `_generate_contextual_header` and `_process_one_chunk` and `_do_ingest` become instance methods (they call `self._model`/`self._generate_contextual_header`/`self._process_one_chunk`/`self._do_ingest` transitively); `_sync_check_duplicate` and `_sync_write_results` stay module-level (no `self` dependency).

This task has one piece of genuine behavior change — header generation moves off the raw `anthropic.AsyncAnthropic` SDK client onto `ClaudeAgent`/`ChatAnthropic` — so that specific test is written test-first (red, then green). The rest is a structural move verified by the existing suite.

Steps 1-10, 12 followed exactly as written in the plan file
(docs/superpowers/plans/2026-07-07-node-base-class-refactor.md, Task 11 section).
Step 11 (integration test execution against live Postgres via `just up-all` /
`just test-integration`) is explicitly SKIPPED per orchestrator instruction — running
Docker Compose from 10 concurrent worktrees would conflict on ports. That verification
is deferred to a separate later full-repo verification task (Task 12) on the merged
branch. The integration test file's patch targets ARE still edited in Step 7 (source
edit, not a test run) — just not executed here.

## Acceptance Criteria
(none listed separately in plan; success = Step 10's `just lint && just type-check &&
just test-unit` all exit 0, plus the new TDD test passing red-then-green per Steps 1-4.)

## Attempt 1

### Implementation Plan
Followed plan Steps 1-10, 12 verbatim, with Step 11 explicitly skipped per orchestrator
deviation instruction (no live Postgres in this worktree — deferred to Task 12
full-repo verification on the merged branch).

### Files Changed
- `apps/backend/src/second_brain/nodes/ingestion_agent.py` — full rewrite per plan
  Step 3: `IngestionAgentNode(BaseAgentNode[IngestionState, IngestionAgentOutput])`,
  `__init__` builds `ClaudeAgent(CLAUDE_MODEL_NAME.HAIKU)` and caches
  `self._model = self._agent.get_model()`. `_generate_contextual_header`,
  `_process_one_chunk`, `_do_ingest` became instance methods; `_sync_check_duplicate`
  and `_sync_write_results` stayed module-level (no `self` dependency, per spec
  decision 12). Removed `anthropic`/`TextBlock` imports, the raw `_anthropic` client,
  and `shutdown()`. `__call__` marked `@override`. Module-level singleton
  `ingestion_agent_node = IngestionAgentNode()` retained (spec decision 5/11 — same
  public name, now an instance rather than a bare function; calling it as
  `ingestion_agent_node(state)` still works since `__call__` makes instances callable).
- `apps/backend/src/second_brain/config.py` — removed dead `ingestion_model` field
  (Step 9).
- `apps/backend/src/second_brain/main.py` — removed `from second_brain.nodes import
  ingestion_agent` and the `await ingestion_agent.shutdown()` try/except block from
  the lifespan handler (Step 8).
- `apps/backend/tests/unit/test_nodes/test_ingestion_agent.py` — Step 1: replaced
  `test_generate_contextual_header_raises_when_no_text_block` with
  `test_generate_contextual_header_strips_whitespace` (see Key Decisions for a
  mocking-strategy deviation from the plan's literal snippet). Step 5: retargeted the
  3 remaining `_generate_contextual_header` patches to
  `ingestion_agent.ingestion_agent_node._generate_contextual_header`.
- `apps/backend/tests/integration/test_ingestion_graph.py` — Step 7: retargeted the 3
  `f"{node}._generate_contextual_header"` patches to
  `f"{node}.ingestion_agent_node._generate_contextual_header"`. Edited only (not
  executed — see Key Decisions on Step 11 deferral).
- `apps/backend/tests/unit/test_main.py` — NOT in the plan's Task 11 file list, but
  required: it patched `second_brain.nodes.ingestion_agent._anthropic` and asserted
  `mock_anthropic.close.assert_called_once()` in two tests
  (`test_lifespan_closes_anthropic_client`,
  `test_lifespan_closes_both_clients_even_if_one_raises`). Both attributes are gone
  once `shutdown()`/`_anthropic` are deleted (spec decision 8). Deleted the now-
  obsolete `test_lifespan_closes_anthropic_client` test entirely, and rewrote
  `test_lifespan_closes_both_clients_even_if_one_raises` to patch
  `second_brain.main.shutdown_query_graph` as the second teardown target instead of
  the removed anthropic client, preserving the original intent (one teardown raising
  must not block the other from running).

### New Tests
- `test_generate_contextual_header_strips_whitespace` (unit) — red before Step 3
  (`AttributeError: 'function' object has no attribute '_model'`), green after.

### Key Decisions
1. **Step 11 (integration test execution) deferred per orchestrator instruction.**
   Not run in this worktree — 10 concurrent worktrees would conflict on Docker Compose
   ports. Verification deferred to the separate Task 12 full-repo verification pass on
   the merged branch. The integration test file's patch-target edits (Step 7) were
   still made as a source change.
2. **Plan's literal Step 1 test snippet doesn't work as written — fixed the mocking
   strategy, not the production code.** The plan says to use
   `patch.object(ingestion_agent_node._model, "ainvoke", AsyncMock(...))`. Running
   this raises `ValueError: "ChatAnthropic" object has no field "ainvoke"` —
   `ChatAnthropic` is a pydantic `BaseModel` and pydantic rejects `setattr` for names
   that aren't declared fields (confirmed via full traceback: pydantic's
   `_setattr_handler` → `raise ValueError(f'"{cls.__name__}" object has no field
   "{name}"')`, since `model_config` doesn't set `extra="allow"`). This is a pre-
   existing constraint of `ChatAnthropic`/pydantic, unrelated to my implementation.
   Confirmed the codebase already solves the identical problem elsewhere
   (`test_orchestrator.py`, `test_memory_agent.py`, `test_synthesis.py`) by patching
   the whole module-level singleton attribute (e.g. `patch("...orchestrator.
   _structured_llm")`) rather than `patch.object`-ing a method onto the live
   pydantic instance. Applied the same established pattern here: `patch(
   "second_brain.nodes.ingestion_agent.ingestion_agent_node._model") as mock_model;
   mock_model.ainvoke = AsyncMock(...)`. Test intent (verify whitespace stripping)
   is unchanged; only the mocking mechanics differ from the plan's literal snippet.
3. **`test_main.py` fix (see Files Changed) was a necessary addition outside the
   plan's stated file list.** Root cause: the plan's Task 11 "Files" section omitted
   this file, but it directly depended on `ingestion_agent._anthropic`/`shutdown()`
   which Step 8/decision 8 removes. Without this fix `just test-unit` fails with
   `AttributeError: <module ...ingestion_agent...> does not have the attribute
   '_anthropic'`. Fixed by deleting the obsolete anthropic-specific test and
   retargeting the "one raises, other still runs" test at `shutdown_query_graph`
   (a teardown target that already existed in `main.py`, untouched by this task).
4. **Commit message shortened from the plan's literal Step 12 text.** The plan's
   exact commit subject line (`refactor: convert ingestion_agent node to
   BaseAgentNode on ClaudeAgent, drop raw Anthropic client and dead shutdown/config`)
   is 122 characters; this repo's `.hooks/commit-msg` hook enforces a 72-character
   subject limit and rejected it (`❌ Commit subject is too long (122 chars). Keep it
   under 72.`). Shortened the subject to `refactor: convert ingestion_agent to
   IngestionAgentNode on ClaudeAgent` (70 chars) and moved the dropped-client/config
   detail into the commit body via a second `-m`.
5. Docstring on the new test needed shortening 3 times to fit ruff's 88-char line
   limit (`E501`) — the plan's literal docstring text
   (`"""_generate_contextual_header strips leading/trailing whitespace from the LLM
   response."""`) is 93 chars including 2-space indent; final version reads
   `"""_generate_contextual_header strips leading/trailing whitespace from
   response."""`.

### Lint Output
`just lint` → All checks passed! (after trimming the one long docstring, see Key
Decision 5).

### Test Output
`just test-unit` → 209 passed, 2 warnings (pre-existing deprecation warnings,
unrelated to this change).
`just type-check` → 0 errors, 0 warnings, 9 notes (all 9 notes are pre-existing
`reportUnknownArgumentType` informational notes on other already-merged files —
`memory_persistence.py`, `memory_retrieval.py` — plus one on the line in
`ingestion_agent.py` where `str(response.content)` narrows an `Any`-typed union;
none are new failures).
`uv run ruff format --check .` → 109 files already formatted.

### Commit
`7e7826cd0d419fb202c3d5fe23cf3e68f4a7ad22` — "refactor: convert ingestion_agent to
IngestionAgentNode on ClaudeAgent"

### Outcome
PASS — attempt 1.
