# Loop Summary

**Plan:** docs/superpowers/plans/2026-07-01-eval-ragas-collections-migration.md
**Spec:** docs/superpowers/specs/2026-07-01-eval-ragas-collections-migration-design.md
**Branch:** feat/006-evaluation-harness
**Date:** 2026-07-01

## Orchestration note

This plan's 5 tasks form a strict dependency chain (Task 2/3 import Task 1's `ragas_client.py`; Task 3 also reuses a test helper Task 2 adds to `test_smoke.py`; Task 4 requires Tasks 2+3 merged; Task 5 verifies everything). The pipeline's default "spawn all tasks in parallel worktrees" was adapted to **sequential** worktrees (each branched off the updated tip after the prior task's squash-merge) to respect this — true parallelism would have had Task 2/3's worktrees branch off a commit that didn't yet contain `ragas_client.py`. Task 5 (pure live verification, no file changes) was folded into Stage 2's Verify step rather than run as a separate redundant worktree agent.

## Tasks

| Task | Status | Attempts | Delivered |
|------|--------|----------|-----------|
| task-1-ragas-client-helper | completed | 1 | Shared `ragas_client.py` helper |
| task-2-migrate-baseline | completed | 1 | Migrate `baseline.py` to `ragas.metrics.collections` |
| task-3-migrate-run-eval | completed | 1 | Migrate `run_eval.py` to `ragas.metrics.collections` |
| task-4-remove-unused-deps | completed | 1 | Remove now-unused dependencies |
| task-5-verify | completed (folded into Stage 2) | n/a | Lint, type-check, and live end-to-end verification |

**Completed:** 5/5
**Failed:** 0/5

## Verification

**Rounds:** 5 (see `.loop-logs/2026-07-01-eval-ragas-collections-migration/tasks/verification-state.json` for full detail)

- Round 1 (post-Stage-1 live verify): found the migration itself introduced a regression — `ragas_client.build_llm()`/`build_embeddings()` used SYNC clients (`anthropic.Anthropic`, `openai.OpenAI`), but `ragas.metrics.collections` metrics require async (`agenerate()`/`aembed_text()`). Every metric silently computed as `null` (broad `except Exception` swallowed the `TypeError`). Fixed: switched to `AsyncAnthropic`/`AsyncOpenAI` (commit `63c7ed9`).
- Round 2 (fresh re-verify): found a second regression — `claude-sonnet-4-6` rejects Anthropic API calls with both `temperature` and `top_p` set (ragas's `InstructorModelArgs` defaults both); every judge-LLM call failed with HTTP 400, again silently swallowed to `null`. Fixed: pop `top_p` from `llm.model_args` after `llm_factory()` returns it (commit `435619e`), confirmed against real ragas source and one live API call before dispatching the fix.
- Round 3 (fresh re-verify): both fixes confirmed working — real, non-null scores for all metrics (`eval-baseline`: faithfulness=0.0/answer_relevancy=0.0, genuine RAGAS zeros not swallowed exceptions; `eval-rag`: context_recall=0.9/context_precision=0.85/faithfulness=0.6944/answer_relevancy=0.8033). One AC flagged FAIL by the verifier turned out to be the orchestrator's own over-strict wording ("no N/A placeholders" in `eval-report`'s table) rather than the actual plan/spec text — baseline structurally never computes `context_recall`/`context_precision` (no retrieval to score), which is explicitly tested behavior from Task 2, not a defect. Corrected without spending a 4th costly live round on a non-bug.
- Round 4 (review-loop iteration 2 re-verify, after 3 code-review fixes merged): live re-run confirmed no regression from the `score_or_nan` refactor; incidentally validated the new stderr logging against 4 REAL `IncompleteOutputException` failures during `eval-rag` (judge LLM truncation) — logged correctly, isolated per-sample, aggregate still computed.
- Round 5 (review-loop iteration 3 re-verify, after 2 more doc/test-only fixes): confirmed via `git diff --stat` that neither fix touched runtime code; skipped a redundant live API round in favor of a fresh `test-eval && lint && type-check` (all green), which fully covers the actual changed surface.

## Review

**Loop iterations:** 3 of ≤5
**Actionable issues found:** 6 (4 in round 1, 2 in round 2)
**Actionable issues fixed:** 6
**Minor issues deferred (NOT handled yet):**
- `ANTHROPIC_API_KEY` redeclared in `baseline.py` instead of importing from `ragas_client`
- `_OLLAMA_URL`/`_EMBEDDING_MODEL` in `run_eval.py` duplicate `ragas_client` constants as literals (pre-existing, deliberate — different consumers)
- `build_llm()`/`build_embeddings()` missing `->` return-type annotations
- `openai` imported directly but only a transitive dependency (approved trade-off, undocumented with a comment)
- Redundant assertion in `test_ragas_client.py` (`"top_p" not in result.model_args` implied by the exact-dict-equality check 3 lines later)
- `top_p`-pop workaround has no comment tying correctness to `JUDGE_MODEL`'s specific value
- Design doc uses module-qualified `ragas_client.foo()` in code samples vs real unqualified imports (pre-existing, out of scope)
- `safe_mean` docstring drift (missing "empty list" clause) in design doc (pre-existing, out of scope)
- Design doc's `run_eval.py` `_score_all()` sample duplicates logic already shown elsewhere (doc verbosity only)
- `score_or_nan`'s rationale stated 3x across docstring/prose/decisions-log (doc verbosity only)
- One plan-doc sentence restates what the diff shows a few lines below (doc verbosity only)
- `safe_mean()` doesn't surface a partial-failure count when some (not all) samples fail — the aggregate mean looks like a normal score even if e.g. 3/10 judge calls timed out. This is a pre-existing, explicitly-approved design decision (original plan Decision 5: catch/NaN/continue, matching old `evaluate(raise_exceptions=False)` behavior), not a regression — flagged by a reviewer as worth a follow-up ticket.

## Out of scope, not committed

- `apps/eval/dataset/qa_pairs.json` — pre-existing untracked file (predates this session), README says it should eventually be committed as the curated dataset, but it's not a deliverable of this plan.
- `apps/eval/results/baseline.json`, `results/rag.json`, `results/2026-07-01-eval-report.md` — live-verification run outputs; `apps/eval/README.md` documents `results/` as gitignored (though no `.gitignore` file actually exists there — a pre-existing repo-hygiene gap, not introduced or fixed by this branch).
