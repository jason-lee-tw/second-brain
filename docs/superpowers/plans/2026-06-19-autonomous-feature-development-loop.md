# Autonomous Feature Development Loop — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite `.claude/command/autonomous-feature-development.md` to implement the full Karpathy Loop — parallel worktrees per task, 3-retry guard, verifying-implementation gate, complex-review delegation, squash-merge linear history, and `.loop-logs/` audit trail.

**Architecture:** The command is a Claude Code prompt file (markdown). When invoked with `claude -p "/autonomous-feature-development <plan.md> <spec.md>"`, Claude reads the command, parses `$ARGUMENTS`, and orchestrates the loop using the Agent tool, git worktrees, and existing skills. No Python or shell scripts — all orchestration is performed by Claude following the prompt instructions.

**Tech Stack:** Claude Code command (markdown prompt), git worktrees, `just lint` / `just test-unit` / `just format`, skills: `verifying-implementation`, `complex-review`, `enhanced-review`. `.loop-logs/` directories already exist with `.gitkeep` files.

## Global Constraints

- Command file lives at `.claude/command/autonomous-feature-development.md`
- `.loop-logs/tasks/`, `.loop-logs/logs/`, `.loop-logs/error/` directories already exist — do not create them
- Task JSON schema must match exactly: `task_id`, `plan`, `spec`, `status`, `attempt`, `worktree`, `completed_steps`
- Branch naming from plan filename: strip leading date (`YYYY-MM-DD-`) and `.md` suffix, prepend `feature/` (e.g. `2026-06-16-ticket-3-ingestion.md` → `feature/ticket-3-ingestion`)
- Squash-merge only — reference `.claude/rules/git-linear-history.md`
- Max 3 retries per task; max 3 verification rounds
- Commit convention: `feat(scope): description` on full success; `wip: partial — N/total tasks completed` on partial failure

---

## File Map

| Status | Path | Responsibility |
|--------|------|----------------|
| Modify | `.claude/command/autonomous-feature-development.md` | Full Karpathy Loop command |

---

### Task 1: Stage 0 — Guard & Setup

**Files:**
- Modify: `.claude/command/autonomous-feature-development.md`

**Interfaces:**
- Produces: `$ARGUMENTS` parsed into `plan_path` / `spec_path`; `.loop-logs/tasks/<task-id>.json` files; feature branch

- [ ] **Step 1: Write the failing review check**

Before writing any content, write a review checklist you will verify against after writing Stage 0:

```
Stage 0 checklist:
[ ] Parses $ARGUMENTS into plan_path and spec_path
[ ] Fails with named-file error if either file is missing
[ ] Fails with named-file error if either file is empty
[ ] Guards against main branch — auto-creates feature/... branch
[ ] Derives branch name from plan filename (strip date + .md, prepend feature/)
[ ] Parses ### Task N: headings from plan file
[ ] Writes .loop-logs/tasks/<task-id>.json with correct schema
[ ] task_id uses kebab format: task-<N>-<name>
[ ] JSON includes plan, spec, status="pending", attempt=0, worktree=null, completed_steps=[]
[ ] Resume: if .loop-logs/tasks/<task-id>.json already exists with status="completed", skip that task
```

- [ ] **Step 2: Replace the current command file with Stage 0 content**

Replace the entire contents of `.claude/command/autonomous-feature-development.md` with:

```markdown
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
```

- [ ] **Step 3: Verify Stage 0 content against checklist**

Read back the written command file and check every item in the Stage 0 checklist from Step 1. Fix any gaps inline. Do not move on until all boxes are checked.

- [ ] **Step 4: Commit Stage 0**

```bash
git add .claude/command/autonomous-feature-development.md
git commit -m "feat(command): add stage 0 guard and setup to autonomous dev loop"
```

---

### Task 2: Stage 1 — Parallel Implementation Loop

**Files:**
- Modify: `.claude/command/autonomous-feature-development.md`

**Interfaces:**
- Consumes: `.loop-logs/tasks/<task-id>.json` (from Task 1)
- Produces: completed worktree branches, `.loop-logs/logs/<task-id>.md`, `.loop-logs/error/<task-id>.md` (on failure), squash-merged feature branch

- [ ] **Step 1: Write the failing review check**

```
Stage 1 checklist:
[ ] All tasks spawn in parallel (not sequential)
[ ] Each agent reads its task JSON at start
[ ] Each agent creates a git worktree at .worktrees/<task-id>
[ ] task JSON updated: status=in_progress, worktree path set
[ ] Agent reads its task section from plan_path
[ ] TDD loop: write failing test first, then implement
[ ] Verifiable signals: just lint AND just test-unit (both must pass)
[ ] Attempt section written to .loop-logs/logs/<task-id>.md before each attempt
[ ] On fail < 3: increment attempt in JSON, append output to log, retry
[ ] On fail = 3: write .loop-logs/error/<task-id>.md, status=failed, wip commit
[ ] On success: status=completed, commit in worktree
[ ] Squash merge: git merge --squash, never plain git merge
[ ] Failed tasks excluded from squash merge
[ ] Worktree cleaned up after squash merge
```

- [ ] **Step 2: Append Stage 1 to the command file**

Append the following section after Stage 0 in `.claude/command/autonomous-feature-development.md`:

