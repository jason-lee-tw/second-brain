# Eval RAGAS Collections Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `just eval-baseline`'s `openai.OpenAIError: Missing credentials` crash and remove the `ragas.metrics`/`LangchainLLMWrapper`/`evaluate()` deprecation warnings, without breaking `just test-eval`.

**Architecture:** Add a small shared `apps/eval/ragas_client.py` module providing `build_llm()` (Anthropic via `ragas.llms.base.llm_factory`), `build_embeddings()` (local Ollama via its OpenAI-compatible endpoint, through `ragas.embeddings.base.embedding_factory`), and `safe_mean()` (NaN-tolerant averaging). `baseline.py` and `run_eval.py` drop `ragas.evaluate()`/`EvaluationDataset`/`SingleTurnSample`/`LangchainLLMWrapper` in favor of a small hand-written `async def _score_all(results)` loop per file that calls `ragas.metrics.collections.{Faithfulness,AnswerRelevancy,ContextPrecision,ContextRecall}.ascore()` per sample, wrapped in `asyncio.run()` inside the existing sync `compute_*_metrics()` functions.

**Tech Stack:** Python 3.12, ragas 0.4.3 (`ragas.metrics.collections`, `ragas.llms.base.llm_factory`, `ragas.embeddings.base.embedding_factory`), `anthropic`, `openai` (already installed transitively — talks to local Ollama, not api.openai.com), `instructor` (already installed transitively), pytest + `unittest.mock`.

## Global Constraints

- ragas version stays pinned at `ragas>=0.2.0,<0.5` in `apps/eval/pyproject.toml` — no version bump needed, 0.4.3 already has `ragas.metrics.collections`.
- No new dependencies are added. `openai` and `instructor` are already installed transitively via `ragas`; `anthropic` is already a direct dependency.
- `langchain-anthropic` and `pandas` become fully unused by this change and are removed via `uv remove` (never hand-edit the lockfile) — flagged here per CLAUDE.md's dependency-change rule.
- Per CLAUDE.md "Done Means": `just lint`, `just type-check`, and `just test-eval` must all pass after every task; TDD (failing test → implementation → passing test) for every behavior change.
- Public function signatures `compute_baseline_metrics(results: list[dict]) -> dict` and `compute_rag_metrics(results: list[dict]) -> dict`, and both files' `main()`, do not change.

---

### Task 1: Shared `ragas_client.py` helper

**Files:**
- Create: `apps/eval/ragas_client.py`
- Test: `apps/eval/tests/unit/test_ragas_client.py`

**Interfaces:**
- Produces: `build_llm() -> InstructorBaseRagasLLM`, `build_embeddings() -> BaseRagasEmbedding`, `safe_mean(values: list[float]) -> float | None`, module constants `ANTHROPIC_API_KEY: str`, `OLLAMA_URL: str`, `EMBEDDING_MODEL: str = "qwen3-embedding:0.6b"`, `JUDGE_MODEL: str = "claude-sonnet-4-6"`. Tasks 2 and 3 consume all of these via `from ragas_client import build_llm, build_embeddings, safe_mean`.

- [ ] **Step 1: Write the failing tests**

Create `apps/eval/tests/unit/test_ragas_client.py`:

```python
from unittest.mock import patch

import ragas_client


class TestSafeMean:
    def test_averages_valid_scores(self):
        assert ragas_client.safe_mean([0.8, 0.9, 1.0]) == round(0.9, 4)

    def test_excludes_nan_values(self):
        assert ragas_client.safe_mean([0.8, float("nan"), 1.0]) == round(0.9, 4)

    def test_all_nan_returns_none(self):
        assert ragas_client.safe_mean([float("nan"), float("nan")]) is None

    def test_empty_list_returns_none(self):
        assert ragas_client.safe_mean([]) is None

    def test_rounds_to_4_decimal_places(self):
        values = [0.123456789, 0.987654321]
        assert ragas_client.safe_mean(values) == round(sum(values) / len(values), 4)


class TestBuildLlm:
    def test_uses_anthropic_provider_and_judge_model(self):
        with (
            patch("ragas_client.anthropic.Anthropic") as mock_anthropic,
            patch("ragas_client.llm_factory") as mock_llm_factory,
        ):
            result = ragas_client.build_llm()

        mock_anthropic.assert_called_once_with(api_key=ragas_client.ANTHROPIC_API_KEY)
        mock_llm_factory.assert_called_once_with(
            ragas_client.JUDGE_MODEL,
            provider="anthropic",
            client=mock_anthropic.return_value,
        )
        assert result is mock_llm_factory.return_value


class TestBuildEmbeddings:
    def test_points_openai_client_at_ollama(self):
        with (
            patch("ragas_client.openai.OpenAI") as mock_openai,
            patch("ragas_client.embedding_factory") as mock_embedding_factory,
        ):
            result = ragas_client.build_embeddings()

        mock_openai.assert_called_once_with(
            base_url=f"{ragas_client.OLLAMA_URL}/v1", api_key="ollama"
        )
        mock_embedding_factory.assert_called_once_with(
            "openai",
            model=ragas_client.EMBEDDING_MODEL,
            client=mock_openai.return_value,
        )
        assert result is mock_embedding_factory.return_value
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --directory apps/eval pytest tests/unit/test_ragas_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ragas_client'`

- [ ] **Step 3: Write the implementation**

> Note: two additional fixes (async clients, `top_p` handling) were required after
> this task shipped, found during Task 5's live verification — see the design doc's
> Decisions log #8-9 and commits `63c7ed9`/`435619e`. The code block below already
> reflects those fixes.

Create `apps/eval/ragas_client.py`:

```python
"""Shared RAGAS LLM/embeddings setup and NaN-safe score aggregation."""

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
    llm = llm_factory(
        JUDGE_MODEL,
        provider="anthropic",
        client=anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY),
    )
    # claude-sonnet-4-6 rejects temperature+top_p together (HTTP 400);
    # ragas's InstructorModelArgs defaults both, so drop top_p, keep temperature.
    llm.model_args.pop("top_p", None)
    return llm


def build_embeddings():
    """Local Ollama embeddings via its OpenAI-compatible endpoint (no OpenAI key)."""
    return embedding_factory(
        "openai",
        model=EMBEDDING_MODEL,
        client=openai.AsyncOpenAI(base_url=f"{OLLAMA_URL}/v1", api_key="ollama"),
    )


def safe_mean(values: list[float]) -> float | None:
    """Average non-NaN scores; None if the list is empty or every score is NaN."""
    clean = [v for v in values if not math.isnan(v)]
    return round(sum(clean) / len(clean), 4) if clean else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --directory apps/eval pytest tests/unit/test_ragas_client.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/eval/ragas_client.py apps/eval/tests/unit/test_ragas_client.py
git commit -m "feat(eval): add shared ragas_client helper for LLM/embeddings setup"
```

---

### Task 2: Migrate `baseline.py` to `ragas.metrics.collections`

**Files:**
- Modify: `apps/eval/baseline.py`
- Modify: `apps/eval/tests/unit/test_baseline.py`
- Modify: `apps/eval/tests/unit/test_smoke.py` (only `TestSmokeBaseline.test_baseline_metrics_contain_expected_keys`)

**Interfaces:**
- Consumes: `ragas_client.build_llm()`, `ragas_client.build_embeddings()`, `ragas_client.safe_mean(values: list[float]) -> float | None` from Task 1.
- Produces: `compute_baseline_metrics(results: list[dict]) -> dict` (signature unchanged, consumed by `main()` in this file and by `test_smoke.py`).

- [ ] **Step 1: Write the failing tests**

Replace the `TestComputeBaselineMetrics` class in `apps/eval/tests/unit/test_baseline.py` (delete the old class and the now-unused `_mock_ragas_result` helper and `import pandas as pd` line; keep `TestRunBaseline` and `_make_qa_pairs` untouched):

```python
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from baseline import compute_baseline_metrics, run_baseline
from ragas.metrics.result import MetricResult


def _make_qa_pairs() -> list[dict]:
    return [
        {
            "id": str(uuid.uuid4()),
            "question": "What is LangGraph?",
            "expected_answer": (
                "LangGraph is a framework for multi-agent orchestration."
            ),
            "source_document": "agents.md",
            "source_chunk_ids": ["chunk-001"],
            "difficulty": "easy",
        },
        {
            "id": str(uuid.uuid4()),
            "question": "What embedding model is used?",
            "expected_answer": "qwen3-embedding:0.6b via Ollama.",
            "source_document": "config.md",
            "source_chunk_ids": ["chunk-002"],
            "difficulty": "medium",
        },
    ]


def _mock_metric(value: float) -> MagicMock:
    metric = MagicMock()
    metric.ascore = AsyncMock(return_value=MetricResult(value=value))
    return metric


class TestRunBaseline:
    def _make_client(self, answers: list[str]) -> MagicMock:
        client = MagicMock()
        responses = []
        for answer in answers:
            content_block = MagicMock()
            content_block.text = answer
            msg = MagicMock()
            msg.content = [content_block]
            responses.append(msg)
        client.messages.create.side_effect = responses
        return client

    def test_returns_one_result_per_pair(self):
        pairs = _make_qa_pairs()
        client = self._make_client(["Answer A.", "Answer B."])
        results = run_baseline(pairs, client)
        assert len(results) == 2

    def test_result_contains_required_keys(self):
        pairs = _make_qa_pairs()
        client = self._make_client(["Answer A.", "Answer B."])
        results = run_baseline(pairs, client)
        for r in results:
            assert "question" in r
            assert "generated_answer" in r
            assert "expected_answer" in r

    def test_generated_answer_comes_from_claude(self):
        pairs = _make_qa_pairs()
        client = self._make_client(["Claude answer 1.", "Claude answer 2."])
        results = run_baseline(pairs, client)
        assert results[0]["generated_answer"] == "Claude answer 1."
        assert results[1]["generated_answer"] == "Claude answer 2."

    def test_no_contexts_key_in_results(self):
        """Baseline results must NOT include retrieved_contexts."""
        pairs = _make_qa_pairs()
        client = self._make_client(["A.", "B."])
        results = run_baseline(pairs, client)
        for r in results:
            assert "retrieved_contexts" not in r


class TestComputeBaselineMetrics:
    def test_returns_faithfulness_and_answer_relevancy(self):
        results = [
            {"question": "Q?", "generated_answer": "A.", "expected_answer": "A."},
        ]
        with (
            patch("baseline.build_llm"),
            patch("baseline.build_embeddings"),
            patch("baseline.Faithfulness", return_value=_mock_metric(0.85)),
            patch("baseline.AnswerRelevancy", return_value=_mock_metric(0.90)),
        ):
            metrics = compute_baseline_metrics(results)

        assert metrics == {"faithfulness": 0.85, "answer_relevancy": 0.9}

    def test_metrics_are_rounded_to_4_decimal_places(self):
        results = [
            {"question": "Q?", "generated_answer": "A.", "expected_answer": "A."}
        ]
        with (
            patch("baseline.build_llm"),
            patch("baseline.build_embeddings"),
            patch("baseline.Faithfulness", return_value=_mock_metric(0.856789123)),
            patch("baseline.AnswerRelevancy", return_value=_mock_metric(0.901234567)),
        ):
            metrics = compute_baseline_metrics(results)

        assert metrics["faithfulness"] == round(0.856789123, 4)
        assert metrics["answer_relevancy"] == round(0.901234567, 4)

    def test_context_recall_is_not_in_baseline_metrics(self):
        """Baseline has no retrieval; context_recall/precision must be absent."""
        results = [
            {"question": "Q?", "generated_answer": "A.", "expected_answer": "A."}
        ]
        with (
            patch("baseline.build_llm"),
            patch("baseline.build_embeddings"),
            patch("baseline.Faithfulness", return_value=_mock_metric(0.80)),
            patch("baseline.AnswerRelevancy", return_value=_mock_metric(0.75)),
        ):
            metrics = compute_baseline_metrics(results)

        assert "context_recall" not in metrics
        assert "context_precision" not in metrics

    def test_nan_metric_returns_none(self):
        results = [
            {"question": "Q?", "generated_answer": "A.", "expected_answer": "A."}
        ]
        with (
            patch("baseline.build_llm"),
            patch("baseline.build_embeddings"),
            patch("baseline.Faithfulness", return_value=_mock_metric(float("nan"))),
            patch("baseline.AnswerRelevancy", return_value=_mock_metric(0.80)),
        ):
            metrics = compute_baseline_metrics(results)

        assert metrics["faithfulness"] is None
        assert metrics["answer_relevancy"] == 0.8

    def test_metric_exception_for_one_sample_does_not_lose_others(self):
        """A failing .ascore() call becomes NaN and is excluded from the mean,
        matching the old evaluate(raise_exceptions=False) behavior."""
        results = [
            {"question": "Q1?", "generated_answer": "A1.", "expected_answer": "A1."},
            {"question": "Q2?", "generated_answer": "A2.", "expected_answer": "A2."},
        ]
        faithfulness_metric = MagicMock()
        faithfulness_metric.ascore = AsyncMock(
            side_effect=[RuntimeError("LLM timeout"), MetricResult(value=0.9)]
        )
        with (
            patch("baseline.build_llm"),
            patch("baseline.build_embeddings"),
            patch("baseline.Faithfulness", return_value=faithfulness_metric),
            patch("baseline.AnswerRelevancy", return_value=_mock_metric(0.8)),
        ):
            metrics = compute_baseline_metrics(results)

        assert metrics["faithfulness"] == 0.9
        assert metrics["answer_relevancy"] == 0.8
```

