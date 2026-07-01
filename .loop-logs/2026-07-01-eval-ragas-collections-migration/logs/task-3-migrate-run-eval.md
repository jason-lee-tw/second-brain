# Task 3 Log: Migrate `run_eval.py` to `ragas.metrics.collections`

## Task Context

### Plan Section

### Task 3: Migrate `run_eval.py` to `ragas.metrics.collections`

**Files:**
- Modify: `apps/eval/run_eval.py`
- Modify: `apps/eval/tests/unit/test_run_eval.py`
- Modify: `apps/eval/tests/unit/test_smoke.py` (only `TestSmokeRagEval.test_rag_metrics_contain_all_four_keys`, plus removing the now-fully-unused `_mock_ragas_result` helper and `import pandas as pd`)

**Interfaces:**
- Consumes: `ragas_client.build_llm()`, `ragas_client.build_embeddings()`, `ragas_client.safe_mean(values: list[float]) -> float | None` from Task 1.
- Produces: `compute_rag_metrics(results: list[dict]) -> dict` (signature unchanged).

- [ ] **Step 1: Write the failing tests**

Replace the `TestComputeRagMetrics` class in `apps/eval/tests/unit/test_run_eval.py` (delete the old class and the now-unused `_mock_ragas_result` helper and `import pandas as pd` line; keep every other class in the file untouched):

```python
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from ragas.metrics.result import MetricResult
from run_eval import (
    call_query_endpoint,
    compute_rag_metrics,
    embed_query,
    fetch_top_k_chunks,
    run_rag_eval,
)


def _pair(question: str = "What is RAG?", expected: str = "RAG is cool.") -> dict:
    return {
        "id": str(uuid.uuid4()),
        "question": question,
        "expected_answer": expected,
        "source_document": "doc.md",
        "source_chunk_ids": ["chunk-001"],
        "difficulty": "easy",
    }


def _mock_metric(value: float) -> MagicMock:
    metric = MagicMock()
    metric.ascore = AsyncMock(return_value=MetricResult(value=value))
    return metric
```

(`TestCallQueryEndpoint`, `TestEmbedQuery`, `TestFetchTopKChunks`, `_mock_ollama`, `TestRunRagEval` stay exactly as they are today — only the metrics section changes.)

Replace `TestComputeRagMetrics`:

```python
class TestComputeRagMetrics:
    def test_returns_all_four_metrics(self):
        results = [
            {
                "question": "Q?",
                "generated_answer": "A.",
                "expected_answer": "A.",
                "retrieved_contexts": ["ctx"],
            }
        ]
        with (
            patch("run_eval.build_llm"),
            patch("run_eval.build_embeddings"),
            patch("run_eval.ContextRecall", return_value=_mock_metric(0.80)),
            patch("run_eval.ContextPrecision", return_value=_mock_metric(0.75)),
            patch("run_eval.Faithfulness", return_value=_mock_metric(0.90)),
            patch("run_eval.AnswerRelevancy", return_value=_mock_metric(0.85)),
        ):
            metrics = compute_rag_metrics(results)

        assert metrics == {
            "context_recall": 0.8,
            "context_precision": 0.75,
            "faithfulness": 0.9,
            "answer_relevancy": 0.85,
        }

    def test_metrics_are_rounded_to_4_decimal_places(self):
        results = [
            {
                "question": "Q?",
                "generated_answer": "A.",
                "expected_answer": "A.",
                "retrieved_contexts": ["ctx"],
            }
        ]
        with (
            patch("run_eval.build_llm"),
            patch("run_eval.build_embeddings"),
            patch("run_eval.ContextRecall", return_value=_mock_metric(0.801234567)),
            patch(
                "run_eval.ContextPrecision", return_value=_mock_metric(0.751234567)
            ),
            patch("run_eval.Faithfulness", return_value=_mock_metric(0.901234567)),
            patch(
                "run_eval.AnswerRelevancy", return_value=_mock_metric(0.851234567)
            ),
        ):
            metrics = compute_rag_metrics(results)

        assert metrics["context_recall"] == round(0.801234567, 4)

    def test_nan_metric_returns_none(self):
        results = [
            {
                "question": "Q?",
                "generated_answer": "A.",
                "expected_answer": "A.",
                "retrieved_contexts": ["ctx"],
            }
        ]
        with (
            patch("run_eval.build_llm"),
            patch("run_eval.build_embeddings"),
            patch(
                "run_eval.ContextRecall", return_value=_mock_metric(float("nan"))
            ),
            patch("run_eval.ContextPrecision", return_value=_mock_metric(0.75)),
            patch("run_eval.Faithfulness", return_value=_mock_metric(0.90)),
            patch("run_eval.AnswerRelevancy", return_value=_mock_metric(0.85)),
        ):
            metrics = compute_rag_metrics(results)

        assert metrics["context_recall"] is None
        assert metrics["faithfulness"] == 0.9

    def test_metric_exception_for_one_sample_does_not_lose_others(self):
        """A failing .ascore() call becomes NaN and is excluded from the mean,
        matching the old evaluate(raise_exceptions=False) behavior."""
        results = [
            {
                "question": "Q1?",
                "generated_answer": "A1.",
                "expected_answer": "A1.",
                "retrieved_contexts": ["ctx1"],
            },
            {
                "question": "Q2?",
                "generated_answer": "A2.",
                "expected_answer": "A2.",
                "retrieved_contexts": ["ctx2"],
            },
        ]
        faithfulness_metric = MagicMock()
        faithfulness_metric.ascore = AsyncMock(
            side_effect=[RuntimeError("LLM timeout"), MetricResult(value=0.9)]
        )
        with (
            patch("run_eval.build_llm"),
            patch("run_eval.build_embeddings"),
            patch("run_eval.ContextRecall", return_value=_mock_metric(0.8)),
            patch("run_eval.ContextPrecision", return_value=_mock_metric(0.8)),
            patch("run_eval.Faithfulness", return_value=faithfulness_metric),
            patch("run_eval.AnswerRelevancy", return_value=_mock_metric(0.8)),
        ):
            metrics = compute_rag_metrics(results)

        assert metrics["faithfulness"] == 0.9
```

Now update `apps/eval/tests/unit/test_smoke.py`. Remove `import pandas as pd` and the `_mock_ragas_result` helper (both now fully unused after this task). Add `from ragas.metrics.result import MetricResult` and extend the `unittest.mock` import to `from unittest.mock import AsyncMock, MagicMock, patch`. The `_mock_metric` helper added in Task 2 is reused here — do not duplicate it.

Replace `TestSmokeRagEval.test_rag_metrics_contain_all_four_keys`:

```python
    def test_rag_metrics_contain_all_four_keys(self):
        results = [
            {
                "question": p["question"],
                "generated_answer": a,
                "expected_answer": p["expected_answer"],
                "retrieved_contexts": ctx,
            }
            for p, a, ctx in zip(FIXTURE_DATASET, _RAG_ANSWERS, _RETRIEVED_CONTEXTS)
        ]
        with (
            patch("run_eval.build_llm"),
            patch("run_eval.build_embeddings"),
            patch(
                "run_eval.ContextRecall",
                return_value=_mock_metric(_RAG_METRICS["context_recall"]),
            ),
            patch(
                "run_eval.ContextPrecision",
                return_value=_mock_metric(_RAG_METRICS["context_precision"]),
            ),
            patch(
                "run_eval.Faithfulness",
                return_value=_mock_metric(_RAG_METRICS["faithfulness"]),
            ),
            patch(
                "run_eval.AnswerRelevancy",
                return_value=_mock_metric(_RAG_METRICS["answer_relevancy"]),
            ),
        ):
            metrics = compute_rag_metrics(results)
        assert set(metrics.keys()) == {
            "context_recall",
            "context_precision",
            "faithfulness",
            "answer_relevancy",
        }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --directory apps/eval pytest tests/unit/test_run_eval.py tests/unit/test_smoke.py -v`
Expected: FAIL — `AttributeError: <module 'run_eval'> does not have the attribute 'build_llm'` (or `'ContextRecall'` not yet importing from collections).

- [ ] **Step 3: Write the implementation**

In `apps/eval/run_eval.py`, replace the import block and drop the now-unused `ANTHROPIC_API_KEY` constant:

```python
#!/usr/bin/env python3
"""RAG pipeline evaluation.

Call /query endpoint, fetch retrieved contexts, run RAGAS.
"""

import argparse
import asyncio
import json
import os
import re
from pathlib import Path

import httpx
import psycopg
from langchain_ollama import OllamaEmbeddings
from psycopg.rows import dict_row
from ragas.metrics.collections import (
    AnswerRelevancy,
    ContextPrecision,
    ContextRecall,
    Faithfulness,
)
from ragas_client import build_embeddings, build_llm, safe_mean
from schema import validate_dataset

_BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:3001")
_DB_URL = re.sub(r"\+[^:]+(?=://)", "", os.environ.get("DATABASE_URL", ""))
_OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
_EMBEDDING_MODEL = "qwen3-embedding:0.6b"
_TOP_K = 5
```

(`math` import is removed — `safe_mean` now lives in `ragas_client.py`. `call_query_endpoint`, `embed_query`, `fetch_top_k_chunks`, and `run_rag_eval` are all unchanged.)

Replace `compute_rag_metrics`:

```python
async def _score_all(results: list[dict]) -> dict[str, list[float]]:
    """Score every result against all four RAGAS metrics, one sample at a time."""
    llm = build_llm()
    embeddings = build_embeddings()
    context_recall = ContextRecall(llm=llm)
    context_precision = ContextPrecision(llm=llm)
    faithfulness = Faithfulness(llm=llm)
    answer_relevancy = AnswerRelevancy(llm=llm, embeddings=embeddings)

    scores: dict[str, list[float]] = {
        "context_recall": [],
        "context_precision": [],
        "faithfulness": [],
        "answer_relevancy": [],
    }
    for r in results:
        try:
            score = await context_recall.ascore(
                user_input=r["question"],
                retrieved_contexts=r["retrieved_contexts"],
                reference=r["expected_answer"],
            )
            scores["context_recall"].append(score.value)
        except Exception:
            scores["context_recall"].append(float("nan"))
        try:
            score = await context_precision.ascore(
                user_input=r["question"],
                reference=r["expected_answer"],
                retrieved_contexts=r["retrieved_contexts"],
            )
            scores["context_precision"].append(score.value)
        except Exception:
            scores["context_precision"].append(float("nan"))
        try:
            score = await faithfulness.ascore(
                user_input=r["question"],
                response=r["generated_answer"],
                retrieved_contexts=r["retrieved_contexts"],
            )
            scores["faithfulness"].append(score.value)
        except Exception:
            scores["faithfulness"].append(float("nan"))
        try:
            score = await answer_relevancy.ascore(
                user_input=r["question"], response=r["generated_answer"]
            )
            scores["answer_relevancy"].append(score.value)
        except Exception:
            scores["answer_relevancy"].append(float("nan"))
    return scores


def compute_rag_metrics(results: list[dict]) -> dict:
    """Run all four RAGAS metrics on RAG pipeline results."""
    scores = asyncio.run(_score_all(results))
    return {name: safe_mean(values) for name, values in scores.items()}
```

`main()` is unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --directory apps/eval pytest tests/unit/test_run_eval.py tests/unit/test_smoke.py -v`
Expected: PASS

- [ ] **Step 5: Run the full eval unit test suite**

Run: `just test-eval`
Expected: PASS (all tests in `apps/eval/tests/unit/`, no `pandas`/`evaluate`/`LangchainLLMWrapper` references left anywhere)

- [ ] **Step 6: Commit**

```bash
git add apps/eval/run_eval.py apps/eval/tests/unit/test_run_eval.py apps/eval/tests/unit/test_smoke.py
git commit -m "fix(eval): migrate run_eval.py to ragas.metrics.collections"
```

### Acceptance Criteria
- AC-1: `compute_rag_metrics()` returns all four keys (`context_recall`, `context_precision`, `faithfulness`, `answer_relevancy`) using `ragas.metrics.collections`
- AC-2: values rounded to 4 decimal places
- AC-3: a NaN metric result becomes `None`
- AC-4: one sample's `.ascore()` exception does not lose other samples' scores
- AC-5: `compute_rag_metrics(results)` signature and `main()` are unchanged
- AC-6: `just test-eval` passes for the full suite with no `pandas`/`evaluate`/`LangchainLLMWrapper` references remaining anywhere in `apps/eval`

---

## Attempt 1 — 2026-07-01T04:32:16Z

### Implementation Plan
- Replace `TestComputeRagMetrics` in `test_run_eval.py` with the collections-based mocks given verbatim in the plan; drop `import pandas as pd` and `_mock_ragas_result`
- Update `test_smoke.py`: drop `import pandas as pd` and `_mock_ragas_result` (now fully unused), reuse the existing `_mock_metric` helper (added by Task 2), replace `TestSmokeRagEval.test_rag_metrics_contain_all_four_keys`
- Run targeted tests to confirm expected `AttributeError: module 'run_eval' has no attribute 'build_llm'` failures
- Rewrite `run_eval.py`'s import block, drop unused `ANTHROPIC_API_KEY` constant, add `_score_all` async loop, rewrite `compute_rag_metrics` per the plan
- Run lint, targeted tests, then the full `apps/eval/tests/unit` suite; grep for leftover `pandas`/`evaluate`/`LangchainLLMWrapper` references

### Files Changed
- modified `apps/eval/tests/unit/test_run_eval.py` — new `TestComputeRagMetrics` mocking `run_eval.build_llm`/`build_embeddings`/collections metric classes instead of `evaluate()`
- modified `apps/eval/tests/unit/test_smoke.py` — removed `import pandas as pd` and `_mock_ragas_result`; rewrote `TestSmokeRagEval.test_rag_metrics_contain_all_four_keys` to use `_mock_metric`
- modified `apps/eval/run_eval.py` — new import block (`ragas.metrics.collections`, `ragas_client`), dropped `ANTHROPIC_API_KEY`, added `_score_all` async scoring loop, rewrote `compute_rag_metrics` to call `asyncio.run(_score_all(results))` + `safe_mean`

### New Tests
- `test_metric_exception_for_one_sample_does_not_lose_others` (in `test_run_eval.py::TestComputeRagMetrics`) — new AC-4 coverage for per-sample `.ascore()` failure isolation; all other tests in the replaced class existed before under the same names but with new mocking strategy

### Key Decisions
- None beyond the plan's own design — followed the plan's exact test/implementation content verbatim, no deviations required (Tasks 1 and 2 were already merged, so `build_llm`/`build_embeddings`/`safe_mean`/`_mock_metric` were already available to import/reuse)

### Lint Output
PASS

### Test Output
PASS (76 passed — full `apps/eval/tests/unit` suite; targeted `test_run_eval.py`+`test_smoke.py` run also passed 25/25 before the full-suite run)
`grep -rn "import pandas\|ragas.evaluate\|LangchainLLMWrapper" apps/eval --include="*.py"` → empty (no matches)

### Commit
`6161ce8`

### Outcome: success
