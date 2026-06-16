# Stop all models running on Ollama
ollama list | awk 'NR>1 {print $1}' | xargs -I {} sh -c 'echo "Stopping {}"; ollama stop {}'

# Stop Ollama server process
pkill -f "ollama serve" && echo "Ollama stopped" || echo "Ollama was not running"