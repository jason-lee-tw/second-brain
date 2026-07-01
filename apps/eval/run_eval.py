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
from ragas_client import build_embeddings, build_llm, safe_mean, score_or_nan
from schema import validate_dataset

_BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:3001")
_DB_URL = re.sub(r"\+[^:]+(?=://)", "", os.environ.get("DATABASE_URL", ""))
_OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
_EMBEDDING_MODEL = "qwen3-embedding:0.6b"
_TOP_K = 5


def call_query_endpoint(question: str, backend_url: str = _BACKEND_URL) -> str:
    """POST /query and return the generated answer string."""
    response = httpx.post(
        f"{backend_url}/query",
        json={"message": question, "sessionId": None},
        timeout=60.0,
    )
    response.raise_for_status()
    return response.json()["answer"]


def fetch_top_k_chunks(conn, embedding: list[float], k: int = _TOP_K) -> list[str]:
    """Run pgvector cosine similarity search and return top-k chunk contents."""
    embedding_str = "[" + ",".join(str(v) for v in embedding) + "]"
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT content
            FROM document_chunks
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (embedding_str, k),
        )
        return [row["content"] for row in cur.fetchall()]


def run_rag_eval(
    qa_pairs: list[dict],
    conn,
    backend_url: str = _BACKEND_URL,
    ollama_url: str = _OLLAMA_URL,
) -> list[dict]:
    """Run the RAG pipeline for each Q&A pair."""
    embeddings = OllamaEmbeddings(model=_EMBEDDING_MODEL, base_url=ollama_url)
    results: list[dict] = []
    total = len(qa_pairs)
    for i, pair in enumerate(qa_pairs, start=1):
        print(f"  [{i}/{total}] {pair['question'][:70]}...")
        generated_answer = call_query_endpoint(
            pair["question"], backend_url=backend_url
        )
        embedding = embeddings.embed_query(pair["question"])
        retrieved_contexts = fetch_top_k_chunks(conn, embedding, k=_TOP_K)
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


def compute_rag_metrics(results: list[dict]) -> dict:
    """Run all four RAGAS metrics on RAG pipeline results."""
    scores = asyncio.run(_score_all(results))
    return {name: safe_mean(values) for name, values in scores.items()}


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

    conn = psycopg.connect(_DB_URL)
    try:
        print(f"Running RAG eval on {len(qa_pairs)} Q&A pairs...")
        results = run_rag_eval(qa_pairs, conn)
    finally:
        conn.close()

    metrics: dict = {}
    if not args.skip_metrics:
        print("Computing RAGAS metrics (all 4)...")
        metrics = compute_rag_metrics(results)
        print(f"  context_recall:    {metrics['context_recall']}")
        print(f"  context_precision: {metrics['context_precision']}")
        print(f"  faithfulness:      {metrics['faithfulness']}")
        print(f"  answer_relevancy:  {metrics['answer_relevancy']}")

    output = {"metrics": metrics, "results": results}
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"RAG results saved to {output_path}")


if __name__ == "__main__":
    main()
