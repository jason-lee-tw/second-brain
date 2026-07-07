import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from ragas.metrics.result import MetricResult
from run_eval import call_query_endpoint, compute_rag_metrics, run_rag_eval


def _pair(question: str = "What is RAG?", expected: str = "RAG is cool.") -> dict:
  return {
    "id": str(uuid.uuid4()),
    "question": question,
    "expected_answer": expected,
    "source_document": "doc.md",
    "source_chunk_ids": ["chunk-001"],
    "difficulty": "easy",
  }


class TestCallQueryEndpoint:
  def test_returns_full_response_dict(self):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
      "answer": "RAG stands for Retrieval-Augmented Generation.",
      "sessionId": str(uuid.uuid4()),
      "confidence": 0.9,
      "isUncertain": False,
      "conflictDetected": False,
      "conflictContext": [],
      "retrievedContexts": ["chunk A", "chunk B"],
    }
    with patch("run_eval.httpx.post", return_value=mock_response):
      response = call_query_endpoint(
        "What is RAG?", backend_url="http://localhost:3001"
      )
    assert response["answer"] == "RAG stands for Retrieval-Augmented Generation."
    assert response["retrievedContexts"] == ["chunk A", "chunk B"]

  def test_raises_on_http_error(self):
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = Exception("500 Internal Server Error")
    with patch("run_eval.httpx.post", return_value=mock_response):
      with pytest.raises(Exception, match="500"):
        call_query_endpoint("Q?", backend_url="http://localhost:3001")


class TestRunRagEval:
  def test_returns_one_result_per_pair(self):
    pairs = [_pair("Q1?", "A1."), _pair("Q2?", "A2.")]

    with patch(
      "run_eval.call_query_endpoint",
      side_effect=[
        {"answer": "Generated A1.", "retrievedContexts": ["ctx"]},
        {"answer": "Generated A2.", "retrievedContexts": ["ctx"]},
      ],
    ):
      results = run_rag_eval(pairs, backend_url="http://localhost:3001")

    assert len(results) == 2

  def test_result_has_retrieved_contexts(self):
    pairs = [_pair()]

    with patch(
      "run_eval.call_query_endpoint",
      return_value={
        "answer": "Answer.",
        "retrievedContexts": ["context 1", "context 2"],
      },
    ):
      results = run_rag_eval(pairs, backend_url="http://localhost:3001")

    assert results[0]["retrieved_contexts"] == ["context 1", "context 2"]

  def test_retrieved_contexts_empty_list_flows_through(self):
    """A 'neither' routing decision means no retrieval happened — the
    response's retrievedContexts is [] and must flow through unchanged."""
    pairs = [_pair()]

    with patch(
      "run_eval.call_query_endpoint",
      return_value={"answer": "Answer.", "retrievedContexts": []},
    ):
      results = run_rag_eval(pairs, backend_url="http://localhost:3001")

    assert results[0]["retrieved_contexts"] == []

  def test_missing_retrieved_contexts_key_defaults_to_empty_list(self):
    """Defensive/back-compat: if the backend response is missing the
    retrievedContexts key entirely, run_rag_eval must not crash."""
    pairs = [_pair()]

    with patch(
      "run_eval.call_query_endpoint",
      return_value={"answer": "Answer."},
    ):
      results = run_rag_eval(pairs, backend_url="http://localhost:3001")

    assert results[0]["retrieved_contexts"] == []

  def test_result_keys_are_complete(self):
    pairs = [_pair()]

    with patch(
      "run_eval.call_query_endpoint",
      return_value={"answer": "A.", "retrievedContexts": ["ctx"]},
    ):
      results = run_rag_eval(pairs, backend_url="http://localhost:3001")

    r = results[0]
    assert "question" in r
    assert "generated_answer" in r
    assert "expected_answer" in r
    assert "retrieved_contexts" in r


