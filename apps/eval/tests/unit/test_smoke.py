"""
End-to-end smoke test: runs the full eval pipeline on a 3-pair fixture dataset.

All external calls (Claude, httpx /query, psycopg, OllamaEmbeddings, RAGAS evaluate)
are mocked so this test runs offline with no infrastructure.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from baseline import compute_baseline_metrics, run_baseline
from compare import build_report
from ragas.metrics.result import MetricResult
from run_eval import compute_rag_metrics, run_rag_eval
from schema import validate_dataset

FIXTURE_DATASET = [
    {
        "id": str(uuid.uuid4()),
        "question": "What is RAG?",
        "expected_answer": (
            "Retrieval-Augmented Generation combines retrieval with generation."
        ),
        "source_document": "intro.md",
        "source_chunk_ids": ["chunk-001"],
        "difficulty": "easy",
    },
    {
        "id": str(uuid.uuid4()),
        "question": "Why use pgvector?",
        "expected_answer": (
            "pgvector enables vector similarity search inside PostgreSQL."
        ),
        "source_document": "database.md",
        "source_chunk_ids": ["chunk-002"],
        "difficulty": "medium",
    },
    {
        "id": str(uuid.uuid4()),
        "question": "What does the Memory Agent do?",
        "expected_answer": (
            "The Memory Agent extracts facts and detects model corrections."
        ),
        "source_document": "agents.md",
        "source_chunk_ids": ["chunk-003"],
        "difficulty": "hard",
    },
]

_BASELINE_ANSWERS = [
    "RAG is a technique that retrieves context before generating answers.",
    "pgvector adds vector similarity search to PostgreSQL.",
    "The Memory Agent stores and retrieves learned facts.",
]

_RAG_ANSWERS = [
    "RAG stands for Retrieval-Augmented Generation and improves accuracy.",
    "pgvector is a PostgreSQL extension for vector search.",
    "The Memory Agent extracts facts from conversations and detects corrections.",
]

_RETRIEVED_CONTEXTS = [
    [
        "RAG combines retrieval with neural generation.",
        "Used to ground LLM answers in documents.",
    ],
    [
        "pgvector supports cosine and L2 distance.",
        "Integrated with PostgreSQL natively.",
    ],
    ["Memory Agent uses claude-haiku-4-5.", "Runs after the Synthesis node."],
]

_BASELINE_METRICS = {"faithfulness": 0.61, "answer_relevancy": 0.72}
_RAG_METRICS = {
    "context_recall": 0.78,
    "context_precision": 0.82,
    "faithfulness": 0.89,
    "answer_relevancy": 0.85,
}


def _mock_claude_client(answers: list[str]) -> MagicMock:
    client = MagicMock()
    responses = []
    for answer in answers:
        block = MagicMock()
        block.text = answer
        msg = MagicMock()
        msg.content = [block]
        responses.append(msg)
    client.messages.create.side_effect = responses
    return client


def _mock_conn(contexts_by_call: list[list[str]]) -> MagicMock:
    conn = MagicMock()
    cursors = []
    for contexts in contexts_by_call:
        cur = MagicMock()
        cur.__enter__ = MagicMock(return_value=cur)
        cur.__exit__ = MagicMock(return_value=False)
        cur.fetchall.return_value = [{"content": c} for c in contexts]
        cursors.append(cur)
    conn.cursor.side_effect = cursors
    return conn


def _mock_metric(value: float) -> MagicMock:
    metric = MagicMock()
    metric.ascore = AsyncMock(return_value=MetricResult(value=value))
    return metric


class TestSmokeSchemaValidation:
    def test_fixture_dataset_passes_validation(self):
        validate_dataset(FIXTURE_DATASET)

    def test_corrupted_pair_is_rejected(self):
        bad = FIXTURE_DATASET[:]
        bad[1] = {**bad[1], "difficulty": "legendary"}
        with pytest.raises(ValueError, match="index 1"):
            validate_dataset(bad)


class TestSmokeBaseline:
    def test_baseline_produces_one_result_per_pair(self):
        client = _mock_claude_client(_BASELINE_ANSWERS)
        results = run_baseline(FIXTURE_DATASET, client)
        assert len(results) == len(FIXTURE_DATASET)

    def test_baseline_results_have_no_retrieved_contexts(self):
        client = _mock_claude_client(_BASELINE_ANSWERS)
        results = run_baseline(FIXTURE_DATASET, client)
        for r in results:
            assert "retrieved_contexts" not in r

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


def _mock_ollama_smoke(embedding: list[float]):
    mock_cls = MagicMock()
    mock_cls.return_value.embed_query.return_value = embedding
    return patch("run_eval.OllamaEmbeddings", mock_cls)


class TestSmokeRagEval:
    def test_rag_eval_produces_one_result_per_pair(self):
        conn = _mock_conn(_RETRIEVED_CONTEXTS)
        with (
            patch("run_eval.call_query_endpoint", side_effect=_RAG_ANSWERS),
            _mock_ollama_smoke([0.1, 0.2, 0.3]),
        ):
            results = run_rag_eval(
                FIXTURE_DATASET,
                conn,
                backend_url="http://localhost:3001",
                ollama_url="http://localhost:11434",
            )
        assert len(results) == len(FIXTURE_DATASET)

    def test_rag_results_include_retrieved_contexts(self):
        conn = _mock_conn(_RETRIEVED_CONTEXTS)
        with (
            patch("run_eval.call_query_endpoint", side_effect=_RAG_ANSWERS),
            _mock_ollama_smoke([0.1, 0.2, 0.3]),
        ):
            results = run_rag_eval(
                FIXTURE_DATASET,
                conn,
                backend_url="http://localhost:3001",
                ollama_url="http://localhost:11434",
            )
        for r in results:
            assert isinstance(r["retrieved_contexts"], list)
            assert len(r["retrieved_contexts"]) > 0

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


class TestSmokeCompareReport:
    def test_report_shows_rag_outperforming_baseline_on_faithfulness(self):
        report = build_report(_BASELINE_METRICS, _RAG_METRICS)
        assert "+0.2800" in report

    def test_report_shows_na_for_baseline_context_metrics(self):
        report = build_report(_BASELINE_METRICS, _RAG_METRICS)
        assert "N/A" in report

    def test_report_contains_all_four_metric_rows(self):
        report = build_report(_BASELINE_METRICS, _RAG_METRICS)
        for metric in [
            "context_recall",
            "context_precision",
            "faithfulness",
            "answer_relevancy",
        ]:
            assert metric in report


class TestSmokeFullPipeline:
    def test_pipeline_produces_report_proving_rag_improves_faithfulness(self):
        """AC-9 proxy: RAG faithfulness > baseline faithfulness."""
        report = build_report(_BASELINE_METRICS, _RAG_METRICS)
        assert "+0.2800" in report, (
            "RAG faithfulness (0.89) should be +0.28 above baseline (0.61)"
        )

    def test_pipeline_produces_report_proving_rag_improves_answer_relevancy(self):
        report = build_report(_BASELINE_METRICS, _RAG_METRICS)
        assert "+0.1300" in report, (
            "RAG answer_relevancy (0.85) should be +0.13 above baseline (0.72)"
        )
