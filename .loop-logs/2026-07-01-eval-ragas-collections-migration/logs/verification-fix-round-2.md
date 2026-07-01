# Verification Fix Round 2 — Anthropic 400 on judge LLM (temperature + top_p)

## Context

Round 1 fixed the async-client / RAGAS collections migration, but a live end-to-end
run of `just eval-baseline` / `just eval-rag` still exited 0 while every RAGAS metric
silently came back as `null`. Both `apps/eval/baseline.py` and `apps/eval/run_eval.py`
swallow scoring failures with a bare `except Exception: append(nan)` in `_score_all()`,
which hid the real error.

## Root cause (already confirmed by the requester before this task started)

`ragas.llms.base.InstructorModelArgs` (installed `ragas==0.4.3`) defaults to
`temperature=0.01` **and** `top_p=0.1`. For `provider="anthropic"`,
`InstructorLLM._map_provider_params()` passes both through unchanged to the Anthropic
Messages API. `claude-sonnet-4-6` rejects requests that set both parameters:

```
Error code: 400 - {'type': 'invalid_request_error', 'message': "\`temperature\` and \`top_p\`
cannot both be specified for this model. Please use only one."}
```

So every judge-LLM call inside RAGAS metric scoring (`faithfulness`,
`answer_relevancy`, `context_precision`, `context_recall`) raised a 400, was caught by
the bare `except Exception`, and appended `nan` — hence the report showing `null` for
every metric despite a clean exit code.

## Fix

`apps/eval/ragas_client.py`, `build_llm()`: after `llm_factory(...)` constructs the
`InstructorLLM`, pop `top_p` from its `model_args` dict before returning it. Each
`generate()`/`agenerate()` call does `self.model_args.copy()` fresh, so popping once at
construction time removes `top_p` from every subsequent call while leaving
`temperature` (which Anthropic accepts alone) untouched.

```python
def build_llm():
    """Instructor-based Anthropic LLM for RAGAS collections metrics."""
    llm = llm_factory(
        JUDGE_MODEL,
        provider="anthropic",
        client=anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY),
    )
    # claude-sonnet-4-6 rejects temperature+top_p together (HTTP 400);
    # ragas's InstructorModelArgs defaults both, so drop top_p, keep temperature.
    llm.model_args.pop("top_p", None)
    return llm
```

No changes to `build_embeddings()`, `safe_mean()`, `baseline.py`, or `run_eval.py` —
the bug and fix are isolated to `build_llm()`.

## TDD

Added `TestBuildLlm.test_drops_top_p_to_avoid_anthropic_400` to
`apps/eval/tests/unit/test_ragas_client.py`. The mock's `model_args` is set to a real
dict (`{"temperature": 0.01, "top_p": 0.1, "max_tokens": 1024}`) so `.pop()` mutates it
for real; the test asserts `"top_p" not in result.model_args` and that the dict equals
`{"temperature": 0.01, "max_tokens": 1024}` after the call.

Confirmed red before the fix:

```
FAILED tests/unit/test_ragas_client.py::TestBuildLlm::test_drops_top_p_to_avoid_anthropic_400
AssertionError: assert 'top_p' not in {'temperature': 0.01, 'top_p': 0.1, 'max_tokens': 1024}
```

Confirmed green after the fix (see full run below).

## Setup note

The worktree (`.worktrees/verification-fix-round-2`, branch
`worktree/verification-fix-round-2`, created from `feat/006-evaluation-harness` at
`63c7ed9`) had no `.venv` — `just lint` initially failed with
`error: Failed to spawn: 'ruff': No such file or directory`. Ran `uv sync --all-extras`
in the worktree root to install dev tools (ruff, basedpyright, pytest-asyncio, etc.),
after which `just lint` worked normally.

`apps/eval/.env` is gitignored and therefore not present in a fresh worktree checkout
(worktrees only materialize tracked files). Copied it byte-for-byte from the main repo
(`cp <main-repo>/apps/eval/.env <worktree>/apps/eval/.env`) without reading its
contents, purely so the live sanity check could source the real
`ANTHROPIC_API_KEY`. This file stays gitignored and was not committed.

## Full lint output

```
$ just lint
All checks passed!
```

## Full unit test output

```
$ uv run --directory apps/eval pytest tests/unit -v
...
tests/unit/test_ragas_client.py::TestSafeMean::test_averages_valid_scores PASSED [ 12%]
tests/unit/test_ragas_client.py::TestSafeMean::test_excludes_nan_values PASSED [ 25%]
tests/unit/test_ragas_client.py::TestSafeMean::test_all_nan_returns_none PASSED [ 37%]
tests/unit/test_ragas_client.py::TestSafeMean::test_empty_list_returns_none PASSED [ 41%]
tests/unit/test_ragas_client.py::TestSafeMean::test_rounds_to_4_decimal_places PASSED [ 42%]
tests/unit/test_ragas_client.py::TestBuildLlm::test_uses_anthropic_provider_and_judge_model PASSED [ 44%]
tests/unit/test_ragas_client.py::TestBuildLlm::test_drops_top_p_to_avoid_anthropic_400 PASSED [ 45%]
tests/unit/test_ragas_client.py::TestBuildEmbeddings::test_points_openai_client_at_ollama PASSED [ 46%]
... (all other pre-existing tests in test_baseline.py, test_compare.py,
     test_generate_dataset.py, test_run_eval.py, test_schema.py, test_smoke.py) ...
============================== 77 passed in 6.23s ==============================
```

Pre-commit hook also independently ran `just format lint` (102 files unchanged, all
checks passed) and `just type-check` (0 errors, 0 warnings, 8 pre-existing informational
notes unrelated to this change, in `memory_persistence.py` / `memory_retrieval.py`) —
both green.

## Live sanity check (real Anthropic API call)

```
$ set -a && source apps/eval/.env && set +a && uv run --directory apps/eval python -c "
import asyncio
from pydantic import BaseModel
import ragas_client

class Trivial(BaseModel):
    answer: str

async def main():
    llm = ragas_client.build_llm()
    print('model_args:', llm.model_args)
    r = await llm.agenerate('Reply with the word OK.', Trivial)
    print('SUCCESS:', r)

asyncio.run(main())
"
model_args: {'temperature': 0.01, 'max_tokens': 1024}
SUCCESS: answer='OK'
```

`top_p` is absent from `model_args`, and the real Anthropic call for
`claude-sonnet-4-6` succeeded (no 400) with a valid structured response. This confirms
the fix works against the live API, not just against mocks.

## Commit

```
6b420d5 fix(eval): drop top_p to avoid Anthropic 400 on judge LLM
 2 files changed, 24 insertions(+), 1 deletion(-)
 apps/eval/ragas_client.py
 apps/eval/tests/unit/test_ragas_client.py
```

Branch: `worktree/verification-fix-round-2` (in worktree
`.worktrees/verification-fix-round-2`), based on `feat/006-evaluation-harness` at
`63c7ed9`. Not merged back into `feat/006-evaluation-harness` — that is the calling
agent's/orchestrator's responsibility (use `git merge --squash`, per
`.claude/rules/git-linear-history.md`).

## Status: completed, attempt 1/3
