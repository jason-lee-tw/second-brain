# Task 7: Wire Memory Nodes into Query Graph

## Summary

Wired `memory_agent_node` and `memory_persistence_node` into `query_graph.py`, and renamed the existing `"retrieve_memory"` node key to `"memory_retrieval_node"` for consistency.

## Changes Made

**File:** `apps/backend/src/second_brain/graphs/query_graph.py`

1. Added imports for `memory_agent_node` (from `second_brain.nodes.memory_agent`) and `memory_persistence_node` (from `second_brain.nodes.memory_persistence`).
2. Renamed node registration from `"retrieve_memory"` → `"memory_retrieval_node"`.
3. Added node registrations for `"memory_agent"` and `"memory_persistence"`.
4. Updated edges `redact_inbound → retrieve_memory → orchestrator` to use `memory_retrieval_node`.
5. Replaced terminal edge `redact_outbound → END` with chain: `redact_outbound → memory_agent → memory_persistence → END`.

## New Graph Flow

```
redact_inbound → memory_retrieval_node → orchestrator → [rag_retrieval|web_research|synthesis] → synthesis → redact_outbound → memory_agent → memory_persistence → END
```

## Verification

- `just lint`: All checks passed
- `just test-unit`: 195 passed, 2 warnings
- Graph import verified (module resolution confirmed; settings validation error is expected without env vars)
