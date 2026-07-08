# Code Review — Round 2

**Timestamp:** 2026-07-08
**Loop iteration:** 2 of ≤5

## Raw findings

### Reviewer A — enhanced-review

Round-1 fixes verified clean, no new issues from them. New finding:
- `apps/backend/src/second_brain/nodes/ingestion_agent.py:83` (CONFIRMED, correctness) — migrating `_generate_contextual_header` off raw `anthropic.AsyncAnthropic` onto `ClaudeAgent` silently dropped the `max_tokens=150` cap that existed on `main`. `ClaudeAgent`'s kwargs dict has no `max_tokens` control, so `ChatAnthropic` falls back to its library default of 1024 (~7x). 10-way concurrent chunk processing amplifies this. Zero mention in spec/plan (unlike temperature/model-pinning, which are explicit documented trade-offs).

### Reviewer B — ponytail

Re-flags round-1 F9 (deferred, unfixed): `base_node.py:6-7` — `BaseNode.__init__` is a no-op override adding nothing over ABC/object defaults.

### Reviewer C — simplify

1. `memory_agent.py:38` — naming inconsistency: `self._llm` vs siblings' `self._structured_llm` for the identical construct; already leaked into divergent test patch target names.
2. Re-flags the same `base_node.py:6-7` no-op `__init__`.
3. `web_research.py:20` — `TavilyClient` constructed fresh per `__call__`, not reused. Carried over verbatim from pre-refactor code, not introduced by this diff.
Ruled out a false lead re: `SecretStr` handling in claude_agent.py (confirmed correct).

## Consolidated issues

| ID  | Severity  | Summary | Evidence (file:line) | Reviewers | Verdict |
| --- | --------- | ------- | --------------------- | --------- | ------- |
| F11 | important | `ClaudeAgent` migration silently dropped `max_tokens=150` cap on per-chunk header generation; now defaults to 1024 (~7x), cost/prompt-adherence impact, zero spec mention | `ingestion_agent.py:83`, root cause `claude_agent.py:17-38` | A | actionable |
| F9 (re-flagged) | promoted to important | `BaseNode.__init__` no-op override | `base_node.py:6-7` | B, C (rounds 1+2, 3rd flag) | actionable — zero risk, 2-line deletion, stops recurring review noise |
| F12 | minor | `memory_agent.py` uses `self._llm` vs siblings' `self._structured_llm` | `memory_agent.py:38` | C | deferred — cosmetic; fix would re-touch 2 already-stabilized test files for no functional gain |
| F13 | not-actionable | `TavilyClient` constructed fresh per-call | `web_research.py:20` | C | not-actionable — verified byte-for-byte carried over from `main`, out of scope for a behavior-preserving refactor |

## Disposition

- Actionable (blocking + important) — to fix this iteration: F11, F9
- Deferred (minor — NOT handled yet): F12 — `memory_agent.py` naming inconsistency (`_llm` vs `_structured_llm`)
- Not actionable: F13
