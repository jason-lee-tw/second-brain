# Offline Evaluation Harness Implementation Plan

Source: docs/superpowers/plans/2026-06-16-ticket-6-evaluation.md
Primary-Topic: evaluation-harness
Secondary-Topics: ragas-metrics, pgvector-retrieval

## Key Concepts

- **Goal (AC-9):** Build an offline evaluation harness that generates a synthetic Q&A dataset from ingested documents, runs RAGAS metrics on the full RAG pipeline vs a no-RAG baseline, and produces a markdown report proving RAG measurably beats baseline on `context_recall` and `faithfulness`.
- **Architecture:** Five standalone flat CLI scripts under `apps/eval/` (existing workspace member, no `eval/` subdirectory nesting): `generate_dataset.py`, `baseline.py`, `run_eval.py`, `compare.py`, and a shared `schema.py`. Scripts are independent pipelines, not a single orchestrated app.
- **Tech stack:** Python 3.12+, `anthropic` SDK, `ragas==0.4.3` (0.4.x API — pinned range `>=0.2.0,<0.5` since ragas 0.4.x needs the langchain 0.x ecosystem), `langchain-anthropic`, `langchain-ollama` (`OllamaEmbeddings`), `psycopg[binary]` v3 (sync, not asyncpg), `httpx`, `pytest`.
- **Key RAGAS 0.4.x API decisions** (also recorded separately in `.claude/temp/2026-06-30-ticket-6-eval-grilling-decisions.md`):
  - Use `EvaluationDataset` + `SingleTurnSample(user_input, response, retrieved_contexts, reference)`.
  - Metrics are class instances, not functions: `Faithfulness(llm=...)`, `AnswerRelevancy(llm=...)`, `ContextRecall(llm=...)`, `ContextPrecision(llm=...)`.
  - Scores extracted via `result.to_pandas().mean()`, then `round(float(...), 4)`.
  - LLM wrapper: `LangchainLLMWrapper(ChatAnthropic(model="claude-sonnet-4-6", ...))`.
  - If `AnswerRelevancy` raises an embeddings error, pass embeddings explicitly: `AnswerRelevancy(llm=llm, embeddings=LangchainEmbeddingsWrapper(OllamaEmbeddings(model="qwen3-embedding:0.6b")))`.
- **psycopg v3 usage:** `psycopg.connect()` (sync) with `row_factory=dict_row`; `DATABASE_URL` from `.env` uses SQLAlchemy-style `postgresql+psycopg2://...` and must have the `+<driver>` suffix stripped via regex (`re.sub(r"\+[^:/]+", "", ...)`) before use — a plain `postgresql://` URL also works directly.
- **Ollama embeddings:** `langchain_ollama.OllamaEmbeddings(model="qwen3-embedding:0.6b", base_url=...)` used to embed evaluation questions for pgvector retrieval (`embed_query`).
- **`schema.py` — `QAPair` contract:** `TypedDict` with required fields `id` (UUID string), `question`, `expected_answer`, `source_document`, `source_chunk_ids` (list[str]), `difficulty` (`Literal["easy","medium","hard"]`). `validate_qa_pair(pair) -> list[str]` returns validation error strings (empty = valid); checks missing fields, UUID format, non-empty strings, list type for `source_chunk_ids`, and difficulty enum membership. `validate_dataset(pairs) -> None` raises `ValueError` naming the failing index (e.g. "index 1") on the first invalid pair; empty dataset is valid.
- **`generate_dataset.py` — synthetic dataset generation:**
  - Queries pgvector (`ingested_documents` joined to `document_chunks`, filtered `status = 'processed'`) grouping chunks per document into `full_content` via `string_agg` ordered by `chunk_index`.
  - Calls Claude (`claude-sonnet-4-6`) per document with a prompt asking for N question/answer/difficulty JSON objects grounded in the document content (content truncated to first 8000 chars).
  - `_strip_code_fences(text)` strips leading/trailing ```` ``` ```` or ` ```json ` fences before `json.loads`.
  - `generate_qa_pairs_for_document(client, doc, n)` returns a list of QAPair dicts with fresh `uuid4()` ids, `source_document = doc["filename"]`, `source_chunk_ids = doc["chunk_ids"]`, and `difficulty` defaulting to `"medium"` when the model omits it.
  - CLI writes raw pairs to `dataset/raw_qa_pairs.json`; workflow expects a **manual curation step** afterward (review + trim to 30-50 pairs) saved as `dataset/qa_pairs.json`. `dataset/.gitignore` ignores `raw_qa_pairs.json` but allows the curated `qa_pairs.json`.
