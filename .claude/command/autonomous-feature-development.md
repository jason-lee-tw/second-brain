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

---

## Stage 1: Parallel Implementation

Spawn one worktree agent per task **simultaneously** using the Agent tool. Pass each agent:
- Its `task_id`
- The path to its task file: `.loop-logs/tasks/<task-id>.json`

Do NOT run agents sequentially. All agents must start at the same time.

---

### Per-task Agent Instructions

Each worktree agent follows these steps exactly:

#### Agent Step A — Read task file

Read `.loop-logs/tasks/<task-id>.json`. Extract:
- `plan` (plan_path)
- `spec` (spec_path)
- `attempt` (current attempt count)
- `task_id`

#### Agent Step B — Create worktree

```bash
git worktree add .worktrees/<task-id> -b worktree/<task-id>
```

Switch your working directory to `.worktrees/<task-id>` for all remaining steps in this agent.
All bash commands, file reads, and git operations MUST run from within `.worktrees/<task-id>`.

Update task JSON: `"status": "in_progress"`, `"worktree": ".worktrees/<task-id>"`.

#### Agent Step C — Read task content

From `plan_path`, read the full section for this task: from `### Task N: <name>` to the next `### Task` heading (or end of file). Also read the full `spec_path` for architectural context.

#### Agent Step D — TDD loop (max 3 attempts)

**Before each attempt:**
- Append to `.loop-logs/logs/<task-id>.md`:
  ```markdown
  ## Attempt <N> — <ISO timestamp>
  ### Implementation plan
  <3-5 bullet points describing your approach>
  ```

**Implement:**
1. Write the failing test first. Run it and confirm it fails with the expected reason.
2. Write the minimal implementation to make it pass.
3. Run verifiable signals in this order:
   - `just lint` — must exit 0
   - `just test-unit` — must exit 0

**On pass (both signals green):**
- Append to log:
  ```markdown
  ### Lint output
  PASS
  ### Test output
  PASS
  ### Outcome: success
  ```
- Update task JSON: `"status": "completed"`, `"attempt": <N>`.
- Update `completed_steps` in task JSON: append the string `"tdd-loop-complete"`.
- Commit in the worktree directory:
  ```bash
  git add -A
  git commit -m "feat(<scope>): <task description>"
  ```
- Stop loop.

**On fail:**
- Append full output to log (lint under `### Lint output`, test under `### Test output`)
- Append `### Outcome: failed — <one-line root cause>`
- Increment `attempt` in task JSON (write the new value back to the file)
- If the new `attempt` value is less than 3: return to the start of the TDD loop (new attempt)
- If the new `attempt` value equals 3: proceed to Hard Stop below

**Hard Stop (attempt reached 3):**
- Append `### Outcome: HARD STOP after 3 attempts` to log.
- Write `.loop-logs/error/<task-id>.md`:
  ```markdown
  # Failed: <task-id>

  **Task:** <task description from plan>
  **Plan:** <plan_path>
  **Spec:** <spec_path>
  **Attempts:** 3

  ## Attempt 1
  <full lint + test output from log>
  <output of: git diff>

  ## Attempt 2
  <full lint + test output from log>
  <output of: git diff>

  ## Attempt 3
  <full lint + test output from log>
  <output of: git diff>

  ## Reproduction
  cd <worktree path>
  just lint
  just test-unit
  ```
- Update task JSON: `"status": "failed"`.
- Commit partial work:
  ```bash
  git add -A
  git commit -m "wip: failed <task-id> after 3 attempts"
  ```
- Stop.

---

### Squash Merge (after all agents finish)

Wait for all worktree agents to complete (success or hard-stop).

For each task with `"status": "completed"`:
```bash
git merge --squash worktree/<task-id>
git commit -m "feat(<scope>): <task description>"
git worktree remove .worktrees/<task-id> --force
git branch -D worktree/<task-id>
```

For each task with `"status": "failed"`:
- Do NOT merge its worktree.
- Log in `.loop-logs/logs/summary.md`:
  ```
  FAILED: <task-id> — see .loop-logs/error/<task-id>.md
  ```

---

## Stage 2: Verification

Run the `/verifying-implementation:verifying-implementation` skill.

The skill boots the system and exercises the changed endpoints/paths. Match observed output against the acceptance criteria in `spec_path`.

**If verification passes:** Proceed to Stage 3.

**If verification fails:**
1. Analyze the root cause from the verification output.
2. Spawn a fix worktree agent using the same TDD mini-loop as Stage 1 (single task, targeting the root cause).
3. Squash-merge the fix:
   ```bash
   git merge --squash worktree/verification-fix-<round>
   git commit -m "fix: address verification failure round <round>"
   git worktree remove .worktrees/verification-fix-<round> --force
   git branch -D worktree/verification-fix-<round>
   ```
4. Re-run verification.
5. Repeat up to **3 rounds total**.

**If still failing after 3 rounds:**
- Write `.loop-logs/error/verification-failure.md`:
  ```markdown
  # Verification Failed After 3 Rounds

  **Spec:** <spec_path>

  ## Round 1
  <full verification output>

  ## Round 2
  <full verification output>

  ## Round 3
  <full verification output>
  ```
- Commit: `wip: verification failed after 3 rounds — see .loop-logs/error/verification-failure.md`
- Stop.

---

## Stage 3: Complex Review

Run the `/complex-review` command on the current feature branch.

After complex-review completes, append to `.loop-logs/logs/complex-review.md`:

```markdown
# Complex Review Summary

**Date:** <timestamp>
**Issues found:** <N>
**Issues fixed:** <N>
**Review rounds:** <N>
```

---

## Stage 4: Final Commit

### Step 4.1 — Final lint and format

```bash
just lint    # must exit 0
just format  # must exit 0
```

If either fails, fix the issues before proceeding.

### Step 4.2 — Write summary

Write `.loop-logs/logs/summary.md`:

```markdown
# Loop Summary

**Plan:** <plan_path>
**Spec:** <spec_path>
**Branch:** <branch name>
**Date:** <timestamp>

## Tasks

| Task | Status | Attempts |
|------|--------|----------|
| <task-id> | completed / failed | N |

**Completed:** N/total
**Failed:** N/total (see .loop-logs/error/ for details)

## Verification
Rounds: N

## Review
Rounds: N
```

### Step 4.3 — Commit

Stage everything:
```bash
git add -A
```

**If all tasks completed successfully:**
```bash
git commit -m "feat(<scope>): <description derived from plan Goal line>"
```

**If any tasks failed (partial):**
```bash
git commit -m "wip: partial — <completed>/<total> tasks completed

Failed tasks:
<task-id-1>: see .loop-logs/error/<task-id-1>.md
<task-id-2>: see .loop-logs/error/<task-id-2>.md"
```

---

## Hard Rules

1. Never delete tests to make them pass.
2. One feature per commit — keep it atomic.
3. Always commit at the end, even if partial (`wip:` prefix for partial/failed).
4. Verifiable signal must be green before advancing to the next stage.
5. Squash merge only — never plain `git merge` on worktree branches (see `.claude/rules/git-linear-history.md`).
6. If truly ambiguous, make a reasonable assumption and document it in a code comment.
