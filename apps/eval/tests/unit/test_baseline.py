import uuid
from unittest.mock import MagicMock, patch

import pandas as pd
from baseline import compute_baseline_metrics, run_baseline


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


def _mock_ragas_result(scores: dict) -> MagicMock:
    mock = MagicMock()
    mock.to_pandas.return_value = pd.DataFrame([scores])
    return mock


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
        mock_result = _mock_ragas_result(
            {"faithfulness": 0.85, "answer_relevancy": 0.90}
        )

        with (
            patch("baseline.evaluate", return_value=mock_result),
            patch("baseline.ChatAnthropic"),
            patch("baseline.LangchainLLMWrapper"),
        ):
            metrics = compute_baseline_metrics(results)

        assert "faithfulness" in metrics
        assert "answer_relevancy" in metrics

    def test_metrics_are_rounded_to_4_decimal_places(self):
        results = [
            {"question": "Q?", "generated_answer": "A.", "expected_answer": "A."}
        ]
        mock_result = _mock_ragas_result(
            {"faithfulness": 0.856789123, "answer_relevancy": 0.901234567}
        )

        with (
            patch("baseline.evaluate", return_value=mock_result),
            patch("baseline.ChatAnthropic"),
            patch("baseline.LangchainLLMWrapper"),
        ):
            metrics = compute_baseline_metrics(results)

        assert metrics["faithfulness"] == round(0.856789123, 4)
        assert metrics["answer_relevancy"] == round(0.901234567, 4)

    def test_context_recall_is_not_in_baseline_metrics(self):
        """Baseline has no retrieval; context_recall/precision must be absent."""
        results = [
            {"question": "Q?", "generated_answer": "A.", "expected_answer": "A."}
        ]
        mock_result = _mock_ragas_result(
            {"faithfulness": 0.80, "answer_relevancy": 0.75}
        )

        with (
            patch("baseline.evaluate", return_value=mock_result),
            patch("baseline.ChatAnthropic"),
            patch("baseline.LangchainLLMWrapper"),
        ):
            metrics = compute_baseline_metrics(results)

        assert "context_recall" not in metrics
        assert "context_precision" not in metrics

    def test_nan_metric_returns_none(self):
        results = [
            {"question": "Q?", "generated_answer": "A.", "expected_answer": "A."}
        ]
        mock_result = _mock_ragas_result(
            {"faithfulness": float("nan"), "answer_relevancy": 0.80}
        )

        with (
            patch("baseline.evaluate", return_value=mock_result),
            patch("baseline.ChatAnthropic"),
            patch("baseline.LangchainLLMWrapper"),
        ):
            metrics = compute_baseline_metrics(results)

        assert metrics["faithfulness"] is None
        assert metrics["answer_relevancy"] == 0.8