- **`baseline.py` — no-RAG baseline runner:**
  - `run_baseline(qa_pairs, client)`: calls Claude directly per question with a generic system prompt ("answer from general knowledge", no retrieval context); returns dicts with `question`, `generated_answer`, `expected_answer` — deliberately **no** `retrieved_contexts` key.
  - `compute_baseline_metrics(results)`: runs only `Faithfulness` and `AnswerRelevancy` via RAGAS, using `expected_answer` as a proxy `retrieved_contexts` value (marked `# ponytail:` comment as a deliberate shortcut) since there's no real retrieval to evaluate against. Returns dict with exactly `faithfulness`, `answer_relevancy` — explicitly must NOT contain `context_recall`/`context_precision` since there's no retrieval step in the baseline.
  - CLI: `--dataset`, `--output`, `--skip-metrics` flag; validates dataset via `schema.validate_dataset` before running; writes `{"metrics": {...}, "results": [...]}` JSON.
- **`run_eval.py` — full RAG pipeline evaluator:**
  - `call_query_endpoint(question, backend_url)`: POSTs `{"message": question, "sessionId": None}` to `{backend_url}/query`, raises on HTTP error, returns `response.json()["answer"]`.
  - `embed_query(question, ollama_url)`: embeds via `OllamaEmbeddings`.
  - `fetch_top_k_chunks(conn, embedding, k=5)`: runs pgvector cosine-distance (`<=>`) ORDER BY / LIMIT query against `document_chunks`, returns list of `content` strings (embedding serialized as a `"[v1,v2,...]"` string literal cast `::vector`).
  - `run_rag_eval(qa_pairs, conn, backend_url, ollama_url)`: for each pair, calls the real `/query` endpoint, embeds the question, fetches top-k chunks, and returns dicts with `question`, `generated_answer`, `expected_answer`, and `retrieved_contexts` (this is the key structural difference from the baseline results).
  - `compute_rag_metrics(results)`: runs all four RAGAS metrics — `ContextRecall`, `ContextPrecision`, `Faithfulness`, `AnswerRelevancy` — against real retrieved contexts, returns all four as a dict.
  - Env vars: `DATABASE_URL` (driver-stripped), `BACKEND_URL` (default `http://localhost:8000`), `OLLAMA_URL` (default `http://localhost:11434`), embedding model `qwen3-embedding:0.6b`, `_TOP_K = 5`.
- **`compare.py` — comparison report generator:**
  - `build_report(baseline_metrics, rag_metrics)` builds a pure-function markdown report: a table with columns Metric / No-RAG Baseline / RAG Pipeline / Delta, over the fixed metric list `context_recall, context_precision, faithfulness, answer_relevancy`.
  - Missing metric value (e.g. baseline has no `context_recall`) renders as `N/A`; when only the RAG value exists, delta = `+<rag_value>` (full value, since baseline is absent, not "N/A vs N/A").
  - Positive deltas prefixed with `+`, formatted to 4 decimal places (e.g. `+0.2800`); negative deltas keep the `-` sign.
  - Report includes an H1 heading with today's ISO date (`date.today().isoformat()`).
  - CLI reads `results/baseline.json` and `results/rag.json` `"metrics"` keys, writes report to `results/<date>-eval-report.md`.
- **Testing approach:** Strict TDD per task — write failing tests first (module doesn't exist yet → `ModuleNotFoundError`), then implement. All external calls (Claude API, httpx, psycopg, OllamaEmbeddings, RAGAS `evaluate`) are mocked in unit tests via `unittest.mock.patch` on the module-qualified name (e.g. `baseline.evaluate`, `run_eval.ChatAnthropic`) — flat module names because scripts live flat under `apps/eval/`, not nested under an `eval/` package.
- **End-to-end smoke test (`test_smoke.py`):** Exercises the full pipeline (schema validation → baseline → RAG eval → compare) against a fixed 3-pair fixture dataset with fully mocked external calls; directly asserts the AC-9 proxy — RAG `faithfulness` (0.89) and `answer_relevancy` (0.85) both exceed baseline (0.61 / 0.72) by the expected deltas (`+0.2800`, `+0.1300`).
- **Full real-data execution workflow** (manual, requires running backend + Postgres + ingested data from Ticket 3/4): set `DATABASE_URL`, `ANTHROPIC_API_KEY`, `BACKEND_URL`, `OLLAMA_URL` env vars, then run in order: `generate_dataset.py` → manual curation of `dataset/qa_pairs.json` → `baseline.py` → `run_eval.py` → `compare.py`.
- **Repo-wide scaffolding changes:** `apps/eval/pyproject.toml` deps updated (`ragas`, `langchain-ollama`, `psycopg[binary]`, `second-brain` workspace dep; `pytest` dev group; `[tool.uv] package = false`); `apps/eval/pytest.ini` with `pythonpath = .` and `testpaths = tests/unit`; `pyrightconfig.json` `extraPaths` gains `"apps/eval"`; `Justfile` gains a `test-eval` recipe (`uv run --directory apps/eval pytest tests/unit`); `apps/eval/results/.gitkeep` keeps the results directory tracked in git.
- **Self-review checklist confirms:** flat layout (no `eval/` subdirectory), full RAGAS 0.4.x API usage throughout, psycopg v3 sync pattern, langchain-ollama for embeddings, all config wiring done, mocks use module-flat patch targets and `to_pandas.return_value = pd.DataFrame([scores])` pattern, and AC-9 is verified via the smoke test suite (~43 tests across all modules expected to pass).
