set -euo pipefail

echo "🔄 Initializing git hooks..."

git config core.hooksPath ./.hooks

chmod +x ./.hooks/commit-msg
chmod +x ./.hooks/pre-commit

echo "✅ Complete initializing git hooks"

echo "🔄 Initializing UV packages..."

uv sync --all-extras

echo "✅ Complete initializing UV packages"
