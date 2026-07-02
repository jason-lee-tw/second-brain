#!/usr/bin/env python3
"""RAG pipeline evaluation.

Call /query endpoint, fetch retrieved contexts, run RAGAS.
"""

import argparse
import asyncio
import json
import os
from pathlib import Path

import httpx
from ragas.metrics.collections import (
    AnswerRelevancy,
    ContextPrecision,
    ContextRecall,
    Faithfulness,
)
from ragas_client import (
    build_embeddings,
    build_llm,
    print_metric_summary,
    score_or_nan,
    summarize_scores,
)
from schema import validate_dataset

_BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:3001")


def call_query_endpoint(question: str, backend_url: str = _BACKEND_URL) -> dict:
    """POST /query and return the full parsed JSON response."""
    response = httpx.post(
        f"{backend_url}/query",
        json={"message": question, "sessionId": None},
        timeout=60.0,
    )
    response.raise_for_status()
    return response.json()


def run_rag_eval(
    qa_pairs: list[dict],
    backend_url: str = _BACKEND_URL,
) -> list[dict]:
    """Run the RAG pipeline for each Q&A pair."""
    results: list[dict] = []
    total = len(qa_pairs)
    for i, pair in enumerate(qa_pairs, start=1):
        print(f"  [{i}/{total}] {pair['question'][:70]}...")
        response = call_query_endpoint(pair["question"], backend_url=backend_url)
        generated_answer = response["answer"]
        # .get() (not direct index): this crosses a process boundary (HTTP call to
        # the backend), unlike query.py's internal state access — an older/different
        # backend deployment might not have this field yet.
        retrieved_contexts = response.get("retrievedContexts", [])
        results.append(
            {
                "question": pair["question"],
                "generated_answer": generated_answer,
                "expected_answer": pair["expected_answer"],
                "retrieved_contexts": retrieved_contexts,
            }
        )
    return results


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
        scores["context_recall"].append(
            await score_or_nan(
                context_recall,
                user_input=r["question"],
                retrieved_contexts=r["retrieved_contexts"],
                reference=r["expected_answer"],
            )
        )
        scores["context_precision"].append(
            await score_or_nan(
                context_precision,
                user_input=r["question"],
                reference=r["expected_answer"],
                retrieved_contexts=r["retrieved_contexts"],
            )
        )
        scores["faithfulness"].append(
            await score_or_nan(
                faithfulness,
                user_input=r["question"],
                response=r["generated_answer"],
                retrieved_contexts=r["retrieved_contexts"],
            )
        )
        scores["answer_relevancy"].append(
            await score_or_nan(
                answer_relevancy,
                user_input=r["question"],
                response=r["generated_answer"],
            )
        )
    return scores


def compute_rag_metrics(results: list[dict]) -> tuple[dict, dict]:
    """Run all four RAGAS metrics on RAG pipeline results.

    Returns (metrics, sample_counts): metrics maps each metric name to its
    mean (None if every sample was NaN); sample_counts maps each metric name
    to how many of the samples actually contributed a non-NaN score.
    """
    scores = asyncio.run(_score_all(results))
    return summarize_scores(scores)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run RAG pipeline evaluation with RAGAS."
    )
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--skip-metrics", action="store_true")
    args = parser.parse_args()

    with open(args.dataset) as f:
        qa_pairs = json.load(f)
    validate_dataset(qa_pairs)

    print(f"Running RAG eval on {len(qa_pairs)} Q&A pairs...")
    results = run_rag_eval(qa_pairs)

    metrics: dict = {}
    sample_counts: dict = {}
    if not args.skip_metrics:
        print("Computing RAGAS metrics (all 4)...")
        metrics, sample_counts = compute_rag_metrics(results)
        print_metric_summary(metrics, sample_counts, len(qa_pairs))

    output = {"metrics": metrics, "sample_counts": sample_counts, "results": results}
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"RAG results saved to {output_path}")


if __name__ == "__main__":
    main()
