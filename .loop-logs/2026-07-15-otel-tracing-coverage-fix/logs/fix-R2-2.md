# Task R2-2 Log: Add post-delivery correction notes to plan file (docs-only)

## Task Context

### Plan Section
Round 2 review finding R2-2 (this is a review-fix task, not an original plan task).
Prior round (round 1, finding I4) flagged that both
`docs/superpowers/specs/2026-07-15-otel-tracing-coverage-fix.md` AND
`docs/superpowers/plans/2026-07-15-otel-tracing-coverage-fix.md` contained stale
claims contradicting the actual, live-verified implementation. The round-1 fix
(commit `6d51652`) only corrected the SPEC file. Two independent round-2 reviewers
found the PLAN file was never touched and still contains, verbatim:

1. Around plan line 217 (Task 2, Step 4, "to:" code block) — the pre-fix
   `SQLAlchemyInstrumentor().instrument()` call with no `engine=` kwarg. This is the
   exact bug fixed in the real code (commit `90fdcde`).
2. Around plan lines 340-366 (Task 3, Step 3, "to:" code block) — instructs wrapping
   `redact_inbound`/`redact_outbound` in `trace_node`. The shipped `query_graph.py`
   deliberately does NOT do this (both nodes are sync, no I/O — wrapping would raise
   `TypeError`).
3. Around plan lines 512-518 (Task 5, Step 4, manual E2E verification checklist) —
   lists `redact_inbound`/`redact_outbound` among expected named node spans in
   Phoenix and instructs debugging Tasks 1-4 if any listed span is missing.

### Acceptance Criteria
- AC-1: Immediately after the Task 2 "to:" code block containing the bare
  `SQLAlchemyInstrumentor().instrument()` call, add a clearly-marked correction note
  stating the call is insufficient (needs `engine=engine`) and pointing to the spec's
  "Implementation Notes" section.
- AC-2: Immediately after the Task 3 "to:" code block wrapping
  `redact_inbound`/`redact_outbound`, add a clearly-marked correction note stating the
  shipped implementation deliberately excludes these two nodes, pointing to the same
  spec section.
- AC-3: In the Task 5 Step 4 manual-verification checklist, add an inline note next to
  the `redact_inbound`/`redact_outbound` bullet clarifying they are deliberately
  excluded and won't appear.
- AC-4: Every edit is a clearly-marked addition (blockquote/correction note) — no
  silent rewrite of original plan text. No other file touched.

---

## Attempt 1 — 2026-07-16T00:00:00Z

### Implementation Plan
- Read the current plan file in full to get exact line numbers/context (they had
  shifted slightly from the finding's cited numbers — e.g. bare-instrument call is at
  line 217, redact wrapping block ends at line 366, checklist bullet is at line 513).
- Read the spec file's "Implementation Notes (post-delivery)" section (spec lines
  157-168) and the SQLAlchemy `engine=` fix detail (spec line ~65) to quote them
  accurately in the correction notes rather than paraphrasing loosely.
- Insert 3 blockquote-style `> **Post-delivery correction:**` notes as pure additions
  (no existing line deleted or altered), each pointing back to the spec's
  Implementation Notes section.
- Verify via `git diff` that the change is purely additive (no `-` lines except diff
  context).

### Files Changed
- modified `docs/superpowers/plans/2026-07-15-otel-tracing-coverage-fix.md` — added
  three post-delivery correction blockquotes (Task 2 SQLAlchemy `engine=` gap, Task 3
  redact_inbound/outbound exclusion, Task 5 checklist inline note); no original plan
  text removed or edited.

### New Tests
(none — documentation-only change, no test suite applies)

### Key Decisions
- Used blockquote (`>`) formatting consistently for all three notes, matching the
  style the task instructions suggested, so they're visually distinct from the
  original numbered-step prose and unmistakably additions rather than part of the
  original instructions.
- For the Task 5 checklist, nested the note as an indented sub-bullet directly under
  the `redact_inbound`/... bullet (rather than a top-level line after the whole list)
  so it reads as attached to that specific bullet, not a general list-level caveat.
- Did not edit the "If any of these are missing, that's a real gap" sentence further
  down — the inline note on the bullet itself already resolves the contradiction (a
  reader will see the exclusion note before reaching the "go debug" sentence), and
  editing that sentence would drift toward "silent rewrite" rather than "clearly
  marked addition."
- Quoted the spec's actual root-cause wording (bare `.instrument()` only patches
  `create_engine()`/`Engine.connect()` at class level; `engine` is a module-level
  singleton created before `setup_tracing()` runs) rather than a generic "this was
  wrong" note, so the correction is self-contained and doesn't require opening the
  spec to understand *why*.

### Diff Summary
```
docs/superpowers/plans/2026-07-15-otel-tracing-coverage-fix.md | 27 ++++++++++++++++++++++
1 file changed, 27 insertions(+)
```
All three hunks are pure insertions (`+` lines only, verified via `git diff` — no `-`
lines present other than diff context markers). This satisfies "clearly-marked
addition, not silent rewrite."

### Lint Output
n/a — documentation-only change, no lint target applies (markdown, not linted by
`just lint` which is `ruff check` scoped to Python).

### Test Output
n/a — no test suite applies to a markdown plan file.

### Commit
`fec170d`

### Outcome: success
