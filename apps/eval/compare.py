#!/usr/bin/env python3
"""Generate a side-by-side comparison report from baseline and RAG eval results."""

import argparse
import json
from datetime import date
from pathlib import Path

_ALL_METRICS = [
    "context_recall",
    "context_precision",
    "faithfulness",
    "answer_relevancy",
]


def build_report(baseline_metrics: dict, rag_metrics: dict) -> str:
    """Build a markdown comparison report string."""
    rows: list[tuple[str, str, str, str]] = []
    for metric in _ALL_METRICS:
        baseline_val = baseline_metrics.get(metric)
        rag_val = rag_metrics.get(metric)

        baseline_str = f"{baseline_val:.4f}" if baseline_val is not None else "N/A"
        rag_str = f"{rag_val:.4f}" if rag_val is not None else "N/A"

        if baseline_val is not None and rag_val is not None:
            delta = rag_val - baseline_val
            delta_str = f"+{delta:.4f}" if delta >= 0 else f"{delta:.4f}"
        elif rag_val is not None:
            delta_str = f"+{rag_val:.4f}"
        else:
            delta_str = "N/A"

        rows.append((metric, baseline_str, rag_str, delta_str))

    lines = [
        f"# Evaluation Report — {date.today().isoformat()}",
        "",
        "## RAGAS Metrics: No-RAG Baseline vs RAG Pipeline",
        "",
        "| Metric              | No-RAG Baseline | RAG Pipeline | Delta   |",
        "|---------------------|----------------|--------------|---------|",
    ]
    for metric, b_str, r_str, d_str in rows:
        lines.append(f"| {metric:<19} | {b_str:<14} | {r_str:<12} | {d_str:<7} |")

    lines += [
        "",
        "> **Note:** Baseline metrics use `expected_answer` as proxy retrieved context",
        "> (no retrieval). They measure consistency with ground truth, not document",
        "> grounding. Compare with RAG values to assess the retrieval benefit.",
    ]

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare no-RAG baseline vs RAG pipeline evaluation results."
    )
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--rag", required=True)
    parser.add_argument("--output-dir", default="results")
    args = parser.parse_args()

    with open(args.baseline) as f:
        baseline_data = json.load(f)
    with open(args.rag) as f:
        rag_data = json.load(f)

    report = build_report(baseline_data.get("metrics", {}), rag_data.get("metrics", {}))
    print(report)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"{date.today().isoformat()}-eval-report.md"
    with open(report_path, "w") as f:
        f.write(report)
    print(f"Report saved to {report_path}")


if __name__ == "__main__":
    main()
