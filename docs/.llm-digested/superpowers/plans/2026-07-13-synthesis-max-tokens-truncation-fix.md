# Synthesis max_tokens Truncation Fix Implementation Plan

Source: docs/superpowers/plans/2026-07-13-synthesis-max-tokens-truncation-fix.md
Primary-Topic: synthesis-max-tokens-truncation
Secondary-Topics: known-issues, query-graph

## Key Concepts

- Goal: stop `POST /query` from returning HTTP 500 when the synthesis LLM completion is truncated by `max_tokens` before a required structured-output field is written; also fix the identical latent defect in `MemoryAgentNode` in the same pass.
- Root cause shape: Anthropic's tool-use `required` schema fields are advisory only — a completion truncated by `max_tokens` can omit a required field, which `PydanticToolsParser` surfaces as a `pydantic.ValidationError`, previously uncaught and propagating to a 500.
- Architecture: add one shared retry helper, `BaseAgentNode._ainvoke_structured`, that wraps a structured-output `Runnable`'s `.ainvoke()` call and retries exactly once on `pydantic.ValidationError`.
- Both `SynthesisNode` and `MemoryAgentNode` route their existing single `.ainvoke(prompt)` call through this shared helper instead of calling `.ainvoke` directly.
- Both nodes raise their `ClaudeAgent`'s `max_tokens` from the library default (1024) to 4096 at the `ClaudeAgent(...)` construction call site, so truncation becomes rare in the first place; the retry helper absorbs the residual case where truncation still happens.
- Tech stack for this fix: Python 3.13, LangChain / LangChain-Anthropic (`with_structured_output`), Pydantic v2, pytest + pytest-asyncio.
- Global constraints: `just format`, `just lint`, `just type-check`, `just test-unit` must all pass with no errors/warnings before any task is considered done (per project CLAUDE.md "Done Means"); strict TDD (failing test before implementation) for every task; catch `pydantic.ValidationError` specifically — never a broad `except Exception` (per project CLAUDE.md "no broad excepts"); `max_tokens` changes are scoped per-node at `ClaudeAgent(...)` construction call sites only, and `ClaudeAgent`'s own default-handling logic in `claude_agent.py` is explicitly NOT modified, so unrelated call sites (`IngestionAgentNode`'s `max_tokens=150`, `OrchestratorNode`'s unset default) remain unaffected; 2-space indentation matching the rest of `apps/backend/src`.
- Task 1 — `BaseAgentNode._ainvoke_structured` retry helper:
  - Modifies `apps/backend/src/second_brain/nodes/base_node/base_agent_node.py`; adds new test file `apps/backend/tests/unit/test_nodes/test_base_agent_node.py`.
  - New interface: `BaseAgentNode._ainvoke_structured[T](self, structured_llm: Runnable[LanguageModelInput, T], prompt: str) -> T` — an async instance generic method, called by Tasks 2 and 3 as `await self._ainvoke_structured(self._structured_llm_attr, prompt)`.
  - Implementation: try `await structured_llm.ainvoke(prompt)`; on `ValidationError`, retry once with `await structured_llm.ainvoke(prompt)` again; a second `ValidationError` propagates (is not swallowed).
  - `BaseAgentNode` is a generic ABC parameterized by `[InputStateType, ResultStateType]`, holds `_agent: BaseAgent`, and declares abstract `__call__`.
  - Test coverage: (1) successful first call returns result without a second call; (2) a `ValidationError` on first call triggers exactly one retry and returns the retried result; (3) two consecutive `ValidationError`s propagate instead of being swallowed (call count == 2 in all cases).
  - Commit message for this task: "fix: retry structured-output parse once on truncated ValidationError".
