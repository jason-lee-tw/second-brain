# Autonomous Feature Development Loop — Implementation Plan

Source: docs/superpowers/plans/2026-06-19-autonomous-feature-development-loop.md
Primary-Topic: autonomous-feature-development-loop
Secondary-Topics: git-worktrees, test-driven-development

## Key Concepts

- **Goal:** Rewrite `.claude/command/autonomous-feature-development.md` to implement the full "Karpathy Loop" — parallel worktrees per task, a 3-retry guard, a verifying-implementation gate, complex-review delegation, squash-merge linear history, and a `.loop-logs/` audit trail.
- **Architecture:** The command is a Claude Code prompt file (markdown), not a script. Invoked as `claude -p "/autonomous-feature-development <plan.md> <spec.md>"`. Claude reads the command, parses `$ARGUMENTS`, and orchestrates the loop itself using the Agent tool, git worktrees, and existing skills — no Python/shell orchestration scripts.
- **Tech stack referenced:** Claude Code command (markdown prompt), git worktrees, `just lint` / `just test-unit` / `just format`, skills `verifying-implementation`, `complex-review`, `enhanced-review`.
- **Global constraints:**
  - Command file lives at `.claude/command/autonomous-feature-development.md`.
  - `.loop-logs/tasks/`, `.loop-logs/logs/`, `.loop-logs/error/` already exist (with `.gitkeep`) — do not recreate.
  - Task JSON schema is fixed: `task_id`, `plan`, `spec`, `status`, `attempt`, `worktree`, `completed_steps`.
  - Branch naming derived from plan filename: strip leading `YYYY-MM-DD-` date prefix and `.md` suffix, prepend `feature/` (e.g. `2026-06-16-ticket-3-ingestion.md` → `feature/ticket-3-ingestion`).
  - Squash-merge only, per `.claude/rules/git-linear-history.md`.
  - Max 3 retries per task; max 3 verification rounds.
  - Commit convention: `feat(scope): description` on full success; `wip: partial — N/total tasks completed` on partial failure.
- **Task 1 — Stage 0: Guard & Setup**
  - Parses `$ARGUMENTS` into `plan_path` and `spec_path` (split on whitespace).
  - Validates each file exists and is non-empty; on any failure prints a named-file `ERROR:` message and stops immediately (e.g. `ERROR: Plan file not found: <plan_path>`, `ERROR: Plan file is empty: <plan_path>`, equivalent for spec).
  - Branch guard: runs `git rev-parse --abbrev-ref HEAD`; if on `main`, derives a feature branch name from the plan filename (strip date + `.md`, prepend `feature/`) and runs `git checkout -b <branch-name>`; otherwise continues on the current branch.
  - Parses every `### Task N: <name>` heading in the plan file, derives `task_id` as `task-<N>-<kebab-case-name>` (e.g. `### Task 3: Tavily Service` → `task-3-tavily-service`), and records each task's line range up to the next `### Task` heading or EOF.
  - Writes one `.loop-logs/tasks/<task-id>.json` per task with `status: "pending"`, `attempt: 0`, `worktree: null`, `completed_steps: []`, plus `plan`/`spec` paths.
  - **Resume behavior:** before writing a task file, checks whether it already exists with `"status": "completed"` — if so, skips that task entirely (no overwrite, no worktree agent spawned).
  - Prints a setup-complete summary listing discovered task IDs and the working branch.
- **Task 2 — Stage 1: Parallel Implementation Loop**
  - All per-task worktree agents are spawned **simultaneously** via the Agent tool — never sequentially. Each agent receives its `task_id` and the path to its task JSON file.
  - Per-task agent steps:
    - **Step A:** Read `.loop-logs/tasks/<task-id>.json`, extracting `plan`, `spec`, `attempt`, `task_id`.
    - **Step B:** Create an isolated worktree: `git worktree add .worktrees/<task-id> -b worktree/<task-id>`; update task JSON to `status: "in_progress"` and set `worktree` path.
    - **Step C:** Read the task's own section from the plan (from its `### Task N:` heading to the next, or EOF) plus the full spec file for architectural context.
    - **Step D — TDD loop, max 3 attempts:**
      - Before each attempt, append an `## Attempt <N> — <ISO timestamp>` block with a 3-5 bullet implementation plan to `.loop-logs/logs/<task-id>.md`.
      - Implement TDD-style: write the failing test first (confirm it fails for the expected reason), then write minimal code to pass it.
      - Run verifiable signals in order: `just lint` then `just test-unit`; both must exit 0.
      - **On pass:** append PASS outputs + `Outcome: success` to the log; set task JSON `status: "completed"`, `attempt: <N>`; commit in the worktree (`git add -A && git commit -m "feat(<scope>): <task description>"`); stop the loop.
      - **On fail, attempt < 3:** append full lint/test output + one-line root cause to the log; increment `attempt` in task JSON; loop again.
      - **On fail, attempt = 3 (hard stop):** append `HARD STOP after 3 attempts` to the log; write `.loop-logs/error/<task-id>.md` containing task/plan/spec/attempts metadata, full output + `git diff` for all 3 attempts, and a reproduction snippet (`cd <worktree>; just lint; just test-unit`); set task JSON `status: "failed"`; commit partial work as `wip: failed <task-id> after 3 attempts`; stop.
  - **Squash merge (after all agents finish):** wait for every worktree agent to reach success or hard-stop. For each `"completed"` task: `git merge --squash worktree/<task-id>`, commit as `feat(<scope>): <task description>`, then `git worktree remove .worktrees/<task-id> --force` and `git branch -D worktree/<task-id>`. For each `"failed"` task: do NOT merge; instead log `FAILED: <task-id> — see .loop-logs/error/<task-id>.md` to `.loop-logs/logs/summary.md`.
