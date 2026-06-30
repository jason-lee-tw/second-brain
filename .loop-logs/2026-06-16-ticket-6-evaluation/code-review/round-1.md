# Code Review — Round 1

**Timestamp:** 2026-06-30T14:00:00Z
**Loop iteration:** 1 of ≤5

## Raw findings

### Reviewer A — enhanced-review

1. apps/eval/pyproject.toml:5 — BLOCKING — missing direct deps (anthropic, langchain-anthropic, httpx, pandas)
2. apps/eval/run_eval.py:24 — BLOCKING — _BACKEND_URL defaults to port 8000, but backend is on 3001
3. apps/eval/generate_dataset.py:30-37 — IMPORTANT — _strip_code_fences corrupts output when LLM appends trailing text after closing fence
4. apps/eval/generate_dataset.py:51-62 — IMPORTANT — crash with TypeError when LLM returns JSON object instead of array
5. apps/eval/generate_dataset.py:103-115 — IMPORTANT — no incremental save; crash loses all pairs
6. apps/eval/generate_dataset.py:15 and run_eval.py:25 — IMPORTANT — DB URL regex corrupts passwords containing +
7. apps/eval/baseline.py:51-73 — IMPORTANT — baseline Faithfulness semantically incomparable to RAG Faithfulness
8. apps/eval/run_eval.py:91-121 — IMPORTANT — NaN metrics produce invalid JSON
9. schema.py:52-53 — MINOR — source_chunk_ids validates list type only, not element types
10. run_eval.py:43-45 — MINOR — OllamaEmbeddings re-instantiated per call

### Reviewer B — ponytail-review

1. _mock_ragas_result defined identically in 3 test files — IMPORTANT
2. Duplicate identical smoke test method — IMPORTANT
3. VALID_DIFFICULTIES duplicates Literal type — IMPORTANT
4. json.dumps(embedding) vs manual join — MINOR
5. Duplicate mock Claude client factories — MINOR
6. REQUIRED_FIELDS module-level vs inline — MINOR
7. parametrize easy/medium/hard tests — MINOR
8. try/finally conn.close() vs context manager — MINOR
9. OllamaEmbeddings per-call — MINOR
10. verbose type annotation in compare.py — MINOR

### Reviewer C — simplify

1. _mock_ragas_result duplicated 3x — IMPORTANT (same as B#1)
2. Mock Claude client duplicated — IMPORTANT (same as B#5)
3. OllamaEmbeddings re-instantiated per call — IMPORTANT (same as A#10)
4. compute_*_metrics share 80% body — IMPORTANT
5. _DB_URL regex copy-pasted — IMPORTANT (same as A#6)
6. Model string hardcoded 4 places — IMPORTANT
7. main() load/save boilerplate duplicated — MINOR
8. compare.py sign formatting — MINOR
9. test_compare.py no-arg instance methods — MINOR

## Consolidated issues

| ID    | Severity  | Summary                                                                               | Evidence                                              |
|-------|-----------|---------------------------------------------------------------------------------------|-------------------------------------------------------|
| I-001 | blocking  | anthropic, langchain-anthropic, httpx, pandas not declared as direct deps              | apps/eval/pyproject.toml:5-10                         |
| I-002 | blocking  | _BACKEND_URL defaults to port 8000, backend documented on port 3001                   | apps/eval/run_eval.py:24                              |
| I-003 | important | _strip_code_fences corrupts output when LLM appends prose after closing fence          | apps/eval/generate_dataset.py:35                      |
| I-004 | important | crashes TypeError when LLM returns JSON object instead of array                        | apps/eval/generate_dataset.py:51-62                   |
| I-005 | important | no incremental save; crash loses all previously generated pairs                        | apps/eval/generate_dataset.py:103-115                 |
| I-006 | important | DB URL regex corrupts passwords containing + char                                      | apps/eval/generate_dataset.py:15; run_eval.py:25      |
| I-007 | important | baseline Faithfulness uses expected_answer as context proxy; incomparable to RAG       | apps/eval/baseline.py:51-73                           |
| I-008 | important | NaN metrics produce bare NaN in JSON output (invalid RFC 8259)                         | apps/eval/run_eval.py:116-121; baseline.py:69-73      |
| I-009 | minor     | _mock_ragas_result duplicated in 3 test files                                          | test_baseline.py:31; test_run_eval.py:27; test_smoke.py:110 |
| I-010 | minor     | duplicate identical smoke test method                                                  | test_smoke.py:217-242                                 |
| I-011 | minor     | VALID_DIFFICULTIES duplicates Literal type annotation                                  | schema.py:4 and :21                                   |
| I-012 | minor     | source_chunk_ids validates list type only, not element types                           | schema.py:52-53                                       |
| I-013 | minor     | OllamaEmbeddings instantiated fresh per embed_query call                               | run_eval.py:44                                        |
| I-014 | minor     | try/finally conn.close() reinvents context manager                                     | generate_dataset.py:93-97                             |
| I-015 | minor     | compute_*_metrics share ~80% body; extract _run_ragas helper                           | baseline.py:45-73; run_eval.py:91-121                 |
| I-016 | minor     | model string hardcoded in 4 places                                                     | generate_dataset.py:46; baseline.py:30,:63; run_eval.py:104 |
| I-017 | minor     | manual embedding vector serialization reinvents json.dumps                             | run_eval.py:50                                        |
| I-018 | minor     | mock Claude client factory duplicated in test_baseline.py and test_smoke.py            | test_baseline.py:38; test_smoke.py:84                 |
| I-019 | minor     | three separate easy/medium/hard tests; use parametrize                                 | test_schema.py:58-65                                  |
| I-020 | minor     | no-arg instance methods in test_compare.py                                             | test_compare.py:7-16                                  |

## Disposition

- Actionable (blocking + important) — to fix this iteration: I-001, I-002, I-003, I-004, I-005, I-006, I-007, I-008
- Deferred (minor — NOT handled yet): I-009, I-010, I-011, I-012, I-013, I-014, I-015, I-016, I-017, I-018, I-019, I-020
