#!/usr/bin/env python3
"""Generate synthetic Q&A pairs from ingested document chunks using Claude."""

import argparse
import json
import os
import re
import uuid
from pathlib import Path

import anthropic
import psycopg
from psycopg.rows import dict_row

_DB_URL = re.sub(r"\+[^:/]+", "", os.environ.get("DATABASE_URL", ""))
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

_GENERATION_PROMPT = """\
Given this document content, generate {n} Q&A pairs for evaluating a RAG system.
For each pair:
- Question should require understanding the document content
- Expected answer should be factually grounded in the document
- Include the difficulty level (easy/medium/hard)
Output as a JSON array of objects with exactly these fields:
question, expected_answer, difficulty

Document: {content}"""


def _strip_code_fences(text: str) -> str:
    """Remove leading/trailing markdown code fences (```json ... ``` or ``` ... ```)."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        inner_lines = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        return "\n".join(inner_lines)
    return text


def generate_qa_pairs_for_document(
    client: anthropic.Anthropic, doc: dict, n: int = 7
) -> list[dict]:
    """Call Claude to generate n Q&A pairs for a single document dict."""
    prompt = _GENERATION_PROMPT.format(n=n, content=doc["full_content"][:8000])
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    raw_text = _strip_code_fences(message.content[0].text)
    pairs_raw: list[dict] = json.loads(raw_text)
    return [
        {
            "id": str(uuid.uuid4()),
            "question": p["question"],
            "expected_answer": p["expected_answer"],
            "source_document": doc["filename"],
            "source_chunk_ids": doc["chunk_ids"],
            "difficulty": p.get("difficulty", "medium"),
        }
        for p in pairs_raw
    ]


def _fetch_documents(conn) -> list[dict]:
    """Query pgvector for all processed documents with their chunks."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT
                d.id::text AS doc_id,
                d.filename,
                array_agg(c.id::text ORDER BY c.chunk_index) AS chunk_ids,
                string_agg(c.content, E'\n\n' ORDER BY c.chunk_index) AS full_content
            FROM ingested_documents d
            JOIN document_chunks c ON c.doc_id = d.id
            WHERE d.status = 'processed'
            GROUP BY d.id, d.filename
            """
        )
        return cur.fetchall()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate synthetic Q&A pairs from ingested documents."
    )
    parser.add_argument("--n-per-doc", type=int, default=7)
    parser.add_argument("--output", default="dataset/raw_qa_pairs.json")
    args = parser.parse_args()

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    conn = psycopg.connect(_DB_URL)
    try:
        documents = _fetch_documents(conn)
    finally:
        conn.close()

    if not documents:
        print("No processed documents found. Run ingestion first.")
        return

    all_pairs: list[dict] = []
    for doc in documents:
        print(f"Generating {args.n_per_doc} Q&A pairs for: {doc['filename']}")
        pairs = generate_qa_pairs_for_document(client, doc, n=args.n_per_doc)
        all_pairs.extend(pairs)
        print(f"  -> {len(pairs)} pairs generated.")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(all_pairs, f, indent=2)

    print(f"\nTotal: {len(all_pairs)} raw Q&A pairs saved to {output_path}")
    print("Next: review, curate 30-50 pairs, save as dataset/qa_pairs.json")


if __name__ == "__main__":
    main()
