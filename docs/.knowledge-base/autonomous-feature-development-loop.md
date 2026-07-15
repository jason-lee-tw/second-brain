# Autonomous Feature Development Loop

An autonomous Claude Code command (`/autonomous-feature-development`) that automates the full "Karpathy Loop" — plan parsing, parallel per-task implementation in git worktrees, verification, complex review, and a final squash-merged commit — with no manual orchestration.

## Key Concepts

- **Origin and purpose** — based on Andrej Karpathy's Agentic Engineering "Karpathy Loop" concept. `/superpowers:brainstorming` and `/superpowers:writing-plans` produce specs and plans, but executing them still required manual orchestration (branch creation, per-task implementation, testing, review, verification); this command automates that entire loop end-to-end.
- **Command shape** — a markdown prompt file at `.claude/command/autonomous-feature-development.md`, not a script. Invoked as `claude -p "/autonomous-feature-development <plan.md> <spec.md>"`. Claude parses `$ARGUMENTS` itself and orchestrates the loop using the Agent tool, git worktrees, and existing skills (`verifying-implementation`, `complex-review`, `enhanced-review`) — no Python/shell orchestration scripts.
- **Core principle** — every stage must produce a verifiable signal before advancing; the loop never closes until all signals are green ("no verifiable signal = no reliable loop").
- **High-level loop shape** — `Propose → Implement → Test → Verify → Commit or Rollback`, with a retry loop (max 3 attempts) from Verify back to Propose.
- **Operating mode** — fully autonomous: never pauses or asks questions; on true ambiguity, makes a reasonable assumption and documents it in a code comment.
- **Invocation arguments** — `<plan.md>` (from `/superpowers:writing-plans`) and `<spec.md>` (from `/superpowers:brainstorming`); both must exist and be non-empty, else the command fails immediately with a named-file error.

## Stages

### Stage 0 — Guard & Setup
- Validates `<plan.md>` and `<spec.md>` both exist and are non-empty; on failure, prints a named `ERROR:` message (e.g. `ERROR: Plan file not found: <plan_path>`) and stops immediately.
- **Branch guard** — runs `git rev-parse --abbrev-ref HEAD`; if on `main`, derives a feature branch name from the plan filename (strip leading `YYYY-MM-DD-` date prefix and `.md`, prepend `feature/`, e.g. `2026-06-16-ticket-3-ingestion.md` → `feature/ticket-3-ingestion`) and runs `git checkout -b <branch-name>`; otherwise continues on the current branch.
- **Task parsing** — extracts every top-level `### Task N: <name>` heading from the plan as one discrete unit of work; derives `task_id` as `task-<N>-<kebab-case-name>` (e.g. `### Task 3: Tavily Service` → `task-3-tavily-service`) and records each task's line range up to the next `### Task` heading or EOF.
- **Task file initialization** — writes one `.loop-logs/tasks/<task-id>.json` per task: `task_id`, `plan`, `spec`, `status` (starts `"pending"`), `attempt` (starts `0`), `worktree` (starts `null`), `completed_steps` (starts `[]`). Each file is a self-contained work ticket any worktree agent reads to learn plan/spec paths, attempt count, and completed steps.
- **Resume behavior** — before writing a task file, checks whether it already exists with `"status": "completed"`; if so, skips that task entirely (no overwrite, no worktree agent spawned) — re-running the command is idempotent for finished tasks.
- `.loop-logs/tasks/`, `.loop-logs/logs/`, `.loop-logs/error/` are pre-existing (with `.gitkeep`) and must not be recreated.
- Prints a setup-complete summary listing discovered task IDs and the working branch.

### Stage 1 — Parallel Implementation
- All per-task worktree agents are spawned **simultaneously** via the Agent tool — never sequentially. Each agent runs an independent Karpathy mini-loop (`Propose → Implement (TDD) → Test → Verify signal`) inside its own isolated worktree (`git worktree add .worktrees/<task-id> -b worktree/<task-id>`).
- **Per-task steps:** read the task JSON (plan, spec, attempt, task_id) → read the task's own plan section plus the full spec for architectural context → append a short implementation plan as `## Attempt N — <ISO timestamp>` to `.loop-logs/logs/<task-id>.md` → implement TDD-style (write the failing test first, confirm it fails for the expected reason, then write minimal code to pass it) → run `just lint` then `just test-unit` as the verifiable signal, both must exit 0.
- **On pass** — append PASS output + `Outcome: success` to the log; set task JSON `status: "completed"`, `attempt: <N>`; commit in the worktree (`feat(<scope>): <task description>`); stop the loop.
- **On fail, attempt < 3** — append full lint/test output + one-line root cause to the log; increment `attempt`; retry from Propose.
- **On fail, attempt = 3 (hard stop)** — append `HARD STOP after 3 attempts`; write `.loop-logs/error/<task-id>.md` with task/plan/spec/attempts metadata, full output + `git diff` for all 3 attempts, and a reproduction snippet (`cd <worktree>; just lint; just test-unit`); set task JSON `status: "failed"`; commit partial work as `wip: failed <task-id> after 3 attempts`; stop.
- **Squash merge** — after every worktree agent finishes (success or hard-stop): for each `"completed"` task, `git merge --squash worktree/<task-id>`, commit `feat(<scope>): <task description>`, then `git worktree remove .worktrees/<task-id> --force` and `git branch -D worktree/<task-id>`. Failed tasks are excluded from the merge; their `wip:` commits remain on their own worktree branches for inspection, and a `FAILED: <task-id> — see .loop-logs/error/<task-id>.md` line is logged to `.loop-logs/logs/summary.md`.

