# Code Review — Round 2

**Timestamp:** 2026-07-01
**Loop iteration:** 2 of ≤5
**Diff reviewed:** `435619e..HEAD` (the 3 fixes merged from round 1)

## Raw findings

### Reviewer A — enhanced-review

Verified sound: `score_or_nan()` correctly eliminates all 6 duplicated blocks, preserves kwargs exactly, adds real stderr logging; `mock_metric` fixture is a faithful unique extraction; lint/format/tests all clean (79 passed).

New issue [important]: the docs-sync commit (02c4984) only reconciled the design spec/plan against the Tier-3 live-verification bugs (async clients, `top_p`) — it did NOT re-sync against the `score_or_nan()` extraction that landed earlier in this same round. Design doc lines 109-136 and plan doc lines ~419-457/725-786 still show the old inline try/except `_score_all()` block, contradicting the same commit's own Verification section which narrates the bare-except bug as already fixed.

### Reviewer B — ponytail (over-engineering focus)

`apps/eval/tests/unit/test_ragas_client.py:82-89`: yagni — `type("MockMetric", (), {})()` + `type("Score", (), {"value": 0.75})()` hand-rolls a fake metric/score pair in the same PR that just extracted `mock_metric` into conftest.py to kill this exact duplication. Use `mock_metric(0.75)` instead.

Everything else lean — no other findings.

### Reviewer C — simplify

Confirmed both A and B's findings independently via direct grep/read:
1. Test reinvents the mock it was supposed to reuse (`test_ragas_client.py:82-89`) — confirmed only this one test can use the fixture; the sibling exception test at 91-101 genuinely needs a named class for the stderr assertion and can't use `mock_metric`.
2. Docs still show pre-fix `_score_all` (design doc 109-171, plan doc 420-458/730-785) — confirmed via direct grep, `score_or_nan` absent from both docs' code blocks and Task 1's Interfaces list.

Lower-confidence/deferred: 4 near-identical append blocks in `run_eval.py`'s `_score_all` could collapse further (stylistic); `type(metric).__name__` reflection coupling is a design nit; `safe_mean` doesn't surface partial-failure counts (flagged as "arguably out of round-2's scope" by the reviewer itself — this is a pre-existing, explicitly-approved design decision from the original plan's Decision 5, not a regression); duplicate `MagicMock`+`side_effect` blocks in test files are pre-existing, confirmed unrelated to this round.

## Consolidated issues

| ID | Severity | Summary | Evidence (file:line) |
|----|----------|---------|----------------------|
| 1 | important | Docs-sync commit missed the `score_or_nan()` extraction — design spec and plan still show the old inline try/except `_score_all()`, contradicting the same commit's own narrative that the bare-except bug is fixed | `docs/superpowers/specs/2026-07-01-eval-ragas-collections-migration-design.md:109-171`; `docs/superpowers/plans/2026-07-01-eval-ragas-collections-migration.md:420-458,730-785` |
| 2 | important | New test hand-rolls a duplicate mock metric/score pair instead of using the `mock_metric` fixture just extracted in this same round, reintroducing the exact duplication pattern round 1 fixed | `apps/eval/tests/unit/test_ragas_client.py:82-89` |

Deferred (minor, not acted on this iteration): further collapsing `run_eval.py`'s 4 append blocks into a table-driven loop; `type(metric).__name__` reflection coupling in `score_or_nan`; `safe_mean` not surfacing partial-failure counts (pre-existing, deliberate per original Decision 5 — worth a follow-up ticket, not a regression); duplicate `MagicMock`+`side_effect` blocks in `test_baseline.py`/`test_run_eval.py` (pre-existing, unrelated to this round).

## Disposition

- Actionable (blocking + important) — to fix this iteration: 1, 2
- Deferred (minor — NOT handled yet): the 4 items listed above
