# Spec: Fix max_tokens truncation causing POST /query 500

**Date:** 2026-07-13  
**Status:** Approved  
**Related bug:** `docs/bugs/004-synthesis-max-tokens-truncation.md`

---

## Problem

`POST /query` returns 500 when the synthesis LLM completion is truncated by
`ChatAnthropic`'s default `max_tokens=1024` before the required `reasoning` field of
`_SynthesisOutput` is written. `PydanticToolsParser` raises an uncaught
`pydantic.ValidationError` that propagates through LangGraph into FastAPI as a 500.

`MemoryAgentNode` has the identical defect shape (`MemoryAgentOutput` required fields, no
`max_tokens` override, no error handling around `.ainvoke`) — not yet triggered in
practice (Haiku + shorter expected outputs), but fixed in the same pass since it's the
same root cause and the same shared code path.

## Change

1. **`synthesis.py`** — `ClaudeAgent(CLAUDE_MODEL_NAME.SONNET, temperature=None,
   max_tokens=4096)`.
2. **`memory_agent.py`** — `ClaudeAgent(CLAUDE_MODEL_NAME.HAIKU, max_tokens=4096)`.
3. **`base_agent_node.py`** — new protected async helper on `BaseAgentNode`:
   `_ainvoke_structured(structured_llm, prompt)`. Calls
   `structured_llm.ainvoke(prompt)`; on `pydantic.ValidationError`, retries once. A
   second `ValidationError` propagates unchanged.
4. **`synthesis.py`** and **`memory_agent.py`** — route their existing single
   `.ainvoke(prompt)` call through `self._ainvoke_structured(...)` instead of calling
   `.ainvoke` directly.

`max_tokens` is set per-node at construction time, not changed in `ClaudeAgent`'s own
default — other `ClaudeAgent` call sites (e.g. the ingestion header node capped at
`max_tokens=150`) are unaffected.

Retry catches `pydantic.ValidationError` specifically (the exact exception observed),
not a broad `except Exception` — per the project's no-broad-except rule.

## Acceptance Criteria

| #    | Criterion                                                                                                                          |
| ---- | ----------------------------------------------------------------------------------------------------------------------------------- |
| AC-1 | `POST /query` with the repro prompt from `docs/bugs/004-...md` returns HTTP 200, not 500                                          |
| AC-2 | `SynthesisNode`'s and `MemoryAgentNode`'s underlying `ChatAnthropic` instances have `max_tokens == 4096`                           |
| AC-3 | `_ainvoke_structured`: first-call success returns that result without a second call                                              |
| AC-4 | `_ainvoke_structured`: first call raises `ValidationError`, second call succeeds → returns the second result                     |
| AC-5 | `_ainvoke_structured`: both calls raise `ValidationError` → the `ValidationError` propagates (no silent swallow)                   |
| AC-6 | Other `ClaudeAgent` call sites (e.g. ingestion header generation's `max_tokens=150`) are unchanged                                 |
| AC-7 | `just format`, `just lint`, `just type-check`, and `just test-unit` all pass with no errors                                        |

## Scope

Four files: `base_agent_node.py`, `synthesis.py`, `memory_agent.py`, plus their test
files. No schema changes, no new dependencies, no API contract changes.

## Out of Scope

- Retrying more than once, or falling back to a degraded answer after two failures
- Any other `ClaudeAgent`-based node (e.g. ingestion header generation, orchestrator)
- Raising `ChatAnthropic`'s own library default `max_tokens` globally
