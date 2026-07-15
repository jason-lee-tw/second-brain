# Spec: Fix max_tokens truncation causing POST /query 500

Source: docs/superpowers/specs/2026-07-13-synthesis-max-tokens-truncation-fix.md
Primary-Topic: synthesis-max-tokens-truncation-fix
Secondary-Topics: node-base-class-refactor

## Key Concepts

- Spec dated 2026-07-13, status Approved, explicitly related to bug `docs/bugs/004-synthesis-max-tokens-truncation.md`.
- Root cause: `POST /query` returns HTTP 500 when the synthesis LLM completion is truncated by `ChatAnthropic`'s default `max_tokens=1024` before the required `reasoning` field of `_SynthesisOutput` is written.
- `PydanticToolsParser` raises an uncaught `pydantic.ValidationError` on the truncated output, which propagates through LangGraph into FastAPI as an unhandled 500.
- `MemoryAgentNode` has the identical defect shape (`MemoryAgentOutput` has required fields, no `max_tokens` override, no error handling around `.ainvoke`) — not yet triggered in production because it uses Haiku with shorter expected outputs, but is fixed in the same pass since it shares the same root cause and the same shared code path as `SynthesisNode`.
- Change 1: `synthesis.py` — construct `ClaudeAgent(CLAUDE_MODEL_NAME.SONNET, temperature=None, max_tokens=4096)`.
- Change 2: `memory_agent.py` — construct `ClaudeAgent(CLAUDE_MODEL_NAME.HAIKU, max_tokens=4096)`.
- Change 3: `base_agent_node.py` — add a new protected async helper method on `BaseAgentNode`: `_ainvoke_structured(structured_llm, prompt)`. It calls `structured_llm.ainvoke(prompt)`; on `pydantic.ValidationError` it retries exactly once; a second `ValidationError` propagates unchanged (no silent swallow, no fallback/degraded answer).
- Change 4: both `synthesis.py` and `memory_agent.py` are updated to route their existing single `.ainvoke(prompt)` call through the new `self._ainvoke_structured(...)` helper instead of calling `.ainvoke` directly.
- `max_tokens` is set per-node at construction time (in `synthesis.py` and `memory_agent.py`), not changed in `ClaudeAgent`'s own class default — this deliberately leaves other `ClaudeAgent` call sites unaffected, e.g. the ingestion header node which is capped at `max_tokens=150`.
- The retry in `_ainvoke_structured` catches `pydantic.ValidationError` specifically (the exact exception observed in the bug), not a broad `except Exception` — this follows the project's no-broad-except rule from CLAUDE.md.
- Acceptance Criteria (7 total):
  - AC-1: `POST /query` with the repro prompt from the bug doc returns HTTP 200, not 500.
  - AC-2: `SynthesisNode`'s and `MemoryAgentNode`'s underlying `ChatAnthropic` instances have `max_tokens == 4096`.
  - AC-3: `_ainvoke_structured` — first-call success returns that result without making a second call.
  - AC-4: `_ainvoke_structured` — first call raises `ValidationError`, second call succeeds → returns the second result.
  - AC-5: `_ainvoke_structured` — both calls raise `ValidationError` → the `ValidationError` propagates (no silent swallow).
  - AC-6: Other `ClaudeAgent` call sites (e.g. ingestion header generation's `max_tokens=150`) remain unchanged.
  - AC-7: `just format`, `just lint`, `just type-check`, and `just test-unit` all pass with no errors.
- Scope: exactly four files — `base_agent_node.py`, `synthesis.py`, `memory_agent.py`, plus their corresponding test files. Explicitly no schema changes, no new dependencies, no API contract changes.
- Out of scope: retrying more than once, or falling back to a degraded answer after two failures; any other `ClaudeAgent`-based node such as ingestion header generation or the orchestrator; raising `ChatAnthropic`'s own library default `max_tokens` globally.