- **Task 3 — Stages 2-4: Verification, Complex Review, Final Commit**
  - **Stage 2 (Verification):** run the `verifying-implementation` skill, which boots the system and exercises changed endpoints/paths against `spec_path`'s acceptance criteria.
    - On pass, proceed to Stage 3.
    - On fail: analyze root cause, spawn a single fix worktree agent using the same TDD mini-loop as Stage 1 targeting the root cause, squash-merge it (`worktree/verification-fix-<round>`, commit `fix: address verification failure round <round>`, remove worktree/branch), then re-run verification. Repeat up to 3 rounds total.
    - After 3 failed rounds: write `.loop-logs/error/verification-failure.md` with full output for all 3 rounds, commit `wip: verification failed after 3 rounds — see .loop-logs/error/verification-failure.md`, and stop.
  - **Stage 3 (Complex Review):** run the `/complex-review` command on the current feature branch; append a summary (date, issues found, issues fixed, review rounds) to `.loop-logs/logs/complex-review.md`.
  - **Stage 4 (Final Commit):**
    - Step 4.1: run `just lint` and `just format`, both must exit 0; fix issues before proceeding if not.
    - Step 4.2: write `.loop-logs/logs/summary.md` with plan/spec/branch/date, a per-task status/attempts table, completed/failed counts, verification round count, and review round count.
    - Step 4.3: `git add -A`; on full success commit `feat(<scope>): <description derived from plan Goal line>`; on partial failure commit `wip: partial — <completed>/<total> tasks completed` body listing failed task IDs and their error-log paths.
  - **Hard Rules** (apply throughout): never delete tests to make them pass; one feature per commit (atomic); always commit at the end even if partial (`wip:` prefix); a verifiable signal must be green before advancing to the next stage; squash-merge only, never plain `git merge` on worktree branches; if truly ambiguous, make a reasonable assumption and document it in a code comment.
- **Task 4 — End-to-End Smoke Test**
  - Creates a minimal `/tmp/test-plan.md` (single `### Task 1: Hello World` with failing-test-then-implementation steps for a trivial `hello()` function) and `/tmp/test-spec.md` with acceptance criteria `hello()` returns `"hello"`.
  - Manually traces Stage 0 guard logic against a missing-file case (`nonexistent.md`) expecting `ERROR: Plan file not found: nonexistent.md`.
  - Manually traces the branch-derivation logic for filename `2026-06-19-autonomous-feature-development-loop.md`, expecting derived branch `feature/autonomous-feature-development-loop`.
  - Verifies task-parsing logic against the plan's own 4 `### Task N:` headings, expecting task IDs: `task-1-guard-and-setup`, `task-2-parallel-implementation-loop`, `task-3-stages-2-4-verification-complex-review-final-commit`, `task-4-end-to-end-smoke-test`.
  - Runs `/enhanced-review` on the finished command file against the companion spec `docs/superpowers/specs/2026-06-19-autonomous-feature-development-loop-design.md`, fixing any issues before the final commit `test(command): smoke test and enhanced-review fixes for autonomous dev loop`.
- **Operating Mode of the resulting command:** FULLY AUTONOMOUS — does not pause or ask questions; on true ambiguity, makes a reasonable assumption and documents it in a code comment.
- Each of the plan's four tasks follows the same "review-check-first" TDD-for-prompts pattern: write a checklist before authoring content, author/append the content, verify it against the checklist and fix gaps inline, then commit.
