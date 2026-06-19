# Autonomous Feature Development Loop — Design Spec

**Date:** 2026-06-19  
**Concept basis:** Andrej Karpathy's Agentic Engineering (the Karpathy Loop)

---

## Problem

Developers produce specs and plans via `/superpowers:brainstorming` and `/superpowers:writing-plans`. Executing those plans still requires manual orchestration: create a branch, implement each task, run tests, review, verify. This command automates that entire loop end-to-end.

---

## Core Principle

Every loop stage must produce a **verifiable signal** before advancing. The loop does not close until all signals are green. No verifiable signal = no reliable loop.

```
Propose → Implement → Test → Verify → Commit or Rollback
    ↑_____________ retry (max 3) __|
```

---

## Invocation

```bash
claude -p "/autonomous-feature-development <plan.md> <spec.md>"
```

**Arguments:**
- `<plan.md>` — implementation plan produced by `/superpowers:writing-plans`
- `<spec.md>` — design spec produced by `/superpowers:brainstorming`

Both files must exist and be non-empty. The command fails immediately with a clear error message naming the missing or empty file.

---

## Stage 0: Guard & Setup

1. **Validate inputs** — both files exist and are non-empty; fail with clear error otherwise
2. **Branch guard** — if on `main`, auto-create a feature branch named from the plan filename (e.g., `2026-06-16-ticket-3-ingestion.md` → `feature/ticket-3-ingestion`); if already on a non-`main` branch, use it
3. **Parse tasks** — extract each top-level `### Task N: ...` heading from the plan file as one unit of work
4. **Initialize task files** — write `.loop-logs/tasks/<task-id>.json` per task:

```json
{
  "task_id": "task-003-tavily-service",
  "plan": "./docs/superpowers/plans/2026-06-16-ticket-3-ingestion.md",
  "spec": "./docs/superpowers/specs/2026-06-16-second-brain-design.md",
  "status": "pending",
  "attempt": 0,
  "worktree": null,
  "completed_steps": []
}
```

The task JSON is the self-contained work ticket: any worktree agent reads it to know the plan path, spec path, current attempt, and which steps are done. This also enables a natural resume mechanism — re-running the command skips `"completed"` tasks.

---

## Stage 1: Parallel Implementation (per task)

All tasks run simultaneously, each in its own git worktree. Each worktree agent runs an independent Karpathy mini-loop:

```
Propose → Implement (TDD) → Test → Verify signal
    ↑______________ retry (max 3) __|
```

### Per-task agent steps

1. **Propose** — read the task section from `plan.md` and full context from `spec.md`; write a short implementation plan as `## Attempt N` header in `.loop-logs/logs/<task-id>.md`
2. **Implement (TDD)** — write failing test first, implement until it passes; `just lint` + `just test-unit` are the verifiable signal
3. **On failure** — increment `attempt` in task JSON, append failure output to log file, retry from Propose
4. **On 3rd failure** — write `.loop-logs/error/<task-id>.md` (see Error File Format), update task status to `"failed"`, commit with `wip: failed <task-id>` so partial work is not lost, stop
5. **On success** — update task status to `"completed"`, commit to the worktree branch

### Squash merge

After all worktree agents finish, squash-merge each completed task into the feature branch per `.claude/rules/git-linear-history.md`:

```bash
git merge --squash <worktree-branch>
git commit -m "feat(scope): <task description>"
```

Failed tasks are excluded from the merge (their `wip:` commits stay on their own worktree branches for inspection).

---

## Stage 2: Verification

After squash-merge, the feature branch must pass runtime verification before review.

1. Run `/verifying-implementation:verifying-implementation` — boots the system, exercises the changed endpoints/paths, confirms observed output matches acceptance criteria from the spec
2. **If verification fails** — analyze root cause, spawn fix worktrees (same TDD mini-loop as Stage 1), squash-merge fixes back, re-verify; max 3 rounds before hard-stop with a `wip:` commit + error log
3. **If verification passes** — proceed to complex review

---

## Stage 3: Complex Review

Delegated entirely to `/complex-review`:

```
Parallel review subagents (enhanced-review + ponytail-review + simplify)
          ↓
Consolidation subagent (validates + deduplicates findings)
          ↓
Fix issues in parallel worktrees (squash merge back)
          ↓
Re-verify with verifying-implementation after fixes
          ↓
Re-review until no issues remain
```

After complex-review completes, append a summary to `.loop-logs/logs/complex-review.md`.

---

## Stage 4: Final Commit

1. **`just lint` + `just format`** — final cleanliness gate
2. **Commit** in one conventional commit:
   - All implementation changes
   - All `.loop-logs/` files (tasks, logs, errors if any partial failures)
   - Message: `feat(scope): <description from plan title>`
   - If any tasks hard-stopped: `wip: partial - N/total tasks completed` with error file paths referenced in the body
3. **Summary** — write `.loop-logs/logs/summary.md`: tasks completed, tasks failed (with error file paths), verification rounds, review rounds

---

## `.loop-logs/` File Formats

### Task file — `.loop-logs/tasks/<task-id>.json`

```json
{
  "task_id": "task-003-tavily-service",
  "plan": "<path>",
  "spec": "<path>",
  "status": "pending | in_progress | completed | failed",
  "attempt": 0,
  "worktree": null,
  "completed_steps": []
}
```

### Log file — `.loop-logs/logs/<task-id>.md`

One file per task, sections appended per attempt:

```markdown
# task-003-tavily-service

## Attempt 1 — <timestamp>
### Implementation plan
...
### Lint output
...
### Test output
...
### Outcome: failed — <reason>

## Attempt 2 — <timestamp>
...
```

### Error file — `.loop-logs/error/<task-id>.md`

Written only on 3rd failure. Must contain enough for a developer to reproduce:

```markdown
# Failed: task-003-tavily-service

**Task:** <task description from plan>
**Plan:** <path>
**Spec:** <path>
**Attempts:** 3

## Attempt 1
<full lint + test output>
<git diff>

## Attempt 2
...

## Attempt 3
...

## Reproduction
<exact commands to reproduce the failure state>
```

---

## Hard Rules

1. Never delete tests to make them pass
2. One feature per commit — keep it atomic
3. Always commit at the end, even if partial (`wip:` prefix for partial/failed)
4. Verifiable signal must be green before advancing to the next stage
5. Squash merge only — never plain `git merge` on worktree branches
6. If truly ambiguous, make a reasonable assumption and document it in a code comment

---

## Full Loop Shape

```
Validate inputs + guard branch
          ↓
Parse tasks → initialize .loop-logs/tasks/*.json
          ↓
Parallel worktrees: TDD loop per task (max 3 retries each)
          ↓
Squash-merge completed tasks → feature branch
          ↓
verifying-implementation (max 3 rounds)
          ↓
complex-review → fix in worktrees → squash-merge → re-verify
          ↓
just lint + just format
          ↓
Conventional commit (feat: full success | wip: if partial)
```
