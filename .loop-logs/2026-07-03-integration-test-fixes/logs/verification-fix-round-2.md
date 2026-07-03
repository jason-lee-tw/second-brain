# Verification Fix — Round 2

**Timestamp:** 2026-07-03T07:05:00Z
**Trigger:** Post-code-review-fix verify (fixing R1-1 in `memory_retrieval.py` correctly
started enforcing `settings.memory_retrieval_threshold`, exposing a marginal test fixture)

## Root cause

`apps/backend/tests/integration/test_memory_system.py::test_full_memory_loop_persist_then_retrieve`
failed deterministically (2/2 runs, 19/20 pass overall). The retrieval-threshold
bind-param fix (commit `5b81b0d`) now correctly enforces
`settings.memory_retrieval_threshold=0.5`. The test's original fixture — fact
"The user is a professional cyclist." / query "What sports do I do?" — measured
a real cosine similarity of **0.4847** against the live `qwen3-embedding:0.6b`
model, just under the 0.5 threshold. It only ever passed because the SQL bug
made the threshold filter a no-op (any similarity > 0 passed).

## Fix

Replaced the fixture with fact "The user's favorite sport is cycling." / query
"What is the user's favorite sport?", empirically measured (via a throwaway,
non-committed script calling `second_brain.services.embeddings.embed_text`
against the live Ollama instance) at **0.7330** cosine similarity — comfortably
above threshold, while still exercising semantic (not exact-substring) retrieval
since the query never contains "cycling". Production
`settings.memory_retrieval_threshold` was left untouched.

## Verification

- Target test: PASS in isolation.
- `just test-integration`: 20/20 passed, twice in a row.
- `just lint`, `just format`: clean.
- `just test-unit`: 210 passed.

## Commit

`6fe1580` — `fix(test): use fact/query pair that clears similarity threshold`

## Outcome: success
