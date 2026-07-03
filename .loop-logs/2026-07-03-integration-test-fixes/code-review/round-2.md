# Code Review — Round 2

**Timestamp:** 2026-07-03T07:20:00Z
**Loop iteration:** 2 of ≤5

## Raw findings

### Reviewer A — enhanced-review

Verified live (ran `just lint`/`type-check`/`test-unit` and the full integration
suite against the real Docker stack — 20/20 pass). Round-2 fixes (retrieval
threshold bug fix + regression test, fixture swap) are correct, complete, and
introduce nothing new.

MINOR: `test_memory_system.py`'s new fact/query pair ("favorite sport is
cycling" / "what is the user's favorite sport") shares the literal bigram
"favorite sport" — the code comment claiming pure semantic (non-lexical)
retrieval slightly overstates it. Not a bug; recommend softening the comment
if re-tuned later.

MINOR: coverage asymmetry — `memory_retrieval.py`'s bind-param fix got a
dedicated unit regression test, but the identical-bug-class fix in
`memory_persistence.py:_conflict_check` (commit 9ca722d) has no equivalent
unit-level regression test — only the integration suite would catch a revert.

Re-confirmed still present (not new, not yet fixed, same as round 1):
`event.listens_for` style nit; stale "no live Postgres/Anthropic" docstring in
`test_query_graph.py`; plan/spec docs don't mention the 3 follow-on fixes
(memory_agent mock, retrieval-threshold fix, fixture swap).

No blocking or important issues.

### Reviewer B — ponytail-review

MINOR: `test_memory_retrieval.py`'s new
`test_threshold_binds_precomputed_max_distance_not_raw_threshold` duplicates
~35 lines of mock-pool scaffolding already in `test_threshold_applied_to_sql_queries`
and doesn't reuse the file's existing `_make_mock_pool` helper — third
near-identical copy of the same plumbing.

`_mock_memory_agent_output()` dedup in `test_query_graph.py`: clean, a genuine
simplification, not new over-engineering. `max_distance` fix in both
`memory_persistence.py`/`memory_retrieval.py`: minimal, correct.

### Reviewer C — simplify

Confirmed `max_distance = 1 - settings.memory_retrieval_threshold` is still
duplicated across `_search_facts`/`_search_corrections` in `memory_retrieval.py`
— **verdict: leave as-is**. Hoisting to a module constant would break the new
test's `patch(settings.memory_retrieval_threshold, ...)` (constant would be
baked in before the patch applies); a wrapper function is a wash at 2 call
sites (rule-of-three not met).

MINOR: same test-mock-scaffolding duplication as Reviewer B.
MINOR: same `event.listens_for` vs `event.listen` idiom nit as round 1.

No blocking or important issues; no efficiency concerns.

## Consolidated issues

| ID | Severity | Summary | Evidence (file:line) |
| --- | --- | --- | --- |
| R2-1 | minor | New unit test duplicates mock-pool scaffolding instead of reusing `_make_mock_pool` helper | `apps/backend/tests/unit/test_nodes/test_memory_retrieval.py:178-227` |
| R2-2 | minor | New fixture's fact/query share literal "favorite sport" bigram; comment overstates pure-semantic nature | `apps/backend/tests/integration/test_memory_system.py:220-235` |
| R2-3 | minor | `_conflict_check` (memory_persistence.py) lacks a unit-level regression test for the same bug class that `memory_retrieval.py` now has | `apps/backend/src/second_brain/nodes/memory_persistence.py:30-41` |
| R2-4 (carried from R1-3) | minor | `event.listens_for(...)(lambda...)` — idiomatic form is `event.listen(...)` | `apps/backend/tests/integration/test_memory_system.py:39-41` |
| R2-5 (carried from R1-4) | minor | Stale module docstring ("no live Postgres or Anthropic API required") | `apps/backend/tests/integration/test_query_graph.py:1-12` |
| R2-6 (carried from R1-5) | minor | Plan/spec docs don't mention 3 follow-on fixes (memory_agent mock, retrieval-threshold fix, fixture swap) | `docs/superpowers/plans/2026-07-03-integration-test-fixes.md`, `docs/superpowers/specs/2026-07-03-integration-test-fixes-design.md` |

## Disposition

- Actionable (blocking + important) — to fix this iteration: none
- Deferred (minor — NOT handled yet): R2-1, R2-2, R2-3, R2-4, R2-5, R2-6

**Actionable count: 0 → exit review loop, proceed to Stage 4.**
