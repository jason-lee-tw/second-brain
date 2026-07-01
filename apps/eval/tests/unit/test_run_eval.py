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


class TestCallQueryEndpoint:
    def test_returns_answer_string(self):
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "answer": "RAG stands for Retrieval-Augmented Generation.",
            "sessionId": str(uuid.uuid4()),
            "confidence": 0.9,
            "isUncertain": False,
            "conflictDetected": False,
            "conflictContext": [],
        }
        with patch("run_eval.httpx.post", return_value=mock_response):
            answer = call_query_endpoint(
                "What is RAG?", backend_url="http://localhost:3001"
            )
        assert answer == "RAG stands for Retrieval-Augmented Generation."

    def test_raises_on_http_error(self):
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception(
            "500 Internal Server Error"
        )
        with patch("run_eval.httpx.post", return_value=mock_response):
            with pytest.raises(Exception, match="500"):
                call_query_endpoint("Q?", backend_url="http://localhost:3001")


class TestEmbedQuery:
    def test_returns_list_of_floats(self):
        with patch("run_eval.OllamaEmbeddings") as mock_cls:
            mock_cls.return_value.embed_query.return_value = [0.1, 0.2, 0.3]
            embedding = embed_query("What is RAG?", ollama_url="http://localhost:11434")
        assert embedding == [0.1, 0.2, 0.3]


class TestFetchTopKChunks:
    def test_returns_list_of_content_strings(self):
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_cursor.fetchall.return_value = [
            {"content": "Chunk A content"},
            {"content": "Chunk B content"},
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        chunks = fetch_top_k_chunks(mock_conn, embedding=[0.1, 0.2], k=2)
        assert chunks == ["Chunk A content", "Chunk B content"]

    def test_respects_k_limit_in_query(self):
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_cursor.fetchall.return_value = [{"content": "Only chunk"}]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        fetch_top_k_chunks(mock_conn, embedding=[0.5], k=1)
        call_args = mock_cursor.execute.call_args
        assert 1 in call_args[0][1]


def _mock_ollama(embedding: list[float]):
    mock_cls = MagicMock()
    mock_cls.return_value.embed_query.return_value = embedding
    return patch("run_eval.OllamaEmbeddings", mock_cls)


class TestRunRagEval:
    def test_returns_one_result_per_pair(self):
        pairs = [_pair("Q1?", "A1."), _pair("Q2?", "A2.")]

        with (
            patch(
                "run_eval.call_query_endpoint",
                side_effect=["Generated A1.", "Generated A2."],
            ),
            _mock_ollama([0.1, 0.2, 0.3]),
            patch("run_eval.fetch_top_k_chunks", return_value=["ctx chunk"]),
        ):
            results = run_rag_eval(
                pairs,
                conn=MagicMock(),
                backend_url="http://localhost:3001",
                ollama_url="http://localhost:11434",
            )

        assert len(results) == 2

    def test_result_has_retrieved_contexts(self):
        pairs = [_pair()]

        with (
            patch("run_eval.call_query_endpoint", return_value="Answer."),
            _mock_ollama([0.1]),
            patch(
                "run_eval.fetch_top_k_chunks",
                return_value=["context 1", "context 2"],
            ),
        ):
            results = run_rag_eval(
                pairs,
                conn=MagicMock(),
                backend_url="http://localhost:3001",
                ollama_url="http://localhost:11434",
            )

        assert results[0]["retrieved_contexts"] == ["context 1", "context 2"]

    def test_result_keys_are_complete(self):
        pairs = [_pair()]

        with (
            patch("run_eval.call_query_endpoint", return_value="A."),
            _mock_ollama([0.1]),
            patch("run_eval.fetch_top_k_chunks", return_value=["ctx"]),
        ):
            results = run_rag_eval(
                pairs,
                conn=MagicMock(),
                backend_url="http://localhost:3001",
                ollama_url="http://localhost:11434",
            )

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
            metrics = compute_rag_metrics(results)

        assert metrics == {
            "context_recall": 0.8,
            "context_precision": 0.75,
            "faithfulness": 0.9,
            "answer_relevancy": 0.85,
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
            metrics = compute_rag_metrics(results)

        assert metrics["context_recall"] == round(0.801234567, 4)

    def test_nan_metric_returns_none(self, mock_metric):
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
            metrics = compute_rag_metrics(results)

        assert metrics["context_recall"] is None
        assert metrics["faithfulness"] == 0.9

    def test_metric_exception_for_one_sample_does_not_lose_others(self, mock_metric):
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
            patch("run_eval.ContextRecall", return_value=mock_metric(0.8)),
            patch("run_eval.ContextPrecision", return_value=mock_metric(0.8)),
            patch("run_eval.Faithfulness", return_value=faithfulness_metric),
            patch("run_eval.AnswerRelevancy", return_value=mock_metric(0.8)),
        ):
            metrics = compute_rag_metrics(results)

        assert metrics["faithfulness"] == 0.9
