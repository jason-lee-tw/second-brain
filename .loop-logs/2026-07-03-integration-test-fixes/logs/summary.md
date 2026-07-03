# Loop Summary

**Plan:** docs/superpowers/plans/2026-07-03-integration-test-fixes.md
**Spec:** docs/superpowers/specs/2026-07-03-integration-test-fixes-design.md
**Branch:** fix/000-integration-test
**Date:** 2026-07-03

## Tasks

| Task | Status | Attempts | Delivered |
| --- | --- | --- | --- |
| task-1-session-scoped-event-loop | completed | 1 | Session-scoped asyncio event loop for real-DB integration tests (RC2) |
| task-2-pgvector-codec-fixture | completed | 1 | pgvector codec registration on raw-SQL test fixture (RC3) |
| task-3-conflict-check-threshold | completed | 1 | Fixed untyped-bind-param SQL bug in conflict-check threshold (RC1) |
| task-4-stale-fk-test-fix | completed | 1 | Flipped stale FK tests to match shipped migration 002 (RC4) |

**Completed:** 4/4
**Failed:** 0/4

## Verification

**Rounds:** 5 (cumulative across all verify invocations)

- Initial verify (round 1) found a latent bug exposed by the task-1 event-loop
  fix: `test_ac5`/`test_ac6` in `test_query_graph.py` now reached the real
  (unmocked) `memory_agent_node` LLM client, causing `anthropic.AuthenticationError`.
  Fixed by mocking `memory_agent._llm`, matching the existing `test_ac10` pattern.
- Post-review-fix verify found a second latent issue: fixing the review-flagged
  retrieval-threshold bug in `memory_retrieval.py` (see below) correctly started
  enforcing `memory_retrieval_threshold=0.5`, which exposed that
  `test_full_memory_loop_persist_then_retrieve`'s fixture fact/query pair only
  measured 0.4847 real cosine similarity against the live embedding model —
  just under threshold. It "passed" before only because the threshold check
  was broken. Fixed by swapping in a fact/query pair empirically verified at
  0.7330 similarity.
- Final verify: `just test-integration` 20/20 passing, twice in a row.
  `just format`/`lint`/`type-check`/`test-unit` (210 tests) all clean.

## Review

**Loop iterations:** 2 of ≤5
**Actionable issues found:** 2 (round 1 only; round 2 found zero)
**Actionable issues fixed:** 2
  - blocking: same untyped-bind-parameter SQL bug (RC1's exact pattern) was
    still live, unfixed, in `memory_retrieval.py`'s `_search_facts`/
    `_search_corrections` — a real production correctness bug silently
    disabling the retrieval-threshold filter on every query. Fixed with the
    same `max_distance`-precomputed-in-Python pattern, plus a new unit
    regression test.
  - important: a 3-line `MagicMock` block was duplicated at 3 call sites in
    `test_query_graph.py` instead of following the file's existing
    `_mock_routing()`/`_mock_synthesis()` helper convention. Extracted
    `_mock_memory_agent_output()`.

**Minor issues deferred (NOT handled yet):**
- `event.listens_for(engine, "connect")(lambda...)` in `test_memory_system.py`
  — idiomatic form is `event.listen(...)`. Style only.
- Stale module docstring in `test_query_graph.py` claiming "no live Postgres
  or Anthropic API required" — no longer accurate for `test_ac5`/`test_ac6`.
- Plan/spec docs (`docs/superpowers/plans/...`, `docs/superpowers/specs/...`)
  don't mention 3 follow-on fixes discovered during verification/review
  (memory_agent mock, retrieval-threshold fix, fixture swap).
- New unit test `test_threshold_binds_precomputed_max_distance_not_raw_threshold`
  duplicates mock-pool scaffolding instead of reusing the file's
  `_make_mock_pool` helper.
- New test fixture's fact/query pair shares a literal "favorite sport" bigram
  — comment slightly overstates how purely semantic the retrieval test is.
- `_conflict_check` (`memory_persistence.py`) lacks a unit-level regression
  test for the same bug class that `memory_retrieval.py` now has (only the
  integration suite would catch a revert there).

## Commits (linear, 9 total on this branch since the plan/spec landed)

```
6fe1580 fix(test): use fact/query pair that clears similarity threshold
ce8ff09 refactor(test): dedupe memory-agent mock via helper
5b81b0d fix(memory): bind precomputed max-distance in retrieval threshold SQL
df52c8e fix(test): mock memory-agent LLM in PII redaction integration tests
36823ec fix(test): assert no chat_history FK on learned_facts/corrections
9ca722d fix(memory): bind precomputed max-distance in conflict-check SQL
f5e9c85 fix(test): register pgvector codec on raw-SQL test fixture
4162545 fix(test): share one event loop across real-DB integration tests
```
