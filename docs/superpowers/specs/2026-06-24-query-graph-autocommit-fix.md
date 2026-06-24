# Spec: Fix AsyncConnectionPool autocommit for LangGraph checkpointer

**Date:** 2026-06-24  
**Status:** Approved  
**Related bug:** `docs/bugs/2026-06-24-query-graph-autocommit.md`

---

## Problem

`POST /query` returns 500 on every call because `AsyncPostgresSaver.setup()` runs
`CREATE INDEX CONCURRENTLY` inside a psycopg3 implicit transaction block.

## Change

`AsyncConnectionPool` in `query_graph.py` must be constructed with `autocommit=True` so
that LangGraph's checkpoint schema migrations run outside any transaction block.

## Acceptance Criteria

| #    | Criterion                                                                                                                 |
| ---- | ------------------------------------------------------------------------------------------------------------------------- |
| AC-1 | `POST /query {"message": "hello"}` returns HTTP 200 (not 500) against a fresh database                                    |
| AC-2 | `POST /query` response contains `answer`, `sessionId`, `confidence`, `isUncertain`, `conflictDetected`, `conflictContext` |
| AC-3 | Calling `POST /query` a second time with the returned `sessionId` returns HTTP 200 (session continuity still works)       |
| AC-4 | `just format`, `just lint`, `just type-check`, and `just test-unit` all pass with no errors                              |

## Scope

**One line change** in `apps/backend/src/second_brain/graphs/query_graph.py`.

No schema changes. No new dependencies. No API contract changes.

## Out of Scope

- Memory agent, conflict detection, fact persistence (Ticket 5)
- RAGAS evaluation
- Implementation plan document update (separate chore)
