# Task 12: Full-repo verification pass

## Plan Section (verbatim)

### Task 12: Full-repo verification pass

**Files:** none (verification only).

**Interfaces:** none — this task confirms the whole refactor is coherent end-to-end.

- [ ] **Step 1: Confirm `query_graph.py` needed zero edits**

Run: `git diff main -- apps/backend/src/second_brain/graphs/query_graph.py`
Expected: no output — `query_graph.py` was never touched across Tasks 1–11, per the naming rule in the design spec.

- [ ] **Step 2: Full workspace verification**

Run: `just format lint type-check test-unit`
Expected: all green, no diffs from `format`.

- [ ] **Step 3: Integration verification (if not already confirmed in Task 11)**

Run: `just up-all && just test-integration`
Expected: all integration tests pass.

- [ ] **Step 4: Smoke-test the running system**

Run: `just up-all`, then:

```bash
curl -s -X POST localhost:3001/query -H 'Content-Type: application/json' -d '{"message": "Hello"}'
```

Expected: HTTP 200 with a JSON body containing `final_answer`/`confidence` — confirms `query_graph.py`'s unchanged `add_node` calls actually resolve to the new class instances at runtime (not just at import time in tests).

- [ ] **Step 5: Final commit (if any stray formatting fixes were needed)**

```bash
git status --short
```

If `just format` in Step 2 produced changes not yet committed, stage and commit them:

```bash
git add -u
git commit -m "chore: apply formatting fixes from full-repo verification pass"
```

If nothing changed, skip this step — there is nothing to commit.

## Attempt Log

Branch: `refactor/agent-pattern` (confirmed via `git branch --show-current`).
HEAD at start: `d6ea12d fix: update stale _structured_llm patch target in tests`.

### Step 1: `git diff main -- apps/backend/src/second_brain/graphs/query_graph.py`

Command:
```
git diff main -- apps/backend/src/second_brain/graphs/query_graph.py
```
Output: (empty)

**Result: PASS.** `query_graph.py` is untouched relative to `main`, as expected by the naming-rule design decision.

### Step 2: `just format lint type-check test-unit`

Command:
```
just format lint type-check test-unit
```

Summary of output:
- `format`: "110 files left unchanged" — no diffs produced.
- `lint`: "All checks passed!"
- `type-check`: "0 errors, 0 warnings, 9 notes" (notes are pre-existing `reportUnknownArgumentType` informational notes in `ingestion_agent.py`, `memory_persistence.py`, `memory_retrieval.py` — not errors/warnings, do not fail the gate).
- `test-unit`: `209 passed, 2 warnings in 1.35s` — all unit tests green.

