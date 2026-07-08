# Fix: stale `_structured_llm` patch target in test_synthesis_awaiting.py

## Issue

A prior task ("Task 10: Convert synthesis.py to SynthesisNode") converted
`apps/backend/src/second_brain/nodes/synthesis.py`'s module-level `_structured_llm`
singleton into an instance attribute on `synthesize_answer` (a `SynthesisNode`
instance). Its own test file `test_synthesis.py` was updated with the new patch
target, but a sibling test file,
`apps/backend/tests/unit/test_nodes/test_synthesis_awaiting.py`, was missed — it
still patches the old stale target `second_brain.nodes.synthesis._structured_llm`,
which no longer exists as a module-level name. This causes 2 test failures:

- `test_synthesis_sets_is_uncertain_when_low_confidence`
- `test_synthesis_sets_is_uncertain_false_when_confident`

Both fail with:
`AttributeError: <module 'second_brain.nodes.synthesis' ...> does not have the attribute '_structured_llm'`

## Fix

In `apps/backend/tests/unit/test_nodes/test_synthesis_awaiting.py`, replace both
occurrences of:

```python
with patch("second_brain.nodes.synthesis._structured_llm") as mock_llm:
```

with:

```python
with patch("second_brain.nodes.synthesis.synthesize_answer._structured_llm") as mock_llm:
```

No other lines in this file should change.

## Attempt 1

- Applied the exact fix: replaced both occurrences of
  `patch("second_brain.nodes.synthesis._structured_llm")` with
  `patch("second_brain.nodes.synthesis.synthesize_answer._structured_llm")`
  (single-line form, matching the exact wording given).
- Ran `uv run --package second-brain pytest apps/backend/tests/unit/test_nodes/test_synthesis_awaiting.py -v`
  (first had to `uv sync --all-extras` since `pytest` binary was missing from the
  worktree's fresh `.venv`). Result: both target tests **PASSED**.
- Ran `just lint && just type-check && just test-unit`. `just lint` **FAILED**:
  `ruff` reported `E501 Line too long (91 > 88)` on both edited lines (the
  single-line `with patch(...)` form exceeds the project's 88-char line limit).
- Outcome: FAIL (lint). Full test suite and type-check not reached.

## Attempt 2

- Reformatted the two `with patch(...)` statements to the multi-line form
  already used identically elsewhere in the sibling file
  `test_synthesis.py` (11 occurrences use this exact 3-line style for the
  same patch target string):
  ```python
  with patch(
    "second_brain.nodes.synthesis.synthesize_answer._structured_llm"
  ) as mock_llm:
  ```
  No other content changed — this is purely a line-wrap of the same string
  the task specified, needed to satisfy the repo's line-length lint rule.
- Ran `just lint && just type-check && just test-unit`:
  - `just lint`: **All checks passed!**
  - `just type-check`: **0 errors, 0 warnings, 9 notes** (all 9 informational
    notes are pre-existing `reportUnknownArgumentType` notes in unrelated
    files — `ingestion_agent.py`, `memory_persistence.py`, `memory_retrieval.py`
    — not touched by this change).
  - `just test-unit`: **209 passed**, including both previously-failing tests
    in `test_synthesis_awaiting.py`.
- Outcome: PASS. Committed with message
  `fix: update stale _structured_llm patch target in tests` (commit `bac77ce`
  on branch `worktree/fix-test_synthesis_awaiting-patch-targets`) — shortened
  from the originally-requested message because the commit-msg hook enforces
  a 72-char subject limit and the requested subject was 73 chars.
