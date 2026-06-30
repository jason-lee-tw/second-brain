# Code Review — Round 2

**Timestamp:** 2026-06-30T15:00:00Z
**Loop iteration:** 2 of ≤5

## Raw findings

### Reviewer A — enhanced-review

generate_dataset.py:123 — IMPORTANT — resume re-processes every document, producing duplicate Q&A pairs in the output dataset; fix: build already_processed set from loaded pairs and skip

### Reviewer B — ponytail

generate_dataset.py:116 — IMPORTANT — resume creates duplicates (same as A)
run_eval.py:45 — IMPORTANT — OllamaEmbeddings re-instantiated per question (was I-013 minor in round 1, now important with evidence)

## Consolidated issues

| ID    | Severity  | Summary                                                        | Evidence                      |
|-------|-----------|----------------------------------------------------------------|-------------------------------|
| R2-001 | important | Resume loads existing pairs but re-processes all docs, creating duplicates | generate_dataset.py:116-126 |
| R2-002 | important | OllamaEmbeddings instantiated fresh per embed_query call (N objects for N questions) | run_eval.py:44-46 |

## Disposition

- Actionable: R2-001, R2-002
- Deferred: none
