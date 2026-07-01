# Code Review — Round 1

**Timestamp:** 2026-07-01
**Loop iteration:** 1 of ≤5
**Diff reviewed:** `19e241e..HEAD` (branch `feat/006-evaluation-harness`)

## Raw findings

### Reviewer A — enhanced-review

Scope confirmed: 6 commits touching `apps/eval/ragas_client.py` (new), `baseline.py`, `run_eval.py`, `pyproject.toml`/`uv.lock`, and tests. 77/77 tests pass, ruff clean, no leftover deprecated-API references.

- Finding 1 [Important]: Silent error-swallowing — 6 `except Exception: append(nan)` blocks with zero logging (`baseline.py:63-64,70-71`, `run_eval.py:118-119,127-128,136-137,143-144`). Old `evaluate()` internals logged on this exact path; new code doesn't.
- Finding 2 [Important]: 6 near-identical try/except/append blocks duplicated across `baseline.py`/`run_eval.py` — belong in `ragas_client.py`, which exists for exactly this.
- Finding 3 [Minor]: `build_llm()`/`build_embeddings()` missing return-type annotations the plan specifies. Low impact — `apps/eval` isn't type-checked by any gate.
- Finding 4 [Minor]: `openai` imported directly but only a transitive dependency in `pyproject.toml`. Approved trade-off, undocumented.
- Finding 5 [Minor]: `qwen3-embedding:0.6b` duplicated as a magic string in two modules (deliberate — different consumers — but no cross-reference comment).
- Out of scope: untracked eval artifacts (`dataset/qa_pairs.json`, `results/*.json`, `results/*.md`), no `.gitignore` under `apps/eval/results/` despite README claiming gitignored.

### Reviewer B — ponytail (over-engineering focus)

- 6 near-identical try/except/append blocks (51 lines) → one `safe_score(metric, **kwargs)` helper in `ragas_client.py`.
- `_mock_metric` helper duplicated verbatim in 3 test files, no `conftest.py`.
- `ANTHROPIC_API_KEY` redeclared in `baseline.py:15` despite importing from `ragas_client` on the next line.
- `_OLLAMA_URL`/`_EMBEDDING_MODEL` in `run_eval.py` byte-for-byte duplicate `ragas_client.OLLAMA_URL`/`EMBEDDING_MODEL`.
- Net: ~36 lines removable.

### Reviewer C — simplify (reuse/simplification/efficiency/altitude)

- REUSE/SIMPLIFICATION: same scoring-loop duplication (#1 above); `_mock_metric` duplicated in 3 files — **plan explicitly said "do not duplicate it,"** violated for `test_smoke.py`; `ANTHROPIC_API_KEY`/`OLLAMA_URL`/`EMBEDDING_MODEL` duplicate constants; redundant assertion in `test_ragas_client.py:53` (implied by the dict-equality check 3 lines later).
- EFFICIENCY: sequential (non-concurrent) scoring loop, down from ~16-way concurrent under the old `evaluate()` executor — but this is an explicit, spec-documented trade-off (design doc: "10-50 pairs is small enough that concurrency isn't worth the added complexity"). Flagged, not necessarily to fix.
- ALTITUDE: same silent-exception-swallowing issue as Reviewer A, with detail that this is plausibly why the round-1 async-client bug needed live debugging instead of surfacing from run output; `top_p`-pop workaround has no guard/comment tying it to `JUDGE_MODEL`'s specific value; **design spec and plan docs still show the pre-fix (buggy) sync-client, no-`top_p` code as current** — the two verification-fix commits never updated them.
- Checked/cleared: `SimpleBaseMetric.abatch_score()` exists but lacks `return_exceptions=True`, confirming the hand-written loop compensates for a real library gap, not a reuse miss.

## Consolidated issues

| ID | Severity | Summary | Evidence (file:line) |
|----|----------|---------|----------------------|
| 1 | important | 6 scoring `except Exception:` blocks swallow all errors with zero logging — a systemic outage produces null metrics + exit 0 with no diagnostic trace | `apps/eval/baseline.py:63-64,70-71`; `apps/eval/run_eval.py:118-119,127-128,136-137,143-144` |
| 2 | important | 6 near-identical try/except/append blocks belong in one shared helper in `ragas_client.py` (fixing alongside #1 kills both at once) | `apps/eval/baseline.py:54-71`; `apps/eval/run_eval.py:110-144` |
| 3 | important | `_mock_metric` duplicated verbatim in 3 test files; plan explicitly said "do not duplicate it" — violated for `test_smoke.py`; no `conftest.py` exists | `apps/eval/tests/unit/test_baseline.py:31-34`, `test_run_eval.py:26-29`, `test_smoke.py:110-113` |
| 4 | important | Design spec + plan docs still show pre-fix (buggy) code as current; the two verification-fix commits never updated them, risking regression if someone "fixes forward" from the docs | `docs/superpowers/specs/2026-07-01-eval-ragas-collections-migration-design.md:62-77,170`; `docs/superpowers/plans/2026-07-01-eval-ragas-collections-migration.md:115,125,134` |
| 5 | minor | `ANTHROPIC_API_KEY` redeclared in `baseline.py` instead of importing from `ragas_client` | `apps/eval/baseline.py:15` |
| 6 | minor | `_OLLAMA_URL`/`_EMBEDDING_MODEL` in `run_eval.py` duplicate `ragas_client` constants as literals (pre-existing, deliberate — different consumers) | `apps/eval/run_eval.py:29-30` |
| 7 | minor | `build_llm()`/`build_embeddings()` missing return-type annotations | `apps/eval/ragas_client.py:17,30` |
| 8 | minor | `openai` imported directly, only a transitive dependency | `apps/eval/ragas_client.py:7,35` |
| 9 | minor | Redundant assertion in `test_ragas_client.py` | `apps/eval/tests/unit/test_ragas_client.py:53` |
| 10 | minor | `top_p`-pop workaround has no comment tying correctness to `JUDGE_MODEL`'s value | `apps/eval/ragas_client.py:24-26` |

Claims rejected as not real / not worth acting on: sequential-scoring-loop efficiency finding (explicit spec trade-off, not a bug).

Out of scope for this diff (not fixed here): untracked eval artifacts (`dataset/qa_pairs.json`, `results/*.json`, `results/*.md`), missing `.gitignore` under `apps/eval/results/`.

## Disposition

- Actionable (blocking + important) — to fix this iteration: 1, 2, 3, 4
- Deferred (minor — NOT handled yet): 5, 6, 7, 8, 9, 10
