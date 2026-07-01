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

_SYSTEM_PROMPT = (
    "You are a helpful assistant. Answer questions based on your general knowledge."
)


def run_baseline(qa_pairs: list[dict], client: anthropic.Anthropic) -> list[dict]:
    """Call Claude directly (no retrieval) for every Q&A pair."""
    results: list[dict] = []
    total = len(qa_pairs)
    for i, pair in enumerate(qa_pairs, start=1):
        print(f"  [{i}/{total}] {pair['question'][:70]}...")
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": pair["question"]}],
        )
        results.append(
            {
                "question": pair["question"],
                "generated_answer": message.content[0].text,
                "expected_answer": pair["expected_answer"],
            }
        )
    return results


async def _score_all(results: list[dict]) -> dict[str, list[float]]:
    """Score every result against Faithfulness and AnswerRelevancy, one sample
    at a time."""
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Run no-RAG baseline evaluation.")
    parser.add_argument(
        "--dataset", required=True, help="Path to curated qa_pairs.json"
    )
    parser.add_argument(
        "--output", required=True, help="Output path for baseline results JSON"
    )
    parser.add_argument("--skip-metrics", action="store_true")
    args = parser.parse_args()

    with open(args.dataset) as f:
        qa_pairs = json.load(f)
    validate_dataset(qa_pairs)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    print(f"Running no-RAG baseline on {len(qa_pairs)} Q&A pairs...")
    results = run_baseline(qa_pairs, client)

    metrics: dict = {}
    if not args.skip_metrics:
        print("Computing RAGAS metrics (faithfulness, answer_relevancy)...")
        metrics = compute_baseline_metrics(results)
        print(f"  faithfulness:     {metrics['faithfulness']}")
        print(f"  answer_relevancy: {metrics['answer_relevancy']}")

    output = {"metrics": metrics, "results": results}
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Baseline results saved to {output_path}")


if __name__ == "__main__":
    main()
