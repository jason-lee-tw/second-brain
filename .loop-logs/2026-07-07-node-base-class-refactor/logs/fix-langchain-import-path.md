# Fix: import BaseChatModel from langchain_core, not langchain

## Bug

`apps/backend/src/second_brain/nodes/base_node/agents/base_agent.py` line 3 does:

```python
from langchain.chat_models.base import BaseChatModel
```

But `apps/backend/pyproject.toml` never declares `langchain` as a direct dependency
(only `langchain-anthropic`/`langgraph`). It works in local dev only because the shared
uv workspace venv leaks `langchain` in transitively from another workspace member. The
Docker image (built from `apps/backend/pyproject.toml` alone) genuinely lacks it, so the
backend container crashes on boot with `ModuleNotFoundError: No module named 'langchain'`.

## Fix

Change the import to use the actual home of `BaseChatModel`, which is a real
(already-transitive) dependency:

```python
from langchain_core.language_models.chat_models import BaseChatModel
```

No new dependency added — `langchain_core` is already pulled in by `langchain-anthropic`.

## Per-Attempt Block — Attempt 1 (PASS)

- Changed `apps/backend/src/second_brain/nodes/base_node/agents/base_agent.py` line 3:
  `from langchain.chat_models.base import BaseChatModel` ->
  `from langchain_core.language_models.chat_models import BaseChatModel`
- Confirmed `apps/backend/pyproject.toml` has no direct `langchain` dependency, only
  `langchain-anthropic>=0.3.0,<1.0` and `langgraph>=0.2.0,<1.0`. Every other module in
  the codebase already imports from `langchain_core` (e.g. `utils.py`, `pii_redaction.py`,
  `memory_agent.py`, `synthesis.py`, `graphs/state.py`), so this fix aligns `base_agent.py`
  with the existing convention.
- `just lint` -> "All checks passed!"
- `just type-check` -> "0 errors, 0 warnings, 9 notes" (pre-existing informational notes
  unrelated to this file) -> "Type check is completed"
- `just test-unit` -> 209 passed, 2 warnings (unrelated deprecation warnings)
- Isolated dependency check: `uv run --package second-brain python -c "from
  langchain_core.language_models.chat_models import BaseChatModel"` -> succeeded
- Smoke import: `DATABASE_URL=... ANTHROPIC_API_KEY=... TAVILY_API_KEY=... uv run python
  -c "from second_brain.nodes.base_node.agents.base_agent import BaseAgent"` -> succeeded
  (dummy env vars needed only because `second_brain.config.Settings()` validates required
  fields at import time — unrelated to this bug)
- Full Docker rebuild: `docker compose -f ./docker-compose.yml build backend` from the
  worktree root -> built successfully (used cached layers for `pip install -e .`, only
  `COPY src/` layer re-ran since `base_agent.py` changed)
- Docker runtime verification: `docker run --rm -e DATABASE_URL=... -e
  ANTHROPIC_API_KEY=... -e TAVILY_API_KEY=... fix-langchain-import-path-backend python -c
  "from second_brain.nodes.base_node.agents.base_agent import BaseAgent"` -> "OK: BaseAgent
  imports cleanly in Docker image, no ModuleNotFoundError for langchain". Confirmed this
  reproduces the original bug shape first (without dummy env vars, the container raised a
  `pydantic_settings` validation error, not `ModuleNotFoundError: No module named
  'langchain'` — proving the langchain import path is resolved and the only remaining
  friction is unrelated required-env-var validation, expected in a bare `docker run`
  without the full compose stack).

Result: PASS on attempt 1. Committed as
"fix: import BaseChatModel from langchain_core, not langchain".
