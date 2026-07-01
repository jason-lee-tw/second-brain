# Eval RAGAS Collections Migration Design

**Date:** 2026-07-01
**Status:** Approved

## Goal

`just eval-baseline` crashes with `openai.OpenAIError: Missing credentials` and prints
`ragas.metrics` / `LangchainLLMWrapper` deprecation warnings. Fix the crash and remove
the deprecated APIs, without breaking the existing offline unit test suite.

## Root cause

The crash is **not** about the judge LLM — `baseline.py` and `run_eval.py` already use
Anthropic (`ChatAnthropic(model="claude-sonnet-4-6")`) for that. `AnswerRelevancy` also
requires an **embeddings** model (cosine similarity between the original question and a
question regenerated from the answer). Neither file passes embeddings explicitly, so
RAGAS's `evaluate()` falls back to its OpenAI default embedder, which needs
`OPENAI_API_KEY`.

Anthropic and xAI/Grok do not expose public embeddings APIs, so swapping the judge LLM
provider would not fix this. The project already runs local embeddings via Ollama
(`qwen3-embedding:0.6b`, see `run_eval.py`) for RAG retrieval — reuse that.

## Why this isn't a one-line fix

Investigated whether we could just pass `embeddings=` into the existing
`evaluate()`/`EvaluationDataset` call. Ruled out:

- `ragas.metrics.{AnswerRelevancy,Faithfulness}` (legacy) are deprecated in ragas 0.4.3
  in favor of `ragas.metrics.collections.{AnswerRelevancy,Faithfulness}`.
- Collections metrics inherit from `ragas.metrics.collections.base.BaseMetric`, a
  **different class hierarchy** than `ragas.metrics.base.Metric`. `ragas.evaluate()`
  does `isinstance(m, Metric)` and rejects collections metrics outright.
- `ragas.evaluate()` itself now also emits its own `DeprecationWarning` (ragas is
  moving to an `@experiment` decorator / manual scoring pattern).

So fixing the crash *and* clearing the deprecation warnings requires dropping
`evaluate()` / `EvaluationDataset` / `SingleTurnSample` / `LangchainLLMWrapper`
entirely and hand-writing the scoring loop against the collections metrics' async
`.ascore()` API.

## Approach

### New shared module: `apps/eval/ragas_client.py`

```python
import math
import os

import anthropic
import openai
from ragas.embeddings.base import embedding_factory
from ragas.llms.base import llm_factory

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
EMBEDDING_MODEL = "qwen3-embedding:0.6b"
JUDGE_MODEL = "claude-sonnet-4-6"


def build_llm():
    """Instructor-based Anthropic LLM for RAGAS collections metrics."""
    return llm_factory(
        JUDGE_MODEL,
        provider="anthropic",
        client=anthropic.Anthropic(api_key=ANTHROPIC_API_KEY),
    )


def build_embeddings():
    """Local Ollama embeddings via its OpenAI-compatible endpoint (no OpenAI key)."""
    return embedding_factory(
        "openai",
        model=EMBEDDING_MODEL,
        client=openai.OpenAI(base_url=f"{OLLAMA_URL}/v1", api_key="ollama"),
    )


def safe_mean(values: list[float]) -> float | None:
    """Average non-NaN scores; None if every score is NaN."""
    clean = [v for v in values if not math.isnan(v)]
    return round(sum(clean) / len(clean), 4) if clean else None
```

- `build_llm()` uses `ragas.llms.base.llm_factory`, which patches the given client with
  `instructor` for structured output. `instructor` and `anthropic` are already
  installed (no new dependency).
- `build_embeddings()` points a plain `openai.OpenAI` client at Ollama's own
  `/v1/embeddings` endpoint instead of api.openai.com. `openai` is already installed
  transitively via `ragas`/`langchain-openai` (no new dependency). Reuses the same
  model `run_eval.py` already runs locally for retrieval.

### `apps/eval/baseline.py`

- Replace `from ragas.metrics import AnswerRelevancy, Faithfulness` with
  `from ragas.metrics.collections import AnswerRelevancy, Faithfulness`.
- Replace `LangchainLLMWrapper(ChatAnthropic(...))` + `evaluate(dataset=..., metrics=...)`
  with an explicit async loop:

```python
async def _score_all(results: list[dict]) -> dict[str, list[float]]:
    llm = ragas_client.build_llm()
    embeddings = ragas_client.build_embeddings()
    faithfulness = Faithfulness(llm=llm)
    answer_relevancy = AnswerRelevancy(llm=llm, embeddings=embeddings)

    faithfulness_scores: list[float] = []
    relevancy_scores: list[float] = []
    for r in results:
        try:
            score = await faithfulness.ascore(
                user_input=r["question"],
                response=r["generated_answer"],
                # ponytail: proxy for no-retrieval baseline
                retrieved_contexts=[r["expected_answer"]],
            )
            faithfulness_scores.append(score.value)
        except Exception:
            faithfulness_scores.append(float("nan"))
        try:
            score = await answer_relevancy.ascore(
                user_input=r["question"], response=r["generated_answer"]
            )
            relevancy_scores.append(score.value)
        except Exception:
            relevancy_scores.append(float("nan"))
    return {"faithfulness": faithfulness_scores, "answer_relevancy": relevancy_scores}


def compute_baseline_metrics(results: list[dict]) -> dict:
    scores = asyncio.run(_score_all(results))
    return {name: ragas_client.safe_mean(values) for name, values in scores.items()}
```

