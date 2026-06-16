# Check if ollama is installed
if ! command -v ollama &>/dev/null; then
  echo -e "\033[31mOllama is not installed.\nRun command \`\033[32mbrew install ollama\033[31m\` to install Ollama\033[0m"
  exit 1
fi

echo "Starting Ollama..."

# Start ollama server on port 11434
OLLAMA_FLASH_ATTENTION=true \
  OLLAMA_HOST=0.0.0.0 \
  OLLAMA_MAX_LOADED_MODELS=1 \
  OLLAMA_NUM_PARALLEL=1 \
  OLLAMA_MAX_QUEUE=512 \
  OMP_NUM_THREADS=6 \
  OLLAMA_MODELS=~/.ollama/models \
  OLLAMA_KV_CACHE_TYPE=f16 \
  OLLAMA_NO_CACHE=false \
  ollama serve >/dev/null 2>&1 &

echo "✅ Ollama is started"