Also update `apps/eval/tests/unit/test_smoke.py`'s `TestSmokeBaseline.test_baseline_metrics_contain_expected_keys` (delete its `_mock_ragas_result(_BASELINE_METRICS)` call and the `patch("baseline.evaluate"...)`/`patch("baseline.ChatAnthropic"...)`/`patch("baseline.LangchainLLMWrapper"...)` context managers):

```python
    def test_baseline_metrics_contain_expected_keys(self):
        results = [
            {
                "question": p["question"],
                "generated_answer": a,
                "expected_answer": p["expected_answer"],
            }
            for p, a in zip(FIXTURE_DATASET, _BASELINE_ANSWERS)
        ]
        with (
            patch("baseline.build_llm"),
            patch("baseline.build_embeddings"),
            patch(
                "baseline.Faithfulness",
                return_value=_mock_metric(_BASELINE_METRICS["faithfulness"]),
            ),
            patch(
                "baseline.AnswerRelevancy",
                return_value=_mock_metric(_BASELINE_METRICS["answer_relevancy"]),
            ),
        ):
            metrics = compute_baseline_metrics(results)
        assert "faithfulness" in metrics
        assert "answer_relevancy" in metrics
        assert "context_recall" not in metrics
```

Add the same `_mock_metric` helper to `test_smoke.py` (replacing `_mock_ragas_result`, which becomes unused once Task 3 also removes its last caller):

```python
def _mock_metric(value: float) -> MagicMock:
    metric = MagicMock()
    metric.ascore = AsyncMock(return_value=MetricResult(value=value))
    return metric
```

Add `from unittest.mock import AsyncMock, MagicMock, patch` (extend the existing `unittest.mock` import to include `AsyncMock`) and `from ragas.metrics.result import MetricResult` to the top of `test_smoke.py`. Leave `_mock_ragas_result`, `import pandas as pd`, and the RAG-eval section of `test_smoke.py` untouched for now — Task 3 removes them.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --directory apps/eval pytest tests/unit/test_baseline.py tests/unit/test_smoke.py -v`
Expected: FAIL — `test_baseline.py::TestComputeBaselineMetrics` tests fail with `AttributeError: <module 'baseline'> does not have the attribute 'build_llm'` (or `'Faithfulness'` not yet importing from collections); `test_smoke.py::TestSmokeBaseline::test_baseline_metrics_contain_expected_keys` fails the same way.

- [ ] **Step 3: Write the implementation**

In `apps/eval/baseline.py`, replace the import block:

```python
#!/usr/bin/env python3
"""No-RAG baseline: answer questions using Claude with no retrieval context."""

import argparse
import asyncio
import json
import os
from pathlib import Path

