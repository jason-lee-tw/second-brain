---
description: Autonomous feature development loop — Karpathy Loop (parallel worktrees, TDD, review, verify)
---

# Autonomous Feature Development Loop

## Operating Mode

FULLY AUTONOMOUS. Do not pause. Do not ask questions. Complete end-to-end.
If something is truly ambiguous, make a reasonable assumption and document it in a code comment.

---

## Arguments

`$ARGUMENTS` contains two file paths separated by a space:

```
/autonomous-feature-development <plan.md> <spec.md>
```

Parse `$ARGUMENTS` by splitting on whitespace:
- `plan_path` = first token
- `spec_path` = second token

---

## Stage 0: Guard & Setup

### Step 0.1 — Validate inputs

Check each file in order:

1. Does `plan_path` exist on disk?
   - No → print `ERROR: Plan file not found: <plan_path>` and stop immediately.
2. Is `plan_path` non-empty (size > 0)?
   - No → print `ERROR: Plan file is empty: <plan_path>` and stop immediately.
3. Does `spec_path` exist on disk?
   - No → print `ERROR: Spec file not found: <spec_path>` and stop immediately.
4. Is `spec_path` non-empty (size > 0)?
   - No → print `ERROR: Spec file is empty: <spec_path>` and stop immediately.

### Step 0.2 — Branch guard

Run: `git rev-parse --abbrev-ref HEAD`

- If the result is `main`:
  - Derive branch name from the plan filename (basename only):
    - Strip a leading date prefix matching `YYYY-MM-DD-` if present
    - Strip the `.md` suffix
    - Prepend `feature/`
    - Example: `2026-06-16-ticket-3-ingestion.md` → `feature/ticket-3-ingestion`
  - Run: `git checkout -b <branch-name>`
- If not on `main`: continue on the current branch.

### Step 0.3 — Parse tasks

Read `plan_path`. Extract every heading that matches the pattern `### Task N: <name>` (where N is a number). For each match:

- Derive `task_id`: `task-<N>-<kebab-case-name>`
  - Example: `### Task 3: Tavily Service` → `task-3-tavily-service`
- Record the line range (from this heading to the next `### Task` heading or end of file) — this is the task section you will pass to the worktree agent.

### Step 0.4 — Initialize task files

For each parsed task, write `.loop-logs/tasks/<task-id>.json`:

```json
{
  "task_id": "<task_id>",
  "plan": "<plan_path>",
  "spec": "<spec_path>",
  "status": "pending",
  "attempt": 0,
  "worktree": null,
  "completed_steps": []
}
```

**Resume:** Before writing a task file, check if `.loop-logs/tasks/<task-id>.json` already exists with `"status": "completed"`. If so, skip that task entirely — do not overwrite it, do not spawn a worktree agent for it.

After all files are written, print:

```
Setup complete. Found <N> tasks:
  - <task-id-1>
  - <task-id-2>
  ...
Working branch: <current-branch>
```