- Task 2 — Wire `SynthesisNode`:
  - Modifies `apps/backend/src/second_brain/nodes/synthesis.py` at line 45 (constructor) and line 104 (the `.ainvoke` call site); test file `apps/backend/tests/unit/test_nodes/test_synthesis.py`.
  - Constructor change: `ClaudeAgent(CLAUDE_MODEL_NAME.SONNET, temperature=None)` becomes `ClaudeAgent(CLAUDE_MODEL_NAME.SONNET, temperature=None, max_tokens=4096)`.
  - Call-site change: `await self._structured_llm.ainvoke(prompt)` becomes `await self._ainvoke_structured(self._structured_llm, prompt)`.
  - New regression tests reference `docs/bugs/004-synthesis-max-tokens-truncation.md` explicitly as the bug this closes: `test_synthesis_node_sets_max_tokens_4096` (asserts `ChatAnthropic` is constructed with `max_tokens=4096`) and `test_synthesize_answer_retries_once_when_structured_output_is_truncated` (mocks `_structured_llm.ainvoke` to raise a real `ValidationError` from `_SynthesisOutput.model_validate({"final_answer": "partial", "confidence": 0.75})` — i.e. missing the required `reasoning` field — then succeed on retry, asserting `call_count == 2` and the final answer is the retried one).
  - Regression check: full unit suite (`uv run pytest tests/unit -v`) must still pass after this change.
  - Commit message: "fix: raise SynthesisNode max_tokens to 4096 and retry truncated output".
- Task 3 — Wire `MemoryAgentNode`:
  - Modifies `apps/backend/src/second_brain/nodes/memory_agent.py` at line 37 (constructor) and line 99 (the `.ainvoke` call site); test file `apps/backend/tests/unit/test_nodes/test_memory_agent.py`.
  - Constructor change: `ClaudeAgent(CLAUDE_MODEL_NAME.HAIKU)` becomes `ClaudeAgent(CLAUDE_MODEL_NAME.HAIKU, max_tokens=4096)`.
  - Call-site change: `await self._llm.ainvoke(prompt)` becomes `await self._ainvoke_structured(self._llm, prompt)`.
  - This is described as "the identical latent defect shape" as the synthesis bug (required `MemoryAgentOutput.case` field, no `max_tokens` override) — fixed proactively even though it has not been observed to truncate in production yet.
  - New test: `test_memory_agent_node_sets_max_tokens_4096`.
  - Regression check after this task explicitly must include `test_ingestion_agent_node_caps_max_tokens_at_150` (proves `IngestionAgentNode`'s unrelated `max_tokens=150` call site stayed untouched) plus every existing `test_memory_agent.py` / `test_synthesis.py` case (proves the happy path through `_ainvoke_structured` behaves identically to the old direct `.ainvoke` call).
  - Commit message: "fix: raise MemoryAgentNode max_tokens to 4096 and retry truncated output".
- Task 4 — Runtime verification and bug-doc closeout:
  - Modifies `docs/bugs/004-synthesis-max-tokens-truncation.md` (its `## Fix` section).
  - Full workspace verification: `just format && just lint && just type-check && just test-unit` must all pass with no errors/warnings.
  - Boot the backend via `just up-all`; confirm health check (e.g. `curl -s localhost:3001/health`) succeeds.
  - Replay the exact original repro curl from the bug doc: `POST http://localhost:3001/query` with body `{"message": "What is the bug causing the endpoint POST /query keep failing from responding to user?", "sessionId": null}`; expected result is now HTTP 200 with an `answer`/`confidence` JSON body instead of a 500.
  - Updates the bug doc's `## Fix` section from "Not yet implemented — see spec" to a completed-fix description referencing both the spec (`docs/superpowers/specs/2026-07-13-synthesis-max-tokens-truncation-fix.md`) and this plan, summarizing the `max_tokens=4096` change and the `_ainvoke_structured` retry-once behavior, and stating the repro curl was verified to return 200 against a fresh backend.
  - Commit message: "docs: close out synthesis max_tokens truncation bug".
- This plan is explicitly linked to a prior spec document at `docs/superpowers/specs/2026-07-13-synthesis-max-tokens-truncation-fix.md` and to the bug report at `docs/bugs/004-synthesis-max-tokens-truncation.md`, which this plan's Task 4 closes out.
- Recommended execution sub-skills for agentic workers implementing this plan: `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans`, using checkbox (`- [ ]`) syntax for step tracking.
