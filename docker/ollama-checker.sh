#!/bin/sh
set -eu

RED='\033[0;31m'
NC='\033[0m'
MODEL="qwen3-embedding:0.6b"

if [ -z "${OLLAMA_BASE_URL:-}" ]; then
  printf "${RED}OLLAMA_BASE_URL is not set.${NC}\n" >&2
  exit 1
fi

if ! curl -sf "${OLLAMA_BASE_URL}" >/dev/null 2>&1; then
  printf "${RED}Ollama server is not running.${NC}\n" >&2
  exit 1
fi

is_installed() {
  curl -sf "${OLLAMA_BASE_URL}/api/tags" | grep -q "\"name\":\"${MODEL}"
}

if is_installed; then
  echo "Model ${MODEL} is already installed."
  exit 0
fi

echo "Installing model ${MODEL}..."
curl -fsS -X POST "${OLLAMA_BASE_URL}/api/pull" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"${MODEL}\"}"
echo ""

if is_installed; then
  echo "Model ${MODEL} installed successfully."
  exit 0
fi

printf "${RED}Failed to install model ${MODEL}.${NC}\n" >&2
exit 1
