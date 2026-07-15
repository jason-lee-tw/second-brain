# Evaluation Harness

An offline evaluation harness of five flat CLI scripts under `apps/eval/` that generates a synthetic Q&A dataset, scores the full RAG pipeline against a no-RAG baseline with RAGAS metrics, and produces a markdown report proving RAG measurably beats baseline on `context_recall` and `faithfulness` (AC-9).

## Key Concepts

- **Goal (AC-9):** generate a synthetic Q&A dataset from ingested documents, run RAGAS metrics on the full RAG pipeline vs. a no-RAG baseline, and produce a markdown report proving RAG measurably beats baseline on `context_recall` and `faithfulness`.
- **Architecture:** five standalone flat CLI scripts under `apps/eval/` (existing workspace member, no `eval/` subdirectory nesting) — `generate_dataset.py`, `baseline.py`, `run_eval.py`, `compare.py`, and a shared `schema.py`. Scripts are independent pipelines, not a single orchestrated app. A shared `ragas_client.py` module was added later to centralize RAGAS setup (see below).
- **Tech stack:** Python 3.13, `anthropic` SDK, `ragas==0.4.3` (pinned `>=0.2.0,<0.5`), `langchain-ollama` (`OllamaEmbeddings`), `psycopg[binary]` v3 (sync, not asyncpg), `httpx`, `pytest`. LLM-as-judge tier is `claude-sonnet-4-6`; embeddings are `qwen3-embedding:0.6b` served via Ollama at `localhost:11434`, producing 1024-dimensional vectors — the same model used for RAG retrieval elsewhere in the project.
- **RAGAS metrics used:** `context_recall`, `context_precision`, `faithfulness`, `answer_relevancy` — the full RAG pipeline is scored on all four; the no-RAG baseline only supports `faithfulness` and `answer_relevancy` (no retrieval step exists to evaluate `context_recall`/`context_precision` against).
- **`schema.py` — `QAPair` contract:** a `TypedDict` with required fields `id` (UUID string), `question`, `expected_answer`, `source_document`, `source_chunk_ids` (list[str]), `difficulty` (`Literal["easy","medium","hard"]`). `validate_qa_pair(pair) -> list[str]` returns validation error strings (empty = valid); `validate_dataset(pairs) -> None` raises `ValueError` naming the failing index on the first invalid pair.
- **`generate_dataset.py`:** queries pgvector (`ingested_documents` joined to `document_chunks`, filtered `status = 'processed'`), groups chunks per document into `full_content`, and calls Claude (`claude-sonnet-4-6`) per document to produce question/answer/difficulty JSON grounded in the content. Writes raw pairs to `dataset/raw_qa_pairs.json`; a **manual curation step** trims to 30-50 pairs saved as `dataset/qa_pairs.json` (the curated file is tracked in git, the raw one is not).
- **`baseline.py`:** calls Claude directly per question with a generic "answer from general knowledge" system prompt and no retrieval context, then scores results with only `Faithfulness` and `AnswerRelevancy`, using `expected_answer` as a marked (`# ponytail:`) proxy for `retrieved_contexts` since there's no real retrieval in the baseline.
- **`run_eval.py`:** calls the real `/query` backend endpoint per question, embeds the question via `OllamaEmbeddings`, fetches the top-k (`k=5`) chunks from pgvector by cosine distance (`<=>`), and scores all four RAGAS metrics against the real retrieved contexts.
- **`compare.py`:** a pure function, `build_report(baseline_metrics, rag_metrics)`, builds a markdown table (Metric / No-RAG Baseline / RAG Pipeline / Delta) over the fixed metric list; missing baseline values render `N/A`, positive deltas are `+`-prefixed to 4 decimal places. Reads `results/baseline.json` and `results/rag.json`, writes `results/<date>-eval-report.md`.
- **Testing approach:** strict TDD; all external calls (Claude API, httpx, psycopg, OllamaEmbeddings, RAGAS scoring) are mocked via `unittest.mock.patch` on flat module-qualified names (scripts live flat under `apps/eval/`). `test_smoke.py` exercises the full pipeline against a fixed 3-pair fixture and directly asserts the AC-9 proxy — RAG `faithfulness`/`answer_relevancy` exceeding baseline by expected deltas.
- **Full real-data execution workflow** (manual): set `DATABASE_URL`, `ANTHROPIC_API_KEY`, `BACKEND_URL`, `OLLAMA_URL`, then run in order — `generate_dataset.py` → manual curation of `dataset/qa_pairs.json` → `baseline.py` → `run_eval.py` → `compare.py`.
- **RAGAS scoring internals were later migrated** off the deprecated `evaluate()`/`EvaluationDataset`/`SingleTurnSample`/`LangchainLLMWrapper` API (used in the original implementation above) onto `ragas.metrics.collections` classes scored via a hand-written async loop in a shared `ragas_client.py` module (`build_llm()`, `build_embeddings()`, `score_or_nan()`, `safe_mean()`). The migration also fixed a runtime crash where `AnswerRelevancy` silently required an OpenAI embeddings key because no embeddings client was passed explicitly — now resolved by wiring `qwen3-embedding:0.6b` (via Ollama's OpenAI-compatible endpoint) as the RAGAS judge's embeddings client. `compute_baseline_metrics(results) -> dict` and `compute_rag_metrics(results) -> dict` keep the same public signatures across this migration. Full detail: [[ragas-collections-migration]].

## Sources

- Offline Evaluation Harness Implementation Plan — `docs/superpowers/plans/2026-06-16-ticket-6-evaluation.md`
- Eval RAGAS Collections Migration Design — `docs/superpowers/specs/2026-07-01-eval-ragas-collections-migration-design.md`
- Tech Stack — `docs/codebase/001-tech-stack.md`

## Related Topics

- [[ragas-collections-migration]]
- [[pgvector-embeddings]]
- [[tech-stack]]
- [[query-workflow]]
- [[database-schema]]
- [[dependency-management]]
- [[capstone-requirements]]
- [[implementation-plan]]
- [[multi-agent-architecture]]
- [[second-brain-architecture]]
- [[second-brain-requirements]]
- [[uv-workspace-restructure]]
