# Verification Fix Round 1 — memory-agent LLM mock missing in AC-5/AC-6

## Status: SUCCESS

Worktree: `.worktrees/verification-fix-round-1` (branch `worktree/verification-fix-round-1`)
Commit: `fdb35c4` — "fix(test): mock memory-agent LLM in PII redaction integration tests"

## Root cause investigation

Read `apps/backend/tests/integration/test_query_graph.py` in full. Confirmed
`test_ac10_null_session_id_creates_new_thread_uuid_continues` (~line 209) already
patches the memory agent's LLM:

```python
patch("second_brain.nodes.memory_agent._llm") as mock_memory_agent_llm,
...
mock_memory_agent_output = MagicMock()
mock_memory_agent_output.fact_updates = []
mock_memory_agent_output.correction_updates = []
mock_memory_agent_llm.ainvoke = AsyncMock(return_value=mock_memory_agent_output)
```

Its docstring explains why: "memory_retrieval_node runs on an unconditional graph
edge regardless of routing_decision ... the memory_agent's LLM is likewise stubbed
since memory_agent_node always runs after synthesis."

Confirmed the target symbol by reading `apps/backend/src/second_brain/nodes/memory_agent.py`:
- Line 15: `_llm = ChatAnthropic(model="claude-haiku-4-5").with_structured_output(...)`
- Line 93: `output: MemoryAgentOutput = await _llm.ainvoke(prompt)`
- Lines 99/114: reads `output.fact_updates` and `output.correction_updates`