class TestComputeRagMetrics:
  def test_returns_all_four_metrics(self, mock_metric):
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
      patch("run_eval.ContextRecall", return_value=mock_metric(0.80)),
      patch("run_eval.ContextPrecision", return_value=mock_metric(0.75)),
      patch("run_eval.Faithfulness", return_value=mock_metric(0.90)),
      patch("run_eval.AnswerRelevancy", return_value=mock_metric(0.85)),
    ):
      metrics, sample_counts = compute_rag_metrics(results)

    assert metrics == {
      "context_recall": 0.8,
      "context_precision": 0.75,
      "faithfulness": 0.9,
      "answer_relevancy": 0.85,
    }
    assert sample_counts == {
      "context_recall": 1,
      "context_precision": 1,
      "faithfulness": 1,
      "answer_relevancy": 1,
    }

  def test_metrics_are_rounded_to_4_decimal_places(self, mock_metric):
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
      patch("run_eval.ContextRecall", return_value=mock_metric(0.801234567)),
      patch("run_eval.ContextPrecision", return_value=mock_metric(0.751234567)),
      patch("run_eval.Faithfulness", return_value=mock_metric(0.901234567)),
      patch("run_eval.AnswerRelevancy", return_value=mock_metric(0.851234567)),
    ):
      metrics, _ = compute_rag_metrics(results)

    assert metrics["context_recall"] == round(0.801234567, 4)

  def test_nan_metric_returns_none_and_zero_count(self, mock_metric):
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
      patch("run_eval.ContextRecall", return_value=mock_metric(float("nan"))),
      patch("run_eval.ContextPrecision", return_value=mock_metric(0.75)),
      patch("run_eval.Faithfulness", return_value=mock_metric(0.90)),
      patch("run_eval.AnswerRelevancy", return_value=mock_metric(0.85)),
    ):
      metrics, sample_counts = compute_rag_metrics(results)

    assert metrics["context_recall"] is None
    assert metrics["faithfulness"] == 0.9
    assert sample_counts["context_recall"] == 0
    assert sample_counts["faithfulness"] == 1

  def test_metric_exception_for_one_sample_does_not_lose_others(self, mock_metric):
    """A failing .ascore() call becomes NaN and is excluded from the mean,
    matching the old evaluate(raise_exceptions=False) behavior. The sample
    count reflects only the samples that actually scored."""
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
      patch("run_eval.ContextRecall", return_value=mock_metric(0.8)),
      patch("run_eval.ContextPrecision", return_value=mock_metric(0.8)),
      patch("run_eval.Faithfulness", return_value=faithfulness_metric),
      patch("run_eval.AnswerRelevancy", return_value=mock_metric(0.8)),
    ):
      metrics, sample_counts = compute_rag_metrics(results)

    assert metrics["faithfulness"] == 0.9
    assert sample_counts["faithfulness"] == 1
    assert sample_counts["context_recall"] == 2

  def test_all_nan_metric_has_zero_count_and_none_mean(self, mock_metric):
    results = [
      {
        "question": "Q?",
        "generated_answer": "A.",
        "expected_answer": "A.",
        "retrieved_contexts": [],
      }
    ]
    with (
      patch("run_eval.build_llm"),
      patch("run_eval.build_embeddings"),
      patch("run_eval.ContextRecall", return_value=mock_metric(float("nan"))),
      patch("run_eval.ContextPrecision", return_value=mock_metric(float("nan"))),
      patch("run_eval.Faithfulness", return_value=mock_metric(float("nan"))),
      patch("run_eval.AnswerRelevancy", return_value=mock_metric(0.5)),
    ):
      metrics, sample_counts = compute_rag_metrics(results)

    assert metrics["context_recall"] is None
    assert sample_counts["context_recall"] == 0
    assert sample_counts["context_precision"] == 0
    assert sample_counts["faithfulness"] == 0
    assert sample_counts["answer_relevancy"] == 1
