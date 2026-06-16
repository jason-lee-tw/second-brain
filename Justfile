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

[group: "Clean up"]
clean-python:
  @rm -rf **/.venv ./.venv
  @echo "'.venv' folders are deleted."
  @find . -not -path './.git/*' -type d \( -name "__pycache__" -o -name ".pytest_cache" \) -exec rm -rf {} + 2>/dev/null; find . -not -path './.git/*' -name "*.pyc" -delete
  @rm -rf .ruff_cache
  @echo "All cached files are deleted."