### Stage 2 — Verification
- After squash-merge, the feature branch must pass runtime verification before review. Runs the `verifying-implementation` skill, which boots the system and exercises the changed endpoints/paths against the spec's acceptance criteria.
- On pass, proceeds to Stage 3.
- On fail — analyzes root cause, spawns a single fix worktree agent using the same TDD mini-loop as Stage 1 (`worktree/verification-fix-<round>`), squash-merges it (commit `fix: address verification failure round <round>`), removes the worktree/branch, and re-runs verification. Repeats up to 3 rounds total.
- After 3 failed rounds — writes `.loop-logs/error/verification-failure.md` with full output for all 3 rounds, commits `wip: verification failed after 3 rounds — see .loop-logs/error/verification-failure.md`, and stops.

### Stage 3 — Complex Review
- Delegated entirely to `/complex-review`: parallel review subagents (`enhanced-review` + `ponytail-review` + `simplify`) → a consolidation subagent validates and deduplicates findings → fixes applied in parallel worktrees, squash-merged back → re-verify with `verifying-implementation` → re-review until no issues remain.
- After complex-review completes, a summary (date, issues found, issues fixed, review rounds) is appended to `.loop-logs/logs/complex-review.md`.

### Stage 4 — Final Commit
- Step 4.1 — run `just lint` and `just format`; both must exit 0; fix issues before proceeding if not.
- Step 4.2 — write `.loop-logs/logs/summary.md` with plan/spec/branch/date, a per-task status/attempts table, completed/failed counts, verification round count, and review round count.
- Step 4.3 — `git add -A`; on full success commit `feat(<scope>): <description derived from plan Goal line>`; on partial failure commit `wip: partial — <completed>/<total> tasks completed` with failed task IDs and their error-log paths referenced in the body.

## `.loop-logs/` File Formats

- **Task file** (`.loop-logs/tasks/<task-id>.json`) — JSON with `task_id`, `plan`, `spec`, `status` (`pending | in_progress | completed | failed`), `attempt`, `worktree`, `completed_steps`.
- **Log file** (`.loop-logs/logs/<task-id>.md`) — one file per task; sections appended per attempt: `## Attempt N — <timestamp>`, `### Implementation plan`, `### Lint output`, `### Test output`, `### Outcome: failed — <reason>` (or success).
- **Error file** (`.loop-logs/error/<task-id>.md`) — written only on the 3rd failure; must contain enough detail to reproduce the failure: task description, plan path, spec path, attempt count (3), a `## Attempt N` section per attempt with full lint + test output and `git diff`, and a final `## Reproduction` section with exact commands to reproduce the failure state.

## Hard Rules

1. Never delete tests to make them pass.
2. One feature per commit — commits are atomic.
3. Always commit at the end, even if partial (`wip:` prefix for partial/failed work).
4. A verifiable signal must be green before advancing to the next stage.
5. Squash-merge only — never plain `git merge` on worktree branches.
6. If truly ambiguous, make a reasonable assumption and document it in a code comment.

## End-to-End Smoke Test

Task 4 of the plan verifies the command itself before shipping it:

- Creates a minimal `/tmp/test-plan.md` (single `### Task 1: Hello World` with failing-test-then-implementation steps for a trivial `hello()` function) and `/tmp/test-spec.md` with acceptance criteria `hello()` returns `"hello"`.
- Manually traces Stage 0 guard logic against a missing-file case (`nonexistent.md`), expecting `ERROR: Plan file not found: nonexistent.md`.
- Manually traces the branch-derivation logic for filename `2026-06-19-autonomous-feature-development-loop.md`, expecting derived branch `feature/autonomous-feature-development-loop`.
- Verifies task-parsing logic against the plan's own 4 `### Task N:` headings, expecting task IDs: `task-1-guard-and-setup`, `task-2-parallel-implementation-loop`, `task-3-stages-2-4-verification-complex-review-final-commit`, `task-4-end-to-end-smoke-test`.
- Runs `/enhanced-review` on the finished command file against the companion design spec, fixing any issues before the final commit `test(command): smoke test and enhanced-review fixes for autonomous dev loop`.

## Sources

- Autonomous Feature Development Loop — Implementation Plan — `docs/superpowers/plans/2026-06-19-autonomous-feature-development-loop.md`
- Autonomous Feature Development Loop — Design Spec — `docs/superpowers/specs/2026-06-19-autonomous-feature-development-loop-design.md`

## Related Topics

- [[git-worktrees]]
- [[multi-agent-architecture]]
- [[implementation-plan]]
