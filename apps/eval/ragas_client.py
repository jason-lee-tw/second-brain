"""Shared RAGAS LLM/embeddings setup and NaN-safe score aggregation."""

import math
import os
import sys

import anthropic
import openai
from ragas.embeddings.base import embedding_factory
from ragas.llms.base import llm_factory

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
EMBEDDING_MODEL = "qwen3-embedding:0.6b"
JUDGE_MODEL = "claude-sonnet-4-6"


def build_llm():
    """Instructor-based Anthropic LLM for RAGAS collections metrics."""
    llm = llm_factory(
        JUDGE_MODEL,
        provider="anthropic",
        client=anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY),
    )
    # claude-sonnet-4-6 rejects temperature+top_p together (HTTP 400);
    # ragas's InstructorModelArgs defaults both, so drop top_p, keep temperature.
    llm.model_args.pop("top_p", None)
    return llm


def build_embeddings():
    """Local Ollama embeddings via its OpenAI-compatible endpoint (no OpenAI key)."""
    return embedding_factory(
        "openai",
        model=EMBEDDING_MODEL,
        client=openai.AsyncOpenAI(base_url=f"{OLLAMA_URL}/v1", api_key="ollama"),
    )


def safe_mean(values: list[float]) -> float | None:
    """Average non-NaN scores; None if the list is empty or every score is NaN."""
    clean = [v for v in values if not math.isnan(v)]
    return round(sum(clean) / len(clean), 4) if clean else None


def sample_count(values: list[float]) -> int:
    """Count of non-NaN scores that actually contributed to safe_mean(values)."""
    return sum(1 for v in values if not math.isnan(v))


def summarize_scores(
    scores: dict[str, list[float]],
) -> tuple[dict[str, float | None], dict[str, int]]:
    """Reduce per-metric score lists to (metrics, sample_counts) via
    safe_mean/sample_count."""
    metrics = {name: safe_mean(values) for name, values in scores.items()}
    counts = {name: sample_count(values) for name, values in scores.items()}
    return metrics, counts


def print_metric_summary(
    metrics: dict[str, float | None], sample_counts: dict[str, int], total: int
) -> None:
    """Print one line per metric: name, mean, and how many samples scored."""
    for name, value in metrics.items():
        n = sample_counts[name]
        print(f"  {name + ':':<19}{value}  ({n}/{total} samples scored)")


async def score_or_nan(metric, **kwargs) -> float:
    """Score one sample; log and return NaN on failure so one bad sample
    doesn't lose the rest."""
    try:
        result = await metric.ascore(**kwargs)
        return result.value
    except Exception as e:
        print(
            f"{type(metric).__name__} scoring failed: {type(e).__name__}: {e}",
            file=sys.stderr,
        )
        return float("nan")
