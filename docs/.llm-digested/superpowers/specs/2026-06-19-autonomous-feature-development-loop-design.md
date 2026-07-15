# Autonomous Feature Development Loop — Design Spec

Source: docs/superpowers/specs/2026-06-19-autonomous-feature-development-loop-design.md
Primary-Topic: autonomous-feature-development-loop
Secondary-Topics: git-worktree-workflow, verification-and-review-pipeline

## Key Concepts

- **Origin/basis** — the design is based on Andrej Karpathy's Agentic Engineering concept, referred to throughout as the "Karpathy Loop."
- **Problem statement** — `/superpowers:brainstorming` and `/superpowers:writing-plans` produce specs and plans, but executing those plans still needs manual orchestration (branch creation, per-task implementation, testing, review, verification). This command (`/autonomous-feature-development`) automates that entire loop end-to-end.
- **Core principle** — every loop stage must produce a verifiable signal before advancing; the loop does not close until all signals are green. "No verifiable signal = no reliable loop."
- **High-level loop shape** — `Propose → Implement → Test → Verify → Commit or Rollback`, with a retry loop (max 3) from Verify back to Propose.
- **Invocation** — `claude -p "/autonomous-feature-development <plan.md> <spec.md>"`. Arguments: `<plan.md>` (from `/superpowers:writing-plans`) and `<spec.md>` (from `/superpowers:brainstorming`). Both files must exist and be non-empty, else the command fails immediately with a clear error naming the missing/empty file.

### Stage 0: Guard & Setup
- **Validate inputs** — check both plan and spec files exist and are non-empty.
- **Branch guard** — if currently on `main`, auto-create a feature branch named from the plan filename (example: `2026-06-16-ticket-3-ingestion.md` → `feature/ticket-3-ingestion`); if already on a non-`main` branch, reuse it.
- **Parse tasks** — extract each top-level `### Task N: ...` heading from the plan file as one discrete unit of work.
- **Initialize task files** — write one `.loop-logs/tasks/<task-id>.json` per task, containing `task_id`, `plan` path, `spec` path, `status` (starts `"pending"`), `attempt` (starts `0`), `worktree` (starts `null`), and `completed_steps` (starts `[]`).
- The task JSON is described as a "self-contained work ticket": any worktree agent reads it to learn the plan path, spec path, current attempt count, and which steps are already done. This also gives a natural resume mechanism — re-running the command skips tasks already marked `"completed"`.

### Stage 1: Parallel Implementation (per task)
- All tasks run simultaneously, each in its own git worktree.
- Each worktree agent runs an independent Karpathy mini-loop: `Propose → Implement (TDD) → Test → Verify signal`, with retry (max 3) back to Propose.
- **Per-task agent steps:**
  1. Propose — read the task's section from `plan.md` plus full context from `spec.md`; write a short implementation plan as an `## Attempt N` header in `.loop-logs/logs/<task-id>.md`.
  2. Implement (TDD) — write a failing test first, then implement until it passes; `just lint` + `just test-unit` serve as the verifiable signal.
  3. On failure — increment `attempt` in the task JSON, append failure output to the log file, retry from Propose.
  4. On 3rd failure — write `.loop-logs/error/<task-id>.md` (see Error File Format below), set task status to `"failed"`, commit with message `wip: failed <task-id>` so partial work isn't lost, then stop.
  5. On success — set task status to `"completed"`, commit to the worktree branch.
- **Squash merge** — after all worktree agents finish, squash-merge each completed task into the feature branch per `.claude/rules/git-linear-history.md`, using `git merge --squash <worktree-branch>` followed by `git commit -m "feat(scope): <task description>"`. Failed tasks are excluded from the merge; their `wip:` commits remain on their own worktree branches for inspection.

### Stage 2: Verification
- After squash-merge, the feature branch must pass runtime verification before review.
- Step 1 — run `/verifying-implementation:verifying-implementation`, which boots the system, exercises the changed endpoints/paths, and confirms observed output matches the spec's acceptance criteria.
- Step 2 — if verification fails: analyze root cause, spawn fix worktrees using the same TDD mini-loop as Stage 1, squash-merge fixes back, and re-verify. Max 3 rounds before a hard-stop with a `wip:` commit plus an error log.
- Step 3 — if verification passes, proceed to complex review.

### Stage 3: Complex Review
- Delegated entirely to `/complex-review`, whose internal pipeline is:
  1. Parallel review subagents: `enhanced-review` + `ponytail-review` + `simplify`.
  2. A consolidation subagent validates and deduplicates findings from the parallel reviewers.
  3. Fix issues in parallel worktrees, squash-merged back.
  4. Re-verify with `verifying-implementation` after fixes.
  5. Re-review until no issues remain.
- After complex-review completes, a summary is appended to `.loop-logs/logs/complex-review.md`.

### Stage 4: Final Commit
1. Run `just lint` + `just format` as a final cleanliness gate.
2. Create one conventional commit containing: all implementation changes, and all `.loop-logs/` files (tasks, logs, errors if any partial failures). Message is `feat(scope): <description from plan title>` on full success, or `wip: partial - N/total tasks completed` (with error file paths referenced in the body) if any tasks hard-stopped.
3. Write a summary file `.loop-logs/logs/summary.md` covering: tasks completed, tasks failed (with error file paths), verification rounds, and review rounds.

### `.loop-logs/` File Formats
- **Task file** (`.loop-logs/tasks/<task-id>.json`) — JSON with `task_id`, `plan`, `spec`, `status` (`pending | in_progress | completed | failed`), `attempt`, `worktree`, `completed_steps`.
- **Log file** (`.loop-logs/logs/<task-id>.md`) — one file per task; Markdown sections appended per attempt, each with `## Attempt N — <timestamp>` followed by `### Implementation plan`, `### Lint output`, `### Test output`, and `### Outcome: failed — <reason>` (or success).
- **Error file** (`.loop-logs/error/<task-id>.md`) — written only on the 3rd failure; must contain enough detail for a developer to reproduce the failure. Includes task description, plan path, spec path, attempt count (3), a `## Attempt N` section per attempt with full lint + test output and `git diff`, and a final `## Reproduction` section with exact commands to reproduce the failure state.

### Hard Rules
1. Never delete tests to make them pass.
2. One feature per commit — keep commits atomic.
3. Always commit at the end, even if partial (use `wip:` prefix for partial/failed work).
4. A verifiable signal must be green before advancing to the next stage.
5. Squash merge only — never plain `git merge` on worktree branches.
6. If truly ambiguous, make a reasonable assumption and document it in a code comment.

### Full Loop Shape (end-to-end summary)
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
