# Task I4 Log: Correct stale OTEL spec claims post-delivery

## Task Context

### Finding (2 of 3 reviewers)

`docs/superpowers/specs/2026-07-15-otel-tracing-coverage-fix.md` contains factual
claims that don't match the actual delivered/verified implementation:

1. Line ~55-67 (the "Instrument the raw drivers in `setup_tracing()`" section) states:
   "call each instrumentor's `.instrument()` with no arguments (all four patch at the
   class level... so it doesn't matter whether pools/engines/clients were constructed
   before or after this call)". This is factually wrong for SQLAlchemy: live
   verification found `SQLAlchemyInstrumentor().instrument()` called bare produces
   ZERO per-statement spans for `db/session.py`'s module-level `engine` singleton
   (constructed before `setup_tracing()` runs) — it required
   `SQLAlchemyInstrumentor().instrument(engine=engine)` instead. The actual shipped
   code (`apps/backend/src/second_brain/observability/tracing.py`) already reflects
   the correct behavior; only the spec's prose is stale.
2. Line ~51 states "All four verified present on PyPI at `0.64b0`" — the actual
   resolved/pinned version in `apps/backend/pyproject.toml`/`uv.lock` is `>=0.63b1`
   (resolves to `0.63b1`).
3. The companion plan lists `redact_inbound`/`redact_outbound` as nodes that should be
   wrapped with `trace_node` and should appear as spans in Phoenix. The actual,
   verified-correct implementation deliberately leaves them unwrapped: both are
   synchronous (`def __call__`, not `async def`) and do pure in-memory regex PII
   redaction with no I/O.

### Scope

Edit `docs/superpowers/specs/2026-07-15-otel-tracing-coverage-fix.md` only. Do not
touch the plan file (historical execution record). Documentation-only fix — no
product code changes, no lint/test applicable.

### Acceptance Criteria
- AC-1: Section 2 ("Instrument the raw drivers...") corrected to state the actual
  verified behavior — 3 of 4 instrumentors are class-level patches where construction
  order doesn't matter; SQLAlchemy requires `engine=<instance>` explicitly. Code
  snippet updated to `SQLAlchemyInstrumentor().instrument(engine=engine)`.
- AC-2: "0.64b0" claim corrected to the actual pinned/resolved version, confirmed by
  reading `uv.lock`/`pyproject.toml` directly (not trusting the prompt).
- AC-3: New "## Implementation Notes (post-delivery)" section added before "## Out of
  Scope", documenting (a) `redact_inbound`/`redact_outbound` deliberately unwrapped,
  with reason, and (b) the SQLAlchemy `engine=` requirement with a pointer to
  `.loop-logs/2026-07-15-otel-tracing-coverage-fix/verifications/verification-1.md`.

---

## Attempt 1 — 2026-07-15T07:59:02Z

### Implementation Plan
- Read the spec file in full to locate the three stale claims precisely.
- Verify the actual shipped code in `apps/backend/src/second_brain/observability/tracing.py`
  confirms the `engine=engine` behavior (it does, with an inline comment already
  explaining the root cause).
- Verify the actual resolved version by grepping `uv.lock` and `pyproject.toml` directly
  rather than trusting the finding's claim of `>=0.63b1` — confirmed: all four
  packages pinned `>=0.63b1` in `apps/backend/pyproject.toml`, resolved to exactly
  `0.63b1` in `uv.lock` (repo-root `uv.lock`, single workspace lockfile).
- Verify `redact_inbound`/`redact_outbound` are sync, no-I/O, and where they're
  defined — found both in `apps/backend/src/second_brain/nodes/pii_redaction.py`
  (`RedactInboundNode`/`RedactOutboundNode`, `def __call__`, not `async def`).
- Apply three surgical edits to the spec: (1) rewrite Section 2's prose + code
  snippet, (2) fix the PyPI version claim, (3) insert a new "Implementation Notes
  (post-delivery)" section before "## Out of Scope".
- Leave the plan file (`docs/superpowers/plans/2026-07-15-otel-tracing-coverage-fix.md`)
  untouched per instructions — plans are historical execution records.

### Files Changed
- modified `docs/superpowers/specs/2026-07-15-otel-tracing-coverage-fix.md` — corrected
  stale SQLAlchemy-instrumentation claim + code snippet, corrected PyPI version claim
  from `0.64b0` to `0.63b1`, added "Implementation Notes (post-delivery)" section
  covering the `redact_inbound`/`redact_outbound` exception and the SQLAlchemy
  `engine=` requirement with a pointer to `verification-1.md`.

### New Tests
(none — documentation-only change, no test surface)

### Key Decisions
- Kept the finding's claim of `>=0.63b1` but verified it independently against
  `apps/backend/pyproject.toml` (specifier) and the repo-root `uv.lock` (resolved
  version) rather than accepting it at face value — both confirm `0.63b1` exactly for
  all four instrumentation packages (httpx, asyncpg, sqlalchemy, psycopg).
- Named the file where `redact_inbound`/`redact_outbound` are defined explicitly
  (`nodes/pii_redaction.py`) after discovering both classes (`RedactInboundNode`,
  `RedactOutboundNode`) live in one shared file, not two separate files as a naive
  guess from the names might suggest — checked via `grep` before writing the prose.
- Did not touch the plan file's Task 3 snippet or Task 5 checklist per explicit
  instruction — corrections belong only in the living spec doc.

### Lint Output
n/a — documentation-only change, no lint target

### Test Output
n/a — documentation-only change, no test target

### Commit
`99b9c29`

### Outcome: success