Confirmed via `git status --short` immediately after: only `?? .loop-logs/` untracked (this task's own log directory), no tracked-file diffs from `format`.

**Result: PASS.**

### Step 3: `just up-all && just test-integration`

Command:
```
just up-all
```
(ran in background; this recipe runs `docker compose ... up --build` in the foreground, i.e. it does not detach)

Resulting container state (`docker compose ps` / `docker ps -a`):
- `ai-learning-milestone-app_postgres-1` — Up, healthy
- `ai-learning-milestone-phoenix_postgres-1` — Up, healthy
- `ai-learning-milestone-phoenix-1` — Up, healthy
- `ai-learning-milestone-db_migration-1` — Exited (0) — ran migrations successfully
- `ai-learning-milestone-ollama-checker-1` — Exited (0) — normal one-shot check
- **`ai-learning-milestone-backend-1` — Exited (1) — CRASHED on startup**

Backend container logs (`docker logs ai-learning-milestone-backend-1`) show a `ModuleNotFoundError` during app import:

```
Traceback (most recent call last):
  ...
  File "/app/src/second_brain/main.py", line 7, in <module>
    from second_brain.api.routers.ingest import router as ingest_router
  File "/app/src/second_brain/api/routers/ingest.py", line 8, in <module>
    from second_brain.graphs.ingestion_graph import ingestion_graph
  File "/app/src/second_brain/graphs/ingestion_graph.py", line 5, in <module>
    from second_brain.nodes.ingestion_agent import ingestion_agent_node
  File "/app/src/second_brain/nodes/ingestion_agent.py", line 14, in <module>
    from second_brain.nodes.base_node import BaseAgentNode
  File "/app/src/second_brain/nodes/base_node/__init__.py", line 1, in <module>
    from .base_agent_node import BaseAgentNode
  File "/app/src/second_brain/nodes/base_node/base_agent_node.py", line 4, in <module>
    from .agents import BaseAgent
  File "/app/src/second_brain/nodes/base_node/agents/__init__.py", line 1, in <module>
    from .base_agent import BaseAgent
  File "/app/src/second_brain/nodes/base_node/agents/base_agent.py", line 3, in <module>
    from langchain.chat_models.base import BaseChatModel
ModuleNotFoundError: No module named 'langchain'
```

**Result: FAIL.** Backend container cannot even boot in the Docker image. See ERROR_LOG for root-cause analysis. Ran `just test-integration` anyway (against the local pytest env, not the crashed container) to collect maximal evidence for the error log — see below; it also fails independently, for a different reason.

Command:
```
just test-integration
```
Output summary: `3 failed, 17 passed, 1 warning in 2.98s`. Failures:
- `test_ac5_pii_redacted_before_llm_sees_message`
- `test_ac6_pii_redacted_in_final_answer`
- `test_ac10_null_session_id_creates_new_thread_uuid_continues`

All three fail identically with:
```
AttributeError: <module 'second_brain.nodes.orchestrator' ...> does not have the attribute '_structured_llm'
```
raised from `patch("second_brain.nodes.orchestrator._structured_llm")` in `apps/backend/tests/integration/test_query_graph.py`.

**Result: FAIL.** See ERROR_LOG for root-cause analysis (this is a second, independent bug from the Docker one).

### Step 4: Smoke test

Command:
```
curl -s -w '\nHTTP_STATUS:%{http_code}\n' -X POST localhost:3001/query -H 'Content-Type: application/json' -d '{"message": "Hello"}' --max-time 10
```
Output: `curl: (7) Failed to connect to localhost port 3001` (`HTTP_STATUS:000`).

**Result: FAIL** (expected, given the backend container never came up — Step 3's crash is the root cause).

### Step 5: Final commit

`git status --short` showed no tracked-file changes from `format` (only the untracked `.loop-logs/` directory belonging to this pipeline, not part of the refactor). **Skipped — nothing to commit.**

## Overall Outcome

Steps 1 and 2 PASS. Steps 3 and 4 FAIL. This is a verification-only task — per instructions, no fix was attempted. Full root-cause details in the accompanying ERROR_LOG.

Docker Compose services were left in their current state (backend exited, db/phoenix still running) — see final report for explicit instruction on what's running.

## Re-verification attempt 2

Branch: `refactor/agent-pattern` (confirmed via `git branch --show-current`).
HEAD at start: `47c151a fix: update stale LLM patch targets in integration test` — this attempt
runs after all three hotfixes (stale synthesis_awaiting patch target, langchain import path, stale
integration test patch targets) were squash-merged on top of the attempt-1 HEAD.

### Step 1: `git diff main -- apps/backend/src/second_brain/graphs/query_graph.py`

Output: (empty). **Result: PASS.** Unchanged from attempt 1.

### Step 2: `just format lint type-check test-unit`

- `format`: "110 files left unchanged" — no diffs produced.
- `lint`: "All checks passed!"
- `type-check`: "0 errors, 0 warnings, 9 notes" (same pre-existing informational
  `reportUnknownArgumentType` notes in `ingestion_agent.py`, `memory_persistence.py`,
  `memory_retrieval.py` as attempt 1 — not errors/warnings).
- `test-unit`: `209 passed, 2 warnings in 1.70s` — all unit tests green.

`git status --short` after: only untracked `.loop-logs/` — no tracked-file diffs from `format`.

**Result: PASS.**

### Step 3: `just up-all` then `just test-integration`

`docker compose ps` showed all four services `Up ... (healthy)` (or just `Up` for backend, which
has no healthcheck configured): `app_postgres`, `backend`, `phoenix`, `phoenix_postgres`. Backend
container logs show a clean boot — `Application startup complete`, `Uvicorn running on
http://0.0.0.0:8000` — confirming the langchain-import crash-loop from attempt 1 is fixed.

```
just test-integration
```
Output: `20 passed, 1 warning in 2.88s` — includes all 3 previously-failing
`test_query_graph.py` tests (`test_ac5_pii_redacted_before_llm_sees_message`,
`test_ac6_pii_redacted_in_final_answer`, `test_ac10_null_session_id_creates_new_thread_uuid_continues`).

**Result: PASS.** Both attempt-1 bugs (Docker crash-loop, stale `_structured_llm` patch targets)
are confirmed fixed.

### Step 4: Smoke test

Command:
```
curl -s -w '\nHTTP_STATUS:%{http_code}\n' -X POST localhost:3001/query -H 'Content-Type: application/json' -d '{"message": "Hello"}'
```
Output: `Internal Server Error` / `HTTP_STATUS:500`.

**Result: FAIL — NEW bug, independent of the two fixed in attempt 1.** This is the first time the
smoke test has reached a live LLM call (attempt 1 never got past Step 3's Docker crash), so this
bug was latent and unobserved until now. See ERROR_LOG for root-cause analysis
(`anthropic.BadRequestError: temperature is deprecated for this model`, raised from
`ClaudeAgent.__init__` in `apps/backend/src/second_brain/nodes/base_node/agents/claude_agent.py`).

### Step 5: Final commit

`git status --short` showed no tracked-file changes from `format` (only untracked `.loop-logs/`).
**Skipped — nothing to commit.**

## Overall Outcome (attempt 2)

Steps 1, 2, 3 PASS — both attempt-1 bugs confirmed fixed. Step 4 FAILS on a new, previously-latent
bug: the `ClaudeAgent` base class unconditionally passes `temperature=0.7` to `ChatAnthropic`, but
the configured model (`CLAUDE_MODEL_NAME.SONNET = "claude-sonnet-5"`) rejects the `temperature`
parameter entirely (HTTP 400 from the Anthropic API). This is a verification-only task — per
instructions, no fix was attempted. Full details in the accompanying ERROR_LOG.

Docker Compose services left running (`app_postgres`, `backend`, `phoenix`, `phoenix_postgres` all
up) for the next agent to reproduce/fix against.

## Re-verification attempt 3

Branch `refactor/agent-pattern`, HEAD `b31f288` (temperature fix merged in). Backend image rebuilt from scratch to pick up the fix (old running container was stale).

1. **Rebuild + restart**: `docker compose --env-file ./apps/backend/.env -f ./docker-compose.yml build backend` — built clean (COPY src/ layer re-executed, deps cached). Then `just down-all` followed by `just up-all` for a full clean restart of all services (ollama, app_postgres, phoenix_postgres, phoenix, db_migration, backend). All containers came up healthy; backend logged `INFO: Application startup complete. Uvicorn running on http://0.0.0.0:8000`.
2. **`just format`**: `111 files left unchanged` — no diff.
3. **`just lint`**: `All checks passed!`
4. **`just type-check`**: `0 errors, 0 warnings, 9 notes` (informational reportUnknownArgumentType notes only, pre-existing/unrelated) — `✅ Type check is completed`.
5. **`just test-unit`**: `212 passed, 2 warnings in 1.34s` (warnings are pre-existing deprecation notices from langgraph/starlette, unrelated to this change).
6. **`just test-integration`**: `20 passed, 1 warning in 2.91s` — no regression from attempt 2.
7. **Smoke test** (the critical check):
   ```
   curl -s -w '\nHTTP_STATUS:%{http_code}\n' -X POST localhost:3001/query -H 'Content-Type: application/json' -d '{"message": "Hello"}'
   ```
   Result: `HTTP_STATUS:200` with body:
   ```json
   {"answer":"Hello! 👋 I'm your Second Brain assistant. I don't have any prior context or notes loaded for this conversation yet, but I'm ready to help once you share a question, task, or some information for me to work with. What would you like to explore or do [DATE]?","sessionId":"019f3fe8-80e8-73bf-804b-b21d164b5969","confidence":1.0,"isUncertain":false,"conflictDetected":false,"conflictContext":[],"retrievedContexts":[]}
   ```
   Backend logs for this request show no errors/tracebacks/HTTP 400s. The ClaudeAgent temperature fix (commit b31f288) is confirmed working end-to-end against the live Anthropic API with a real Claude Sonnet call.
8. **`git status --short`**: only `?? .loop-logs/` (untracked, unrelated to this task) — no format-produced diff to commit.

**Verdict: all steps pass. Full-repo verification is complete — no 4th bug found.** Services left running (see final report).
