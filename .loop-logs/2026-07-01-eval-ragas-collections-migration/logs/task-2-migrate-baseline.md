# Task 2 Log: Migrate `baseline.py` to `ragas.metrics.collections`

## Task Context

### Plan Section

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

### Acceptance Criteria
- AC-1: `compute_baseline_metrics()` returns `{"faithfulness": ..., "answer_relevancy": ...}` using `ragas.metrics.collections.{Faithfulness,AnswerRelevancy}`
- AC-2: values rounded to 4 decimal places
- AC-3: `context_recall`/`context_precision` never appear in baseline metrics
- AC-4: a NaN metric result becomes `None` after `safe_mean`
- AC-5: one sample's `.ascore()` exception does not lose other samples' scores (caught, becomes NaN, excluded from mean)
- AC-6: `compute_baseline_metrics(results)` signature and `main()` are unchanged

---

## Attempt 1 — 2026-07-01T04:24:56Z

### Implementation Plan
- Replace `TestComputeBaselineMetrics` in `test_baseline.py` with the collections-based version (delete `_mock_ragas_result` + `import pandas as pd`, add `_mock_metric` helper + `MetricResult` import)
- Update `test_smoke.py`'s `TestSmokeBaseline.test_baseline_metrics_contain_expected_keys`, add `_mock_metric` helper, extend `unittest.mock` import with `AsyncMock`, add `MetricResult` import — leave `_mock_ragas_result`/`pandas`/RAG-eval section untouched
- Run tests to confirm expected `AttributeError: ... does not have the attribute 'build_llm'` failures
- Replace `baseline.py`'s import block and `compute_baseline_metrics` with the `_score_all` async loop + `ragas_client` helpers, per plan Task 2 Step 3
- Run `just lint` and the targeted pytest command

### Files Changed
- modified `apps/eval/tests/unit/test_baseline.py` — replaced `TestComputeBaselineMetrics` with collections-based mocks (`_mock_metric`/`MetricResult`/`AsyncMock`), dropped `_mock_ragas_result`/`pandas`
- modified `apps/eval/tests/unit/test_smoke.py` — updated `test_baseline_metrics_contain_expected_keys` to mock `build_llm`/`build_embeddings`/`Faithfulness`/`AnswerRelevancy`; added `_mock_metric` helper and `AsyncMock`/`MetricResult` imports; `_mock_ragas_result`/`pandas`/RAG-eval section left untouched (Task 3 scope)
- modified `apps/eval/baseline.py` — new import block (`ragas.metrics.collections`, `ragas_client`, `asyncio`, dropped `math`/`langchain_anthropic`/`ragas` legacy imports); added `_score_all` async scoring loop; `compute_baseline_metrics` now calls `asyncio.run(_score_all(results))` + `safe_mean`; `main()` unchanged

### New Tests
- `test_metric_exception_for_one_sample_does_not_lose_others` (new AC-5 coverage; all other `TestComputeBaselineMetrics` tests are rewrites of pre-existing tests against the new mocking surface, not new behavior)

### Key Decisions
- Wrapped the `_score_all` docstring onto two lines to satisfy ruff `E501` (92 > 88 chars) — the plan's verbatim docstring text is preserved, only the line break changed, no design change.
- Needed to run `uv sync --all-extras` once in the fresh worktree before `ruff`/dev tools were available (worktree `.venv` existed but had no dev-dependency group installed yet); this is one-time worktree setup, not a code change.

### Lint Output
PASS

### Test Output
PASS (22 passed, 5 new/rewritten in `TestComputeBaselineMetrics`, 1 rewritten in `TestSmokeBaseline`; 0 failed. Remaining `DeprecationWarning`s in output are all from `run_eval.py`/`LangchainLLMWrapper` mocks, out of scope for Task 2 — Task 3 addresses them.)

### Commit
`ea258dc`

### Outcome: success
