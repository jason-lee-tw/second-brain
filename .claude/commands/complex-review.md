---
description: Run complex code review with subagents and multiple code review skills. Then run loop to fix the issues in parallel.
---

# Stage 1: Code review

Spawn multiple subagents (using Sonnet[1m]) to do code review.
Each subagent will code review with a skill: /enhanced-review /ponytail:ponytail-review /simplify . All these agent should work independently and in parallel.

All these subagent should pass the code review result to a consilidate subagent, this subagent should verify if the issues brought up are valid, then consolidate all valid issues into a report for you to analyse and plan for the fixes.

# Stage 2: Fix issues raised

Proceed to fix all issues with subagent driven development.

- Do handle all issues in parallel with subagents.
- Using gitworktree to avoid edit conflict.

## Issue resolving loop

1. Analyse the issue.
   - Understand the impact and root cause of the issue.
2. Think of the implementation plan.
3. Review the plan with /enhanced-review skill.
4. React on the review result:
   a. [No issue] Start executing the plan.
   b. [Issues raised] go to step 2 to plan again according to the review result.
5. Code review with /enhanced-review skill.
6. Test and verify the work is actually done.
7. React on the review result:
   a. [No issue] Task completed.
   b. [Issues raised] go to step 2 to plan again according to the review result.

### Rules for the loop

- DO NOT let an agent to complete all steps.
- MUST follow CLAUDE.md instructure about marking a task done.
