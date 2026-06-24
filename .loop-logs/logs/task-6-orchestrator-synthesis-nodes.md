# Task 6: Fix orchestrator.py and synthesis.py

## Status: COMPLETED

## Changes Made

### apps/backend/src/second_brain/nodes/orchestrator.py
- Added `RouteQueryOutput` to the import from `second_brain.graphs.state`
- Changed `model="claude-haiku-4-5"` to `model_name="claude-haiku-4-5"` in `ChatAnthropic` constructor
- Changed return type of `route_query` from `dict` to `RouteQueryOutput`
- Added `# type: ignore[assignment]` to the `_structured_llm.ainvoke` assignment

### apps/backend/src/second_brain/nodes/synthesis.py
- Added `SynthesisNodeOutput` to the import from `second_brain.graphs.state`
- Changed `model="claude-sonnet-4-6"` to `model_name="claude-sonnet-4-6"` in `ChatAnthropic` constructor
- Changed return type of `synthesize_answer` from `dict` to `SynthesisNodeOutput`
- Added `# type: ignore[assignment]` to the `_structured_llm.ainvoke` assignment

## Verification

- `just lint`: All checks passed
- `just test-unit`: 165 passed, 2 warnings (no failures)
- Commit: `6bb94b7` on branch `worktree/task-6-orchestrator-synthesis-nodes`
