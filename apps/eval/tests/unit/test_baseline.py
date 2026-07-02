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
    def test_returns_faithfulness_and_answer_relevancy(self, mock_metric):
        results = [
            {"question": "Q?", "generated_answer": "A.", "expected_answer": "A."},
        ]
        with (
            patch("baseline.build_llm"),
            patch("baseline.build_embeddings"),
            patch("baseline.Faithfulness", return_value=mock_metric(0.85)),
            patch("baseline.AnswerRelevancy", return_value=mock_metric(0.90)),
        ):
            metrics, sample_counts = compute_baseline_metrics(results)

        assert metrics == {"faithfulness": 0.85, "answer_relevancy": 0.9}
        assert sample_counts == {"faithfulness": 1, "answer_relevancy": 1}

    def test_metrics_are_rounded_to_4_decimal_places(self, mock_metric):
        results = [
            {"question": "Q?", "generated_answer": "A.", "expected_answer": "A."}
        ]
        with (
            patch("baseline.build_llm"),
            patch("baseline.build_embeddings"),
            patch("baseline.Faithfulness", return_value=mock_metric(0.856789123)),
            patch("baseline.AnswerRelevancy", return_value=mock_metric(0.901234567)),
        ):
            metrics, _ = compute_baseline_metrics(results)

        assert metrics["faithfulness"] == round(0.856789123, 4)
        assert metrics["answer_relevancy"] == round(0.901234567, 4)

    def test_context_recall_is_not_in_baseline_metrics(self, mock_metric):
        """Baseline has no retrieval; context_recall/precision must be absent."""
        results = [
            {"question": "Q?", "generated_answer": "A.", "expected_answer": "A."}
        ]
        with (
            patch("baseline.build_llm"),
            patch("baseline.build_embeddings"),
            patch("baseline.Faithfulness", return_value=mock_metric(0.80)),
            patch("baseline.AnswerRelevancy", return_value=mock_metric(0.75)),
        ):
            metrics, _ = compute_baseline_metrics(results)

        assert "context_recall" not in metrics
        assert "context_precision" not in metrics

    def test_nan_metric_returns_none_and_zero_count(self, mock_metric):
        results = [
            {"question": "Q?", "generated_answer": "A.", "expected_answer": "A."}
        ]
        with (
            patch("baseline.build_llm"),
            patch("baseline.build_embeddings"),
            patch("baseline.Faithfulness", return_value=mock_metric(float("nan"))),
            patch("baseline.AnswerRelevancy", return_value=mock_metric(0.80)),
        ):
            metrics, sample_counts = compute_baseline_metrics(results)

        assert metrics["faithfulness"] is None
        assert metrics["answer_relevancy"] == 0.8
        assert sample_counts["faithfulness"] == 0
        assert sample_counts["answer_relevancy"] == 1

    def test_metric_exception_for_one_sample_does_not_lose_others(self, mock_metric):
        """A failing .ascore() call becomes NaN and is excluded from the mean,
        matching the old evaluate(raise_exceptions=False) behavior. The sample
        count reflects only the samples that actually scored."""
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
            patch("baseline.AnswerRelevancy", return_value=mock_metric(0.8)),
        ):
            metrics, sample_counts = compute_baseline_metrics(results)

        assert metrics["faithfulness"] == 0.9
        assert metrics["answer_relevancy"] == 0.8
        assert sample_counts["faithfulness"] == 1
        assert sample_counts["answer_relevancy"] == 2

    def test_all_nan_metric_has_zero_count_and_none_mean(self, mock_metric):
        results = [
            {"question": "Q?", "generated_answer": "A.", "expected_answer": "A."}
        ]
        with (
            patch("baseline.build_llm"),
            patch("baseline.build_embeddings"),
            patch("baseline.Faithfulness", return_value=mock_metric(float("nan"))),
            patch("baseline.AnswerRelevancy", return_value=mock_metric(float("nan"))),
        ):
            metrics, sample_counts = compute_baseline_metrics(results)

        assert metrics["faithfulness"] is None
        assert metrics["answer_relevancy"] is None
        assert sample_counts["faithfulness"] == 0
        assert sample_counts["answer_relevancy"] == 0