````markdown
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
- Commit in the worktree directory:
  ```bash
  git add -A
  git commit -m "feat(<scope>): <task description>"
  ```
- Stop loop.

**On fail (attempt < 3):**
- Append to log:
  ```markdown
  ### Lint output
  <full output>
  ### Test output
  <full output>
  ### Outcome: failed — <one-line root cause>
  ```
- Increment `attempt` in task JSON.
- Return to start of loop (new attempt).

**On fail (attempt = 3 — hard stop):**
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
````

- [ ] **Step 3: Verify Stage 1 content against checklist**

Read back the appended section and check every item in the Stage 1 checklist. Fix any gaps inline.

- [ ] **Step 4: Commit Stage 1**

```bash
git add .claude/command/autonomous-feature-development.md
git commit -m "feat(command): add stage 1 parallel implementation loop"
```

---

### Task 3: Stages 2–4 — Verification, Complex Review, Final Commit

**Files:**
- Modify: `.claude/command/autonomous-feature-development.md`

**Interfaces:**
- Consumes: squash-merged feature branch (from Task 2)
- Produces: verified, reviewed, committed feature branch with `.loop-logs/` audit trail

- [ ] **Step 1: Write the failing review check**

```
Stages 2-4 checklist:
[ ] verifying-implementation invoked after squash merge (Stage 2)
[ ] Verification failure: root cause analysis, fix worktree, squash-merge, re-verify
[ ] Verification max 3 rounds; hard-stop with wip commit + error log on 3rd failure
[ ] complex-review invoked after verification passes (Stage 3)
[ ] Summary appended to .loop-logs/logs/complex-review.md after review
[ ] just lint + just format run in Stage 4
[ ] Full success commit: feat(scope): <plan title>
[ ] Partial failure commit: wip: partial — N/total tasks completed
[ ] .loop-logs/ files included in final commit
[ ] summary.md written with: tasks completed, tasks failed, verification rounds, review rounds
```

- [ ] **Step 2: Append Stages 2–4 to the command file**

Append the following after Stage 1 in `.claude/command/autonomous-feature-development.md`:

````markdown
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
````

- [ ] **Step 3: Verify Stages 2–4 content against checklist**

Read back the appended section and check every item in the checklist. Fix any gaps inline.

- [ ] **Step 4: Commit Stages 2–4**

```bash
git add .claude/command/autonomous-feature-development.md
git commit -m "feat(command): add stages 2-4 verification review and commit"
```

---

### Task 4: End-to-End Smoke Test

**Files:**
- Create: `.loop-logs/` — test run artifacts (verify they appear correctly)
- Read: `.claude/command/autonomous-feature-development.md` — verify full command

**Interfaces:**
- Consumes: completed command file (from Tasks 1–3)
- Produces: confidence that Stage 0 guard logic and task parsing work correctly

- [ ] **Step 1: Create a minimal test plan**

Create `/tmp/test-plan.md` with content:

```markdown
# Test Feature — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Add a trivial hello-world function for smoke testing.

---

### Task 1: Hello World

**Files:**
- Create: `apps/backend/src/second_brain/hello.py`
- Test: `apps/backend/tests/unit/test_hello.py`

- [ ] **Step 1: Write failing test**

```python
from second_brain.hello import hello
def test_hello():
    assert hello() == "hello"
```

- [ ] **Step 2: Implement**

```python
def hello():
    return "hello"
```
```

Create `/tmp/test-spec.md` with content:

```markdown
# Test Spec
Acceptance criteria: `hello()` returns the string `"hello"`.
```

- [ ] **Step 2: Run Stage 0 guard — missing file case**

Open `.claude/command/autonomous-feature-development.md` in your editor and trace through Stage 0 manually with inputs `nonexistent.md` and `/tmp/test-spec.md`.

Expected output: `ERROR: Plan file not found: nonexistent.md`

Confirm the guard logic in the command would produce this output. If not, fix the command.

- [ ] **Step 3: Run Stage 0 guard — main branch case**

Run: `git rev-parse --abbrev-ref HEAD`

If the result is `main`, trace through Step 0.2 with plan filename `2026-06-19-autonomous-feature-development-loop.md`.

Expected branch name derived: `feature/autonomous-feature-development-loop`

Confirm the derivation logic in the command produces this. If not, fix.

- [ ] **Step 4: Verify task parsing logic**

Open the current plan file (`docs/superpowers/plans/2026-06-19-autonomous-feature-development-loop.md`) and count the `### Task N:` headings. Expected: 4 tasks.

Trace through Step 0.3 in the command to confirm it would derive these task IDs:
- `task-1-guard-and-setup`
- `task-2-parallel-implementation-loop`
- `task-3-stages-2-4-verification-complex-review-final-commit`
- `task-4-end-to-end-smoke-test`

If the kebab derivation logic is ambiguous, clarify it in the command.

- [ ] **Step 5: Review the complete command with enhanced-review**

Run the `/enhanced-review` skill on `.claude/command/autonomous-feature-development.md` against the spec at `docs/superpowers/specs/2026-06-19-autonomous-feature-development-loop-design.md`.

Fix any issues raised before committing.

- [ ] **Step 6: Commit smoke test artifacts and any fixes**

```bash
git add .claude/command/autonomous-feature-development.md
git commit -m "test(command): smoke test and enhanced-review fixes for autonomous dev loop"
```
