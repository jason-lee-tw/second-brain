echo "🔄 Initializing git hooks..."

git config core.hooksPath ./.hooks

chmod +x ./.hooks/commit-msg
chmod +x ./.hooks/pre-commit

echo "✅ Complete initializing git hooks"