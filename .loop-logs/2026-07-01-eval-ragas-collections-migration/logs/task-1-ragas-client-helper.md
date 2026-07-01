# Task 1 Log: Shared `ragas_client.py` helper

## Task Context

### Plan Section

### Task 1: Shared `ragas_client.py` helper

**Files:**

- Create: `apps/eval/ragas_client.py`
- Test: `apps/eval/tests/unit/test_ragas_client.py`

**Interfaces:**

- Produces: `build_llm() -> InstructorBaseRagasLLM`, `build_embeddings() -> BaseRagasEmbedding`, `safe_mean(values: list[float]) -> float | None`, module constants `ANTHROPIC_API_KEY: str`, `OLLAMA_URL: str`, `EMBEDDING_MODEL: str = "qwen3-embedding:0.6b"`, `JUDGE_MODEL: str = "claude-sonnet-4-6"`. Tasks 2 and 3 consume all of these via `from ragas_client import build_llm, build_embeddings, safe_mean`.

- [ ] **Step 1: Write the failing tests**

Create `apps/eval/tests/unit/test_ragas_client.py`:

```python
from unittest.mock import patch

import ragas_client


class TestSafeMean:
    def test_averages_valid_scores(self):
        assert ragas_client.safe_mean([0.8, 0.9, 1.0]) == round(0.9, 4)

    def test_excludes_nan_values(self):
        assert ragas_client.safe_mean([0.8, float("nan"), 1.0]) == round(0.9, 4)

    def test_all_nan_returns_none(self):
        assert ragas_client.safe_mean([float("nan"), float("nan")]) is None

    def test_empty_list_returns_none(self):
        assert ragas_client.safe_mean([]) is None

    def test_rounds_to_4_decimal_places(self):
        values = [0.123456789, 0.987654321]
        assert ragas_client.safe_mean(values) == round(sum(values) / len(values), 4)


class TestBuildLlm:
    def test_uses_anthropic_provider_and_judge_model(self):
        with (
            patch("ragas_client.anthropic.Anthropic") as mock_anthropic,
            patch("ragas_client.llm_factory") as mock_llm_factory,
        ):
            result = ragas_client.build_llm()

        mock_anthropic.assert_called_once_with(api_key=ragas_client.ANTHROPIC_API_KEY)
        mock_llm_factory.assert_called_once_with(
            ragas_client.JUDGE_MODEL,
            provider="anthropic",
            client=mock_anthropic.return_value,
        )
        assert result is mock_llm_factory.return_value


class TestBuildEmbeddings:
    def test_points_openai_client_at_ollama(self):
        with (
            patch("ragas_client.openai.OpenAI") as mock_openai,
            patch("ragas_client.embedding_factory") as mock_embedding_factory,
        ):
            result = ragas_client.build_embeddings()

        mock_openai.assert_called_once_with(
            base_url=f"{ragas_client.OLLAMA_URL}/v1", api_key="ollama"
        )
        mock_embedding_factory.assert_called_once_with(
            "openai",
            model=ragas_client.EMBEDDING_MODEL,
            client=mock_openai.return_value,
        )
        assert result is mock_embedding_factory.return_value
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --directory apps/eval pytest tests/unit/test_ragas_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ragas_client'`

- [ ] **Step 3: Write the implementation**

Create `apps/eval/ragas_client.py`:

```python
"""Shared RAGAS LLM/embeddings setup and NaN-safe score aggregation."""

import math
import os

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
    return llm_factory(
        JUDGE_MODEL,
        provider="anthropic",
        client=anthropic.Anthropic(api_key=ANTHROPIC_API_KEY),
    )


def build_embeddings():
    """Local Ollama embeddings via its OpenAI-compatible endpoint (no OpenAI key)."""
    return embedding_factory(
        "openai",
        model=EMBEDDING_MODEL,
        client=openai.OpenAI(base_url=f"{OLLAMA_URL}/v1", api_key="ollama"),
    )


def safe_mean(values: list[float]) -> float | None:
    """Average non-NaN scores; None if the list is empty or every score is NaN."""
    clean = [v for v in values if not math.isnan(v)]
    return round(sum(clean) / len(clean), 4) if clean else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --directory apps/eval pytest tests/unit/test_ragas_client.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/eval/ragas_client.py apps/eval/tests/unit/test_ragas_client.py
git commit -m "feat(eval): add shared ragas_client helper for LLM/embeddings setup"
```

### Acceptance Criteria

- AC-1: `build_llm()` returns an Anthropic-backed ragas LLM via `llm_factory(JUDGE_MODEL, provider="anthropic", client=...)`
- AC-2: `build_embeddings()` returns an Ollama-backed ragas embedding via `embedding_factory("openai", model=EMBEDDING_MODEL, client=...)` pointed at `{OLLAMA_URL}/v1`
- AC-3: `safe_mean()` averages non-NaN values, rounds to 4 decimals, returns None for empty/all-NaN input

---

## Attempt 1 — 2026-07-01T04:19:08Z

### Implementation Plan

- Write `apps/eval/tests/unit/test_ragas_client.py` exactly as specified in the plan Step 1
- Run pytest to confirm `ModuleNotFoundError: No module named 'ragas_client'`
- Write `apps/eval/ragas_client.py` exactly as specified in the plan Step 3
- Run `just lint` and the pytest command to confirm both green

### Files Changed

- created `apps/eval/ragas_client.py` — shared RAGAS LLM/embeddings builders and NaN-safe mean helper
- created `apps/eval/tests/unit/test_ragas_client.py` — unit tests for `safe_mean`, `build_llm`, `build_embeddings`

### New Tests

- `test_averages_valid_scores`
- `test_excludes_nan_values`
- `test_all_nan_returns_none`
- `test_empty_list_returns_none`
- `test_rounds_to_4_decimal_places`
- `test_uses_anthropic_provider_and_judge_model`
- `test_points_openai_client_at_ollama`

### Key Decisions

- Ran `uv sync --all-extras` at worktree root before `just lint` — the worktree's `.venv` was freshly created by the earlier `uv run` and lacked `ruff`/`basedpyright` dev tools; this is environment setup, not a design choice, so it isn't a deviation from the plan's exact file contents.
- Plan Step 4 says "Expected: PASS (9 tests)" but the exact test file given in Step 1 contains 7 test methods (5 in `TestSafeMean`, 1 in `TestBuildLlm`, 1 in `TestBuildEmbeddings`). Copied the plan's test file verbatim per instructions; the "9" appears to be a stale count in the plan doc and does not affect correctness — all 7 defined tests pass.

### Lint Output

PASS

### Test Output

PASS (7 passed, 7 new)

### Commit

`2c4aae9`

### Outcome: success