`test_ac5_pii_redacted_before_llm_sees_message` and
`test_ac6_pii_redacted_in_final_answer` patched only
`second_brain.nodes.orchestrator._structured_llm` and
`second_brain.nodes.synthesis._structured_llm` — never `memory_agent._llm`. Once the
earlier fix in this pipeline made these tests session-scoped (so they no longer
crash on event-loop teardown before reaching memory_agent_node), the graph ran to
completion and `memory_agent_node` invoked the real (unmocked) `ChatAnthropic`
client, which hit the live Anthropic API with a fake test key and raised
`anthropic.AuthenticationError: 401 invalid x-api-key` ("During task with name
'memory_agent'").

## Fix

Added the same mock pattern `test_ac10` already uses, to both `test_ac5` and
`test_ac6`:

1. Build a `MagicMock` memory-agent output with `fact_updates = []` and
   `correction_updates = []`.
2. Add `patch("second_brain.nodes.memory_agent._llm") as mock_memory_agent_llm` to
   each test's `with (...)` block.
3. Set `mock_memory_agent_llm.ainvoke = AsyncMock(return_value=mock_memory_agent_output)`.

No changes to the tests' actual assertions — the PII-redaction behavior under test
(raw email/name must not reach the orchestrator prompt / must not leak into
final_answer) is untouched and still genuinely exercised.

Diff (post pre-commit auto-format):

```diff
diff --git a/apps/backend/tests/integration/test_query_graph.py b/apps/backend/tests/integration/test_query_graph.py
index 08d327d..ba05e12 100644
--- a/apps/backend/tests/integration/test_query_graph.py
+++ b/apps/backend/tests/integration/test_query_graph.py
@@ -90,6 +90,10 @@ async def test_ac5_pii_redacted_before_llm_sees_message():
         captured_prompts.append(prompt)
         return _mock_routing("neither")
 
+    mock_memory_agent_output = MagicMock()
+    mock_memory_agent_output.fact_updates = []
+    mock_memory_agent_output.correction_updates = []
+
     with (
         patch(
             "second_brain.graphs.query_graph.AsyncConnectionPool",
@@ -101,11 +105,13 @@ async def test_ac5_pii_redacted_before_llm_sees_message():
         ),
         patch("second_brain.nodes.orchestrator._structured_llm") as mock_orch_llm,
         patch("second_brain.nodes.synthesis._structured_llm") as mock_synth_llm,
+        patch("second_brain.nodes.memory_agent._llm") as mock_memory_agent_llm,
     ):
         mock_orch_llm.ainvoke = AsyncMock(side_effect=capturing_orch_ainvoke)
         mock_synth_llm.ainvoke = AsyncMock(
             return_value=_mock_synthesis("Here is your answer.")
         )
+        mock_memory_agent_llm.ainvoke = AsyncMock(return_value=mock_memory_agent_output)
 
         graph, _pool = await build_query_graph(
             "postgresql://fake:test@localhost:5432/test"
@@ -161,6 +167,10 @@ async def test_ac6_pii_redacted_in_final_answer():
         "john.doe@secretcorp.com for further assistance."
     )
 
+    mock_memory_agent_output = MagicMock()
+    mock_memory_agent_output.fact_updates = []
+    mock_memory_agent_output.correction_updates = []
+
     with (
         patch(
             "second_brain.graphs.query_graph.AsyncConnectionPool",
@@ -172,9 +182,11 @@ async def test_ac6_pii_redacted_in_final_answer():
         ),
         patch("second_brain.nodes.orchestrator._structured_llm") as mock_orch_llm,
         patch("second_brain.nodes.synthesis._structured_llm") as mock_synth_llm,
+        patch("second_brain.nodes.memory_agent._llm") as mock_memory_agent_llm,
     ):
         mock_orch_llm.ainvoke = AsyncMock(return_value=_mock_routing("neither"))
         mock_synth_llm.ainvoke = AsyncMock(return_value=_mock_synthesis(pii_answer))
+        mock_memory_agent_llm.ainvoke = AsyncMock(return_value=mock_memory_agent_output)
 
         graph, _pool = await build_query_graph(
             "postgresql://fake:test@localhost:5432/test"
```

No changes made to any of the 4 already-fixed files (event-loop markers, pgvector
codec fixture, conflict-check SQL, FK test assertions) — only this test file was
touched.

## Before / after test output

### Red (before fix)

```
FAILED apps/backend/tests/integration/test_query_graph.py::test_ac5_pii_redacted_before_llm_sees_message
FAILED apps/backend/tests/integration/test_query_graph.py::test_ac6_pii_redacted_in_final_answer
======================== 2 failed, 1 warning in 38.01s =========================
```
Failure: `anthropic.AuthenticationError: Error code: 401 - {'type': 'error', 'error':
{'type': 'authentication_error', 'message': 'invalid x-api-key'}}` — "During task
with name 'memory_agent'".

### Green (after fix)

```
apps/backend/tests/integration/test_query_graph.py::test_ac5_pii_redacted_before_llm_sees_message PASSED [ 50%]
apps/backend/tests/integration/test_query_graph.py::test_ac6_pii_redacted_in_final_answer PASSED [100%]
========================= 2 passed, 1 warning in 1.27s =========================
```

### Full integration suite

```
apps/backend/tests/integration/test_ingestion_graph.py ...               [ 15%]
apps/backend/tests/integration/test_memory_system.py ....                [ 35%]
apps/backend/tests/integration/test_migration.py ..........              [ 85%]
apps/backend/tests/integration/test_query_graph.py ...                   [100%]
======================== 20 passed, 1 warning in 3.17s =========================
```
Confirmed **20/20 pass**.

### Lint / unit tests

- `just lint` → "All checks passed!"
- `just test-unit` → 209 passed, 2 warnings (unrelated deprecation warnings only).

## Verification

- Re-ran `just test-integration` after the pre-commit hook's auto-format pass —
  still 20/20 passing.
- `git status --porcelain` clean after commit; `git diff` scoped to exactly the
  one test file, only adding the memory-agent mock (no logic changes to the
  assertions or to any of the 4 previously-fixed files).

## Commit

```
fdb35c4 fix(test): mock memory-agent LLM in PII redaction integration tests
```
