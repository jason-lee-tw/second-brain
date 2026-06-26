# Task 3: memory_retrieval_node

## Description

Replace the stub `retrieve_memory` function in `memory_retrieval.py` with a full implementation called `memory_retrieval_node`. Performs dual-table asyncpg cosine search on `learned_facts` + `model_corrections`, merges results sorted by similarity score descending.

## Interfaces

### Input

- `state: SecondBrainState` — uses `state["messages"]` to find the last `HumanMessage`

### Output

- `RetrieveMemoryOutput` — `{"retrieved_memory": list[MemoryItem]}`

### MemoryItem

```python
class MemoryItem(TypedDict):
    id: str
    fact: str
    confidence: float
    type: Literal["learned_fact", "model_correction"]
```

### SQL queries

- `learned_facts`: `SELECT id::text, fact, confidence, 1-(embedding<=>$1) AS score FROM learned_facts ORDER BY embedding<=>$1 ASC LIMIT 5`
- `model_corrections`: `SELECT id::text, correction AS fact, 1-(embedding<=>$1) AS score FROM model_corrections ORDER BY embedding<=>$1 ASC LIMIT 3`

## Status

- [ ] Worktree created
- [ ] Tests written
- [ ] Tests pass
- [ ] Lint pass
