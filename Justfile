help:
  @just -l

[group: "Initialize repository"]
init:
  @chmod +x ./scripts/init.sh && \
    ./scripts/init.sh


# Start Ollama
[group: "Ollama"]
up-ollama:
  @chmod +x ./scripts/start-ollama.sh
  @bash ./scripts/start-ollama.sh


# Stop Ollama
[group: "Ollama"]
down-ollama:
  @chmod +x ./scripts/stop-ollama.sh
  @bash ./scripts/stop-ollama.sh


# Run all apps with Docker
[group: "App"]
up-build:
  @docker compose --env-file ./apps/backend/.env -f ./docker-compose.yml up --build


# Stop all apps
[group: "App"]
down:
  @docker compose -f ./docker-compose.yml down


# Start all services including Ollama
[group: "App"]
up-all:
  @just up-ollama up-build


# Stop all services including Ollama
[group: "App"]
down-all:
  @just down-ollama down


# Stop App docker containers and remove volumes
[group: "Clean up"]
down-clean:
  @docker compose -f ./docker-compose.yml down && \
    echo "🔄 Deleting all unused volumes..." && \
    docker volume prune -af && \
    echo "✅ Deleted all unused volumes"
  @echo "🔄 Deleting all temp folders" && \
    find . -type d -name "temp" | xargs rm -rf && \
    echo "✅ Deleted all temp folders"


# Run Alembic migrations (requires running postgres via just up-build first)
[group: "DB"]
migrate:
  @uv run --package second-brain alembic upgrade head


[group: "Clean up"]
clean-python:
  @rm -rf **/.venv ./.venv
  @echo "'.venv' folders are deleted."
  @find . -not -path './.git/*' -type d \( -name "__pycache__" -o -name ".pytest_cache" \) -exec rm -rf {} + 2>/dev/null; find . -not -path './.git/*' -name "*.pyc" -delete
  @rm -rf .ruff_cache
  @echo "All cached files are deleted."


# Lint entire workspace
[group: "Format"]
lint:
  @uv run ruff check .


# Lint with fix for entire workspace
[group: "Format"]
lint-fix:
  @uv run ruff check . --fix


# Run type check for backend
[group: "Format"]
type-check:
  @echo "🔄 Type checking..."
  @cd ./apps/backend && \
    uv run basedpyright ./src/ && \
    echo "✅ Type check is completed"


# Format entire workspace
[group: "Format"]
format:
  @uv run ruff format .


# Backend unit tests
[group: "Test"]
test-unit:
  @uv run --package second-brain pytest apps/backend/tests/unit


# Backend integration tests
[group: "Test"]
test-integration:
  @uv run --package second-brain pytest apps/backend/tests/integration


# Eval harness unit tests
[group: "Test"]
test-eval:
  @uv run --directory apps/eval pytest tests/unit


# Run all backend tests
[group: "Test"]
test:
  @uv run --package second-brain pytest apps/backend/tests


# Check backend implementation (code format, lint, unit + integration test)
[group: "Test"]
check-implementation-backend:
  @just format lint type-check test-unit test-integration


# Generate raw Q&A pairs from ingested documents (requires running backend + DB)
[group: "LLM Evaluation"]
eval-generate n_per_doc="7" output="apps/eval/dataset/raw_qa_pairs.json":
  @uv run --directory apps/eval python generate_dataset.py --n-per-doc {{n_per_doc}} --output {{output}}


# Run no-RAG baseline evaluation (requires ANTHROPIC_API_KEY)
[group: "LLM Evaluation"]
eval-baseline dataset="apps/eval/dataset/qa_pairs.json" output="apps/eval/results/baseline.json":
  @uv run --directory apps/eval python baseline.py --dataset {{dataset}} --output {{output}}


# Run RAG pipeline evaluation (requires running backend + DB + Ollama)
[group: "LLM Evaluation"]
eval-rag dataset="apps/eval/dataset/qa_pairs.json" output="apps/eval/results/rag.json":
  @uv run --directory apps/eval python run_eval.py --dataset {{dataset}} --output {{output}}


# Generate comparison report from baseline and RAG result files
[group: "LLM Evaluation"]
eval-report baseline="apps/eval/results/baseline.json" rag="apps/eval/results/rag.json" output_dir="apps/eval/results":
  @uv run --directory apps/eval python compare.py --baseline {{baseline}} --rag {{rag}} --output-dir {{output_dir}}