import anthropic
from ragas.metrics.collections import AnswerRelevancy, Faithfulness
from ragas_client import build_embeddings, build_llm, safe_mean
from schema import validate_dataset

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
```

(`math` import is removed — `safe_mean` now lives in `ragas_client.py`.)

Replace `compute_baseline_metrics` (and the `_SYSTEM_PROMPT`/`run_baseline` function above it are unchanged):

```python
async def _score_all(results: list[dict]) -> dict[str, list[float]]:
    """Score every result against Faithfulness and AnswerRelevancy, one sample at a time."""
    llm = build_llm()
    embeddings = build_embeddings()
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
    """Run RAGAS faithfulness and answer_relevancy on baseline results.

    Uses expected_answer as proxy retrieved_contexts — measures whether the
    model's no-RAG answer is consistent with ground truth (baseline for comparison).
    """
    scores = asyncio.run(_score_all(results))
    return {name: safe_mean(values) for name, values in scores.items()}
```

`main()` is unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --directory apps/eval pytest tests/unit/test_baseline.py tests/unit/test_smoke.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/eval/baseline.py apps/eval/tests/unit/test_baseline.py apps/eval/tests/unit/test_smoke.py
git commit -m "fix(eval): migrate baseline.py to ragas.metrics.collections"
```

---

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

---

### Task 4: Remove now-unused dependencies

**Files:**
- Modify: `apps/eval/pyproject.toml`
- Modify: `apps/eval/uv.lock` (or workspace root `uv.lock`, whichever `uv remove` updates — via `uv remove`, never by hand)

**Interfaces:** None (dependency-only change; no code touches these).

- [ ] **Step 1: Confirm nothing still imports them**

Run: `grep -rn "langchain_anthropic\|^import pandas\|import pandas as" apps/eval --include="*.py"`
Expected: no output (empty) — confirms both are fully unused after Tasks 2 and 3.

- [ ] **Step 2: Remove the dependencies**

```bash
uv remove --directory apps/eval langchain-anthropic pandas
```

Expected: `apps/eval/pyproject.toml`'s `dependencies` list no longer contains `langchain-anthropic` or `pandas`; `uv.lock` is updated by the command itself.

- [ ] **Step 3: Verify the workspace still resolves and tests still pass**

Run: `uv sync --all-extras && just test-eval`
Expected: PASS, no dependency resolution errors.

- [ ] **Step 4: Commit**

```bash
git add apps/eval/pyproject.toml uv.lock
git commit -m "chore(eval): remove langchain-anthropic and pandas, unused after RAGAS migration"
```

---

### Task 5: Lint, type-check, and live end-to-end verification

**Files:** None modified — verification only. Fix any issues surfaced here in the relevant file from Tasks 1-4 before considering the plan complete.

- [ ] **Step 1: Lint and format**

Run: `just lint`
Expected: no errors. If `ruff` flags anything (e.g. unused `os` import if it ends up unused in `run_eval.py` — it is still used for `_BACKEND_URL`/`_DB_URL`/`_OLLAMA_URL`, so it should be clean), fix inline and re-run.

- [ ] **Step 2: Type-check**

Run: `just type-check`
Expected: no new errors introduced by `ragas_client.py`, `baseline.py`, or `run_eval.py`.

- [ ] **Step 3: Start the stack**

Run: `just up-all`
Expected: Ollama, Postgres, Phoenix, and backend containers come up healthy.

- [ ] **Step 4: Confirm the embedding model is pulled**

Run: `curl -s http://localhost:11434/api/tags | grep -o 'qwen3-embedding[^"]*'`
Expected: `qwen3-embedding:0.6b` is listed. If not, run `ollama pull qwen3-embedding:0.6b` first.

- [ ] **Step 5: Run the baseline eval end-to-end**

Run: `just eval-baseline`
Expected: no `DeprecationWarning` output, no `openai.OpenAIError`, exits 0, prints non-null `faithfulness` and `answer_relevancy` scores, and writes `apps/eval/results/baseline.json`.

- [ ] **Step 6: Run the RAG eval end-to-end**

Run: `just eval-rag`
Expected: no `DeprecationWarning` output, no `openai.OpenAIError`, exits 0, prints non-null values for all four metrics, and writes `apps/eval/results/rag.json`.

- [ ] **Step 7: Generate the comparison report**

Run: `just eval-report`
Expected: exits 0, prints a markdown table comparing baseline vs RAG metrics.

- [ ] **Step 8: Final full-suite check**

Run: `just test-eval && just lint && just type-check`
Expected: all three pass with no errors, confirming the branch is shippable per CLAUDE.md's Done Means.
