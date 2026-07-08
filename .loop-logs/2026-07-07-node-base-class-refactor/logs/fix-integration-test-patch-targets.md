# Fix: stale LLM patch targets in query_graph integration test

## Bug

A prior refactor moved these node modules' cached LLM singletons from
module-level names to instance attributes on their singleton node instances:

- `second_brain.nodes.orchestrator._structured_llm` -> `second_brain.nodes.orchestrator.route_query._structured_llm`
- `second_brain.nodes.synthesis._structured_llm` -> `second_brain.nodes.synthesis.synthesize_answer._structured_llm`
- `second_brain.nodes.memory_agent._llm` -> `second_brain.nodes.memory_agent.memory_agent_node._llm`

All unit test files were updated accordingly, but
`apps/backend/tests/integration/test_query_graph.py` was missed — it still had
10 stale `patch(...)` calls pointing at the old module-level names, causing
`test_ac5_pii_redacted_before_llm_sees_message`,
`test_ac6_pii_redacted_in_final_answer`,
`test_ac10_null_session_id_creates_new_thread_uuid_continues` (and any other
tests reaching the same `with` blocks) to fail with `AttributeError`.

## Fix

Update all 10 patch targets to include the singleton node instance attribute
segment (`.route_query`, `.synthesize_answer`, `.memory_agent_node`), matching
the pattern already used in the unit tests. Ran `ruff format` afterward to
re-wrap any lines exceeding the 88-char limit.

## Attempt 1

- Applied the fix via a Python script replacing the three stale dotted
  strings across all 11 occurrences (task brief said "10" but listed 11 line
  numbers; all 11 listed occurrences were fixed).
- `just lint` -> passed after `just format` re-wrapped the 3 multi-clause
  `with (...)` blocks whose lines exceeded 88 chars once the longer dotted
  path was substituted.
- `just type-check` -> 0 errors, 0 warnings (9 pre-existing informational
  notes in unrelated files, not touched by this change).
- Ran `uv run --package second-brain pytest apps/backend/tests/integration/test_query_graph.py -v`.
  First run: `test_ac5_pii_redacted_before_llm_sees_message` and
  `test_ac6_pii_redacted_in_final_answer` failed with
  `httpx.ConnectError: All connection attempts failed` while calling
  `embed_text` -> Ollama was not running in this environment (unrelated to
  the patch-target fix; `test_ac10` already passed).
  Started Ollama with `just up-ollama` (Postgres containers were already up),
  confirmed `curl localhost:11434/api/tags` responds, reran the same pytest
  command: all 3 tests passed
  (`3 passed, 1 warning in 2.17s`).
- Result: PASS on attempt 1.

## Outcome

Committed in worktree as:
`fix: update stale LLM patch targets in query_graph integration test`
