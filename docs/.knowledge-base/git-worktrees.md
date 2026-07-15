# Git Worktrees

Git worktrees give each parallel per-task agent in the autonomous feature development loop its own isolated working directory and branch, so simultaneous implementation work never collides.

## Key Concepts

- **Purpose** — isolation for parallel work: every task in Stage 1 of the autonomous loop runs simultaneously, each in its own git worktree, so agents can write files and run tests concurrently without stepping on each other's working directory.
- **Creation pattern** — `git worktree add .worktrees/<task-id> -b worktree/<task-id>`: creates a new worktree under `.worktrees/<task-id>` on a new branch `worktree/<task-id>`, checked out from the feature branch.
- **Fix-round worktrees follow the same pattern** — verification-failure fix loops and complex-review fix loops spawn worktrees the same way, e.g. branch `worktree/verification-fix-<round>`.
- **Squash-merge back, never plain merge** — once a worktree agent's task reaches `"completed"`, its branch is merged into the feature branch with `git merge --squash worktree/<task-id>` followed by a separate commit (e.g. `feat(<scope>): <task description>`); plain `git merge` on a worktree branch is a hard rule violation (never plain `git merge` on worktree branches).
- **Cleanup on success** — after a completed task's squash-merge lands, its worktree and branch are removed: `git worktree remove .worktrees/<task-id> --force` followed by `git branch -D worktree/<task-id>`.
- **Failed tasks are excluded and left for inspection** — a task that hard-stops after 3 attempts is *not* squash-merged; its worktree and branch are left in place so its `wip:` commit and full diff remain available for a developer to inspect, rather than being cleaned up.
- **Concurrency, not sequencing** — all per-task worktree agents are spawned simultaneously via the Agent tool, never sequentially; the worktree is what makes that simultaneity safe (each agent has its own checkout, so there is no shared working-directory state to race on).

## Sources

- Autonomous Feature Development Loop — Implementation Plan — `docs/superpowers/plans/2026-06-19-autonomous-feature-development-loop.md`
- Autonomous Feature Development Loop — Design Spec — `docs/superpowers/specs/2026-06-19-autonomous-feature-development-loop-design.md`

## Related Topics

- [[autonomous-feature-development-loop]]
- [[multi-agent-architecture]]
