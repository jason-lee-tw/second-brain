# Fix: don't send `temperature` to claude-sonnet-5 (API rejects it)

## Bug

`ClaudeAgent.__init__` in
`apps/backend/src/second_brain/nodes/base_node/agents/claude_agent.py`
unconditionally forwarded `temperature` (default `0.7`) to `ChatAnthropic(...)`.
The live Anthropic API rejects this outright for model id `"claude-sonnet-5"`
(`CLAUDE_MODEL_NAME.SONNET`, used by `SynthesisNode`):

```
anthropic.BadRequestError: Error code: 400 - {'type': 'error', 'error':
{'type': 'invalid_request_error', 'message': '`temperature` is deprecated
for this model.'}}
```

Confirmed live: a smoke-test POST to `/query` reached the `synthesis` node
and returned HTTP 500 with this exact error. Prior to the node-base-class
refactor, `synthesis.py` used a raw `ChatAnthropic(model="claude-sonnet-4-6")`
(a stale model string) that apparently didn't trip this. The refactor
correctly updated the model string to the current
`CLAUDE_MODEL_NAME.SONNET = "claude-sonnet-5"`, which exposed this
pre-existing API incompatibility. `CLAUDE_MODEL_NAME.HAIKU` (used by
`OrchestratorNode`, `MemoryAgentNode`, `IngestionAgentNode`) is NOT affected —
only Sonnet-5 rejects the parameter.

---

## Attempt 1

### Implementation Plan

1. Change `ClaudeAgent.__init__`'s `temperature` param to `float | None = 0.7`;
   only pass it to `ChatAnthropic(...)` when not `None`.
2. Update `SynthesisNode.__init__` to construct
   `ClaudeAgent(CLAUDE_MODEL_NAME.SONNET, temperature=None)`.
3. Leave `OrchestratorNode`, `MemoryAgentNode`, `IngestionAgentNode` untouched
   (still default to `temperature=0.7` via HAIKU).
4. Grep for any test asserting on `ClaudeAgent(CLAUDE_MODEL_NAME.SONNET)`
   call args — none found (searched `apps/backend/tests` for
   `ClaudeAgent(CLAUDE_MODEL_NAME` and `ChatAnthropic`); no test file existed
   for `claude_agent.py` prior to this fix, and `test_synthesis.py` mocks
   `_structured_llm` directly, never asserting on `ClaudeAgent` construction
   args. No existing test needed updating.

### Files Changed

- `apps/backend/src/second_brain/nodes/base_node/agents/claude_agent.py`
  — `temperature: float | None = 0.7`; branch on `is None` to build
  `ChatAnthropic(...)` with or without the `temperature` kwarg (explicit
  if/else, not a kwargs-dict splat — see Key Decisions).
- `apps/backend/src/second_brain/nodes/synthesis.py`
  — `ClaudeAgent(CLAUDE_MODEL_NAME.SONNET, temperature=None)`.
- `apps/backend/tests/unit/test_nodes/test_claude_agent.py` (new)
  — 3 unit tests (see below).

### New Tests

`apps/backend/tests/unit/test_nodes/test_claude_agent.py`:

- `test_claude_agent_omits_temperature_when_none` — `ClaudeAgent(SONNET,
  temperature=None)` must call `ChatAnthropic` WITHOUT a `temperature` kwarg
  at all (not even `temperature=None`) — regression guard for the exact bug.
- `test_claude_agent_defaults_temperature_to_0_7` — `ClaudeAgent(HAIKU)` with
  no explicit temperature still passes `temperature=0.7` (HAIKU nodes must be
  unaffected).
- `test_claude_agent_forwards_explicit_temperature` — an explicit non-None
  temperature (e.g. `0.2`) is still forwarded as-is.

Confirmed RED first: ran `just test-unit` against the unfixed source —
`test_claude_agent_omits_temperature_when_none` failed with
`AssertionError: assert 'temperature' not in {..., 'temperature': None, ...}`
(211 other tests passed). This proves the test would have caught the bug
(the original bug forwarded `temperature=0.7` unconditionally; this
regression test specifically guards against forwarding the key at all when
`None`).

### Key Decisions

- **Explicit if/else over a kwargs-dict splat.** First attempt built
  `extra_kwargs = {} if temperature is None else {"temperature": temperature}`
  and called `ChatAnthropic(**extra_kwargs, ...)`. This passed lint and unit
  tests but **failed `just type-check`** with ~20 pyright errors: pyright
  inferred `extra_kwargs: dict[str, float]` and, when splatting `**extra_kwargs`
  into `ChatAnthropic(...)`, treated every one of `ChatAnthropic`'s many
  optional kwargs as if it could receive a `float`, producing bogus
  "float is not assignable to X" errors across unrelated parameters
  (`default_headers`, `betas`, `model_kwargs`, `streaming`, `thinking`,
  `mcp_servers`, `context_management`, ...). Switched to two explicit
  `ChatAnthropic(...)` call sites (one per branch, each with fully literal
  kwargs) — this type-checks cleanly since pyright can match each kwarg to
  its exact parameter type without going through an ambiguous splat.
- Did not touch `OrchestratorNode`, `MemoryAgentNode`, `IngestionAgentNode` —
  all three use `CLAUDE_MODEL_NAME.HAIKU` and keep the default
  `temperature=0.7`, matching HAIKU's continued support for the parameter.

### Lint Output

```
$ just lint
All checks passed!
```

### Type-Check Output

```
$ just type-check
🔄 Type checking...
... (9 pre-existing informational notes in ingestion_agent.py,
     memory_persistence.py, memory_retrieval.py — unrelated files,
     not touched by this fix)
0 errors, 0 warnings, 9 notes
✅ Type check is completed
```

### Test Output

```
$ just test-unit
... 212 passed, 2 warnings in 1.29s
```

(212 = 209 pre-existing + 3 new `test_claude_agent.py` tests; no existing
test needed modification since none asserted on `ClaudeAgent` construction
args.)

### Live E2E Verification

This bug is only reproducible against the LIVE Anthropic API (unit tests
mock `ChatAnthropic` entirely — the SDK-level `temperature` rejection never
reaches a mock). `docker ps` confirms the backend container
(`ai-learning-milestone-backend-1`) is already running from a prior
verification round, but this worktree's source changes are NOT baked into
that running image (worktrees are separate checkouts; the container was
built from a different tree). Rebuilding+re-curling now would test stale-vs-
running-image mismatch, not this fix.

**Scope of this task**: verify the source fix is correct via unit tests +
code inspection (done above, all green). A live rebuild
(`docker compose up --build`) + `curl -X POST localhost:3001/query` smoke
test re-verification is deferred to a separate step after this branch is
merged into the integration branch, per the task instructions.

### Commit

```
fix: don't send temperature to claude-sonnet-5 (API rejects it)
```

### Outcome

PASS on attempt 1. All of lint, type-check, and test-unit are green.
Source-level fix verified; live re-verification deferred to post-merge step
as instructed.
