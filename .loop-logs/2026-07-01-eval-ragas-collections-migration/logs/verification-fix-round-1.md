# Verification Fix Round 1 — async Anthropic/OpenAI clients in ragas_client

## Status: completed (attempt 1/3)

## What was wrong

`apps/eval/ragas_client.py`'s `build_llm()` constructed `anthropic.Anthropic(...)` (a
SYNC client) and passed it to `ragas.llms.base.llm_factory(..., provider="anthropic",
client=...)`. Similarly `build_embeddings()` constructed `openai.OpenAI(...)` (SYNC) and
passed it to `ragas.embeddings.base.embedding_factory(...)`.

`ragas.metrics.collections.{Faithfulness,AnswerRelevancy,ContextPrecision,
ContextRecall}.ascore()` internally call the LLM's `agenerate()` and (for
AnswerRelevancy) the embeddings' `aembed_text()`/`aembed_texts()` — async-only code
paths. Ragas's `InstructorLLM.agenerate()` (in `ragas/llms/base.py`) raises
`TypeError: Cannot use agenerate() with a synchronous client. Use generate() instead.`
when the wrapped client isn't async; `OpenAIEmbeddings.aembed_text()`/
`aembed_texts()` (in `ragas/embeddings/openai_provider.py`) has the same guard.

Both `apps/eval/baseline.py`'s and `apps/eval/run_eval.py`'s `_score_all()` caught this
`TypeError` with a bare `except Exception: append(nan)`, silently swallowing it — so
`just eval-baseline` and `just eval-rag` both exited 0 but every metric ended up `None`
(all-NaN → `safe_mean()` returns `None`). This had been verified live in the parent
session: booted the full stack, ran `just eval-baseline`/`just eval-rag` against real
Anthropic + local Ollama, both produced `null` for every metric.

## What was changed

Isolated fix in `apps/eval/ragas_client.py` only (per instructions, `baseline.py` and
`run_eval.py` were left untouched — the bug was solely in the two client
constructors):

- `build_llm()`: `anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)` →
  `anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)`
- `build_embeddings()`: `openai.OpenAI(base_url=f"{OLLAMA_URL}/v1", api_key="ollama")` →
  `openai.AsyncOpenAI(base_url=f"{OLLAMA_URL}/v1", api_key="ollama")`

TDD: updated the two existing tests in `apps/eval/tests/unit/test_ragas_client.py`
(`TestBuildLlm::test_uses_anthropic_provider_and_judge_model` and
`TestBuildEmbeddings::test_points_openai_client_at_ollama`) to patch
`ragas_client.anthropic.AsyncAnthropic` / `ragas_client.openai.AsyncOpenAI` instead of
the sync equivalents. Confirmed both failed against the unfixed implementation first
(`AsyncAnthropic`/`AsyncOpenAI` mocks were never called since the code still
constructed the sync clients), then applied the fix and confirmed both pass.

## Work done in isolated worktree

```
git worktree add .worktrees/verification-fix-round-1 -b worktree/verification-fix-round-1
```
Commit: `c9f2e26 fix(eval): use async Anthropic/OpenAI clients in ragas_client`
(2 files changed: `apps/eval/ragas_client.py`, `apps/eval/tests/unit/test_ragas_client.py`)

## Verification evidence

### 1. Tests fail pre-fix (confirms tests target the right behavior)

```
tests/unit/test_ragas_client.py::TestBuildLlm::test_uses_anthropic_provider_and_judge_model FAILED
tests/unit/test_ragas_client.py::TestBuildEmbeddings::test_points_openai_client_at_ollama FAILED
E   AssertionError: Expected 'AsyncAnthropic' to be called once. Called 0 times.
E   AssertionError: Expected 'AsyncOpenAI' to be called once. Called 0 times.
2 failed, 5 passed in 51.38s
```

### 2. `just lint` (root, after `uv sync --all-extras` to populate the worktree's root
venv with ruff/basedpyright which weren't yet installed):

```
All checks passed!
```

### 3. Full eval unit suite post-fix

```
uv run --directory apps/eval pytest tests/unit -v
...
============================== 76 passed in 6.32s ==============================
```

All 76 tests pass, including the two updated `TestBuildLlm`/`TestBuildEmbeddings`
tests and the full `test_baseline.py`, `test_run_eval.py`, `test_compare.py`,
`test_smoke.py` suites (no regressions).

### 4. Live smoke check (manual, not a permanent test)

Ran from `apps/eval/` directly (with a temporary local copy of the untracked
`apps/eval/.env`, removed afterward and never committed):

```python
import ragas_client
llm = ragas_client.build_llm()
print('llm.client type:', type(llm.client))
print('is_async:', llm.is_async)
print('underlying client type:', type(llm.client.client))
emb = ragas_client.build_embeddings()
print('emb client type:', type(emb.client))
```

Output:
```
llm.client type: <class 'instructor.v2.core.client.AsyncInstructor'>
is_async: True
underlying client type: <class 'anthropic.AsyncAnthropic'>
emb client type: <class 'openai.AsyncOpenAI'>
```

Confirms `is_async == True` and the underlying wrapped clients are the async variants
(`instructor` wraps the Anthropic client in an `AsyncInstructor`, whose `.client`
attribute is the raw `anthropic.AsyncAnthropic` instance — exactly as expected).

### 5. Pre-commit hooks (format/lint/type-check) on commit

```
🎨 Running 'just format lint'...
102 files left unchanged
All checks passed!
All checks passed!
🔄 Type checking...
0 errors, 0 warnings, 8 notes
✅ Type check is completed
✅ Pre-commit checks passed.
✅ Commit message format OK.
```

(The 8 "notes" are pre-existing `reportUnknownArgumentType` informational notes in
unrelated `apps/backend` files — not errors/warnings, not touched by this change.)

## Follow-up needed (not done here, out of scope for this fix)

This task only fixed `ragas_client.py`. It has NOT re-run `just eval-baseline` /
`just eval-rag` against the live stack to confirm real (non-null) RAGAS scores end to
end — that was explicitly out of scope per the task brief (isolated to the two client
constructors). A subsequent verification pass should re-run the live baseline/RAG eval
commands to confirm metrics are now non-null.