- `compute_baseline_metrics()` keeps its existing sync signature — `main()` is
  unchanged.
- Per-sample `try/except` → `nan` on failure, then `safe_mean()`, preserving today's
  `evaluate(..., raise_exceptions=False)` behavior: one bad sample doesn't lose the
  other 29 results.
- Sequential loop (matches the existing `run_baseline()` loop style; 10-50 pairs is
  small enough that concurrency isn't worth the added complexity).

### `apps/eval/run_eval.py`

Same treatment, extended to all four metrics:

```python
from ragas.metrics.collections import (
    AnswerRelevancy,
    ContextPrecision,
    ContextRecall,
    Faithfulness,
)

async def _score_all(results: list[dict]) -> dict[str, list[float]]:
    llm = ragas_client.build_llm()
    embeddings = ragas_client.build_embeddings()
    context_recall = ContextRecall(llm=llm)
    context_precision = ContextPrecision(llm=llm)
    faithfulness = Faithfulness(llm=llm)
    answer_relevancy = AnswerRelevancy(llm=llm, embeddings=embeddings)
    ...  # one try/except block per metric per sample, same pattern as baseline.py
```

- `run_eval.py` keeps its own `OllamaEmbeddings` (`langchain-ollama`) for embedding the
  *query* before the pgvector similarity search — that is a different consumer (needs
  a raw `list[float]`) from the RAGAS judge's `BaseRagasEmbedding` interface. Only the
  RAGAS metric construction switches to `ragas_client.build_embeddings()`.
- `ANTHROPIC_API_KEY` constant is removed from `run_eval.py`; it moves to
  `ragas_client.py`.

### Tests

`apps/eval/tests/unit/test_baseline.py`, `test_run_eval.py`, and `test_smoke.py`
currently mock `evaluate()`, `SingleTurnSample`, `EvaluationDataset`, and
`LangchainLLMWrapper`. Per TDD, rewrite these mocks *before* the implementation change:

- Mock `ragas_client.build_llm` / `build_embeddings` to return sentinel objects.
- Mock each collections metric class (`Faithfulness`, `AnswerRelevancy`,
  `ContextPrecision`, `ContextRecall`) so `.ascore()` is an `AsyncMock` returning a
  `MetricResult`-like object with a fixed `.value`.
- Add a test covering the per-sample-failure → NaN → excluded-from-mean path (this
  behavior currently has no direct test; it was implicit in `evaluate()`'s default).
- `just test-eval` must stay green throughout — no red-then-fix-later.

## What does NOT change

- `generate_dataset.py` — unaffected, doesn't touch RAGAS metrics.
- `compare.py` — unaffected, only reads already-computed metric JSON.
- `run_baseline()` / `run_rag_eval()` — the actual answer-generation loops are
  untouched; only the metrics-computation functions change.
- Public function signatures (`compute_baseline_metrics(results) -> dict`,
  `compute_rag_metrics(results) -> dict`) and `main()` in both files.
- `.env.template` — no new env vars needed; `OLLAMA_URL` already exists.

## Verification

Not yet confirmed against a live Ollama instance. Before calling this done:

1. `just up-all` (Ollama running, `qwen3-embedding:0.6b` pulled).
2. `just eval-baseline` end-to-end — confirm no `OpenAIError`, no deprecation
   warnings, and `faithfulness` / `answer_relevancy` scores are produced.
3. `just eval-rag` end-to-end — same check for all four metrics.
4. `just test-eval`, `just lint`, `just type-check` all pass.

## Decisions log

| # | Question | Decision | Why |
|---|----------|----------|-----|
| 1 | Embedding source for `AnswerRelevancy`? | Reuse Ollama `qwen3-embedding:0.6b` | Already running locally for retrieval; no API key; Anthropic/Grok have no embeddings API. |
| 2 | Handle `ragas.metrics` deprecation now or later? | Migrate now to `ragas.metrics.collections` | User chose to clear the warning permanently rather than defer; investigation showed this also removes the equally-deprecated `evaluate()` harness. |
| 3 | Fix `run_eval.py` too? | Yes, both files | Identical latent crash — untriggered only because baseline runs first. |
| 4 | Handle the 67 existing mocked unit tests? | Rewrite as part of this change | TDD requirement — `just test-eval` must stay green. |
| 5 | Keep `evaluate()`'s per-sample error tolerance? | Yes — catch, NaN, continue | Matches current behavior; one bad sample shouldn't lose the rest. |
| 6 | Scoring loop concurrency? | Sequential | Matches existing loop style; dataset is only 10-50 pairs. |
| 7 | Shared setup code (`llm_factory`/`embedding_factory`/NaN-mean)? | Extract `ragas_client.py` | Would otherwise be ~20 identical lines duplicated across two files being touched by this exact change. |
