# Second Brain — Offline Evaluation Harness

Measures RAG improvement over a no-RAG baseline using [RAGAS](https://docs.ragas.io/) 0.4.x metrics.

## Offine unit test

```bash
# Offline unit tests (no infra required)
just test-eval
```

## Five-step evaluation pipeline

### Pre-requisite

For a full live evaluation you need the stack running (`just up-all`) and an env file:

```bash
cp apps/eval/.env.template apps/eval/.env
# fill in ANTHROPIC_API_KEY (and adjust other values if needed)
```

The `just eval-*` recipes load `apps/eval/.env` automatically when it exists. You can also export the vars manually:

```bash
export DATABASE_URL="postgresql://second_brain:secret@localhost:5432/second_brain"
export ANTHROPIC_API_KEY="sk-ant-..."
export BACKEND_URL="http://localhost:3001"
export OLLAMA_URL="http://localhost:11434"
```

### Step 1 — Generate raw Q&A pairs

Queries pgvector for ingested document chunks and uses Claude to generate question–answer pairs.

```bash
just eval-generate                        # 7 pairs per doc → apps/eval/dataset/raw_qa_pairs.json
just eval-generate n_per_doc=10           # override pairs per doc
```

### Step 2 — Curate the dataset (manual)

Review `apps/eval/dataset/raw_qa_pairs.json`. Keep 30–50 high-quality pairs and save them to `apps/eval/dataset/qa_pairs.json`. This file is the input for Steps 3–4.

### Step 3 — Run the no-RAG baseline

Answers every question using Claude with no retrieval. Measures `faithfulness` and `answer_relevancy`.

```bash
just eval-baseline
just eval-baseline dataset=apps/eval/dataset/qa_pairs.json output=apps/eval/results/baseline.json
```

> **Note:** Baseline `faithfulness` uses `expected_answer` as proxy retrieved context — it measures
> consistency with ground truth, not document grounding. Use the delta vs RAG to assess retrieval benefit.

### Step 4 — Run the RAG evaluation

Calls the `/query` endpoint, fetches the actual retrieved chunks from pgvector, and measures all four RAGAS metrics.

```bash
just eval-rag
just eval-rag dataset=apps/eval/dataset/qa_pairs.json output=apps/eval/results/rag.json
```

### Step 5 — Generate the comparison report

Produces a dated markdown report in `apps/eval/results/`.

```bash
just eval-report
just eval-report baseline=apps/eval/results/baseline.json rag=apps/eval/results/rag.json
```

Example output:

```
# Evaluation Report — 2026-06-30

## RAGAS Metrics: No-RAG Baseline vs RAG Pipeline

| Metric              | No-RAG Baseline | RAG Pipeline | Delta   |
|---------------------|----------------|--------------|---------|
| context_recall      | N/A            | 0.7800       | +0.7800 |
| context_precision   | N/A            | 0.8200       | +0.8200 |
| faithfulness        | 0.6100         | 0.8900       | +0.2800 |
| answer_relevancy    | 0.7200         | 0.8500       | +0.1300 |
```

AC-9 is satisfied when `context_recall` and `faithfulness` are higher for RAG than baseline.

## File layout

```
apps/eval/
├── schema.py               # QAPair TypedDict + validate_qa_pair / validate_dataset
├── generate_dataset.py     # Step 1: Claude → raw Q&A JSON
├── baseline.py             # Step 3: no-RAG evaluation (faithfulness, answer_relevancy)
├── run_eval.py             # Step 4: RAG evaluation (all 4 RAGAS metrics)
├── compare.py              # Step 5: markdown comparison report
├── dataset/
│   ├── .gitignore          # raw_qa_pairs.json excluded; qa_pairs.json committed
│   └── qa_pairs.json       # curated dataset (add after Step 2)
├── results/                # generated reports and JSON result files (gitignored)
└── tests/unit/             # 67 offline tests (all external calls mocked)
```

## RAGAS metrics

| Metric              | What it measures                               | Who uses it |
| ------------------- | ---------------------------------------------- | ----------- |
| `context_recall`    | Ground truth covered by retrieved chunks       | RAG only    |
| `context_precision` | Fraction of retrieved chunks that are relevant | RAG only    |
| `faithfulness`      | Answer claims supported by retrieved context   | Both        |
| `answer_relevancy`  | Answer addresses the question                  | Both        |
