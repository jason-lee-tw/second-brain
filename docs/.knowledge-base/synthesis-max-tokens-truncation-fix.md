# Synthesis max_tokens Truncation Fix

`POST /query` intermittently returned HTTP 500 when a verbose synthesis completion was truncated by Anthropic's default `max_tokens=1024`, cutting off the model before it wrote `_SynthesisOutput`'s required `reasoning` field — fixed by raising `max_tokens` to 4096 on `SynthesisNode`/`MemoryAgentNode` and adding a shared retry-once helper on `BaseAgentNode`.

## Key Concepts

- Symptom: `POST /query` intermittently returned HTTP 500 with `pydantic_core._pydantic_core.ValidationError: 1 validation error for _SynthesisOutput — reasoning: Field required`, raised during the LangGraph task named `synthesis`. Severity P1, intermittent — triggered whenever RAG/web/memory context fed into synthesis was verbose enough to make the model's answer run long (e.g. asking about `docs/bugs/002-query-graph-autocommit.md`, which pulls a multi-section five-why table into context).
- Reproduction: `curl -X POST http://localhost:3001/query -H "Content-Type: application/json" -d '{"message": "What is the bug causing the endpoint POST /query keep failing from responding to user?", "sessionId": null}'` reliably reproduced the 500 before the fix.
- Stack trace: failure in `second_brain/nodes/synthesis.py:104` inside `await self._structured_llm.ainvoke(prompt)`, surfaced through `langchain_core/output_parsers/openai_tools.py`'s `PydanticToolsParser.parse_result`, which does `name_dict[res["type"]](**res["args"])` and raises when required fields are missing from the parsed tool-call args.
- Phoenix trace evidence (span `0714a461...`) showed `"stop_reason": "max_tokens"` with `"usage": {"input_tokens": 1860, "output_tokens": 1024}` — the tool-call arguments contained only `final_answer` and `confidence`, meaning generation was cut off by the 1024-token cap before the model reached `reasoning`, the last field defined on `_SynthesisOutput`.
- Anthropic's tool-use `required` schema fields are advisory only — a completion truncated by `max_tokens` can omit a required field, which `PydanticToolsParser` surfaces as a `pydantic.ValidationError` rather than a clean stop.
- Branch where bug was found and fixed: `refactor/agent-pattern`. Date logged: 2026-07-13.

## Root Cause

Five-why chain:

1. `/query` 500s because `PydanticToolsParser` raises `ValidationError` when `reasoning` is missing from the parsed tool call.
2. `reasoning` is missing because Anthropic returned `stop_reason: max_tokens` — generation was truncated mid tool-call before the `reasoning` field was written.
3. It hit `max_tokens` because `SynthesisNode`'s `ClaudeAgent(CLAUDE_MODEL_NAME.SONNET, temperature=None)` never overrides `max_tokens`, so it silently falls back to `ChatAnthropic`'s library default of 1024 tokens.
4. A 500 propagates (instead of degrading gracefully) because `with_structured_output(...)` is called with the default `include_raw=False`, and `synthesis.py:104` wraps the call in no try/except — a parse failure raises straight through LangGraph into FastAPI, which has no handler for it.
5. This surfaced now (not on `main`) because the same defect shape (`_SynthesisOutput.reasoning` required, no `max_tokens` override, no error handling) already existed on `main` but was dormant — `main` uses `claude-sonnet-4-6`, which answered the repro prompt in ~720 tokens, staying under the 1024 cap. This branch's agent-pattern refactor (commit `d65f194`) switched the model to `claude-sonnet-5` (`claude_agent.py:12`), which is markedly more verbose on the same prompt and blows through the same pre-existing 1024 cap.

Empirical confirmation table (identical prompt/schema/`max_tokens=1024`, only the model swapped):

| Model | stop_reason | output_tokens | `reasoning` present |
|---|---|---|---|
| `claude-sonnet-4-6` (main) | `tool_use` | 720 | yes |
| `claude-sonnet-5` (this branch) | `max_tokens` | 1024 | no (didn't even reach `confidence`) |

Root cause statement: `synthesis.py:45` constructs `ClaudeAgent(CLAUDE_MODEL_NAME.SONNET, temperature=None)` without passing `max_tokens`, so `ChatAnthropic` defaults to 1024. Combined with `_SynthesisOutput` requiring `reasoning` with no default value, and no error handling around `.ainvoke()`, any completion truncated at the cap crashes the entire `/query` request with a 500. The refactor's model swap to `claude-sonnet-5` made this latent defect load-bearing by producing longer completions for the same prompts.

Related latent defect (not triggered in production at time of writing): `memory_agent.py` has the identical shape — `MemoryAgentOutput` has required fields, no `max_tokens` override, and no error handling around structured-output calls. Not yet triggered because `MemoryAgentNode` uses Haiku with shorter expected outputs, but it is the same class of bug, shares the same code path as `SynthesisNode`, and was fixed proactively in the same pass.

## Fix

Architecture: add one shared retry helper, `BaseAgentNode._ainvoke_structured`, that wraps a structured-output `Runnable`'s `.ainvoke()` call and retries exactly once on `pydantic.ValidationError`. Both `SynthesisNode` and `MemoryAgentNode` route their existing single `.ainvoke(prompt)` call through this shared helper instead of calling `.ainvoke` directly, and both raise their `ClaudeAgent`'s `max_tokens` from the library default (1024) to 4096 at the `ClaudeAgent(...)` construction call site — so truncation becomes rare in the first place, and the retry helper absorbs the residual case where truncation still happens.

- **Change 1** — `apps/backend/src/second_brain/nodes/synthesis.py:45`: `ClaudeAgent(CLAUDE_MODEL_NAME.SONNET, temperature=None)` → `ClaudeAgent(CLAUDE_MODEL_NAME.SONNET, temperature=None, max_tokens=4096)`.
- **Change 2** — `apps/backend/src/second_brain/nodes/synthesis.py:104`: `await self._structured_llm.ainvoke(prompt)` → `await self._ainvoke_structured(self._structured_llm, prompt)`.
- **Change 3** — `apps/backend/src/second_brain/nodes/memory_agent.py:37`: `ClaudeAgent(CLAUDE_MODEL_NAME.HAIKU)` → `ClaudeAgent(CLAUDE_MODEL_NAME.HAIKU, max_tokens=4096)`.
- **Change 4** — `apps/backend/src/second_brain/nodes/memory_agent.py:99`: `await self._llm.ainvoke(prompt)` → `await self._ainvoke_structured(self._llm, prompt)`.
- **Change 5** — `apps/backend/src/second_brain/nodes/base_node/base_agent_node.py`: new protected async generic method `_ainvoke_structured[T](self, structured_llm: Runnable[LanguageModelInput, T], prompt: str) -> T`. Implementation: try `await structured_llm.ainvoke(prompt)`; on `pydantic.ValidationError`, retry once with `await structured_llm.ainvoke(prompt)` again; a second `ValidationError` propagates unchanged (not swallowed, no fallback/degraded answer). `BaseAgentNode` is a generic ABC parameterized by `[InputStateType, ResultStateType]`, holds `_agent: BaseAgent`, and declares abstract `__call__`.
- The retry catches `pydantic.ValidationError` specifically — not a broad `except Exception` — per the project's no-broad-except rule.
- `max_tokens` is set per-node at construction time in `synthesis.py` and `memory_agent.py`, not changed in `ClaudeAgent`'s own class default. This deliberately leaves other `ClaudeAgent` call sites unaffected, e.g. `IngestionAgentNode`'s `max_tokens=150` and `OrchestratorNode`'s unset default.
- Scope: exactly four files — `base_agent_node.py`, `synthesis.py`, `memory_agent.py`, plus their corresponding test files. No schema changes, no new dependencies, no API contract changes.
- Out of scope: retrying more than once; falling back to a degraded answer after two failures; any other `ClaudeAgent`-based node such as ingestion header generation or the orchestrator; raising `ChatAnthropic`'s own library default `max_tokens` globally.

### Implementation task breakdown

1. **`BaseAgentNode._ainvoke_structured` retry helper** — modifies `base_agent_node.py`; adds `apps/backend/tests/unit/test_nodes/test_base_agent_node.py`. Test coverage: (1) successful first call returns result without a second call; (2) a `ValidationError` on first call triggers exactly one retry and returns the retried result; (3) two consecutive `ValidationError`s propagate instead of being swallowed (call count == 2 in all cases). Commit: "fix: retry structured-output parse once on truncated ValidationError".
2. **Wire `SynthesisNode`** — modifies `synthesis.py` (constructor line 45, call site line 104); test file `test_synthesis.py`. New regression tests reference the bug doc explicitly: `test_synthesis_node_sets_max_tokens_4096` (asserts `ChatAnthropic` is constructed with `max_tokens=4096`) and `test_synthesize_answer_retries_once_when_structured_output_is_truncated` (mocks `_structured_llm.ainvoke` to raise a real `ValidationError` from `_SynthesisOutput.model_validate({"final_answer": "partial", "confidence": 0.75})` — missing the required `reasoning` field — then succeed on retry, asserting `call_count == 2` and the final answer is the retried one). Full unit suite must still pass. Commit: "fix: raise SynthesisNode max_tokens to 4096 and retry truncated output".
3. **Wire `MemoryAgentNode`** — modifies `memory_agent.py` (constructor line 37, call site line 99); test file `test_memory_agent.py`. New test: `test_memory_agent_node_sets_max_tokens_4096`. Regression check must include `test_ingestion_agent_node_caps_max_tokens_at_150` (proves `IngestionAgentNode`'s unrelated `max_tokens=150` call site stayed untouched) plus every existing `test_memory_agent.py`/`test_synthesis.py` case. Commit: "fix: raise MemoryAgentNode max_tokens to 4096 and retry truncated output".
4. **Runtime verification and bug-doc closeout** — modifies `docs/bugs/004-synthesis-max-tokens-truncation.md`'s `## Fix` section. Full workspace verification: `just format && just lint && just type-check && just test-unit` must all pass with no errors/warnings. Boot the backend via `just up-all`; confirm health check (`curl -s localhost:3001/health`) succeeds. Replay the original repro curl; expected result is HTTP 200 with an `answer`/`confidence` JSON body instead of a 500. Commit: "docs: close out synthesis max_tokens truncation bug".

Verification performed: replaying the original repro curl against a fresh backend after the fix returned HTTP 200 (previously 500).

## Acceptance Criteria

1. `POST /query` with the repro prompt from the bug doc returns HTTP 200, not 500.
2. `SynthesisNode`'s and `MemoryAgentNode`'s underlying `ChatAnthropic` instances have `max_tokens == 4096`.
3. `_ainvoke_structured` — first-call success returns that result without making a second call.
4. `_ainvoke_structured` — first call raises `ValidationError`, second call succeeds → returns the second result.
5. `_ainvoke_structured` — both calls raise `ValidationError` → the `ValidationError` propagates (no silent swallow).
6. Other `ClaudeAgent` call sites (e.g. ingestion header generation's `max_tokens=150`) remain unchanged.
7. `just format`, `just lint`, `just type-check`, and `just test-unit` all pass with no errors.

## Sources

- Bug: POST /query — 500 when synthesis LLM output is truncated by max_tokens — `docs/bugs/004-synthesis-max-tokens-truncation.md`
- Synthesis max_tokens Truncation Fix Implementation Plan — `docs/superpowers/plans/2026-07-13-synthesis-max-tokens-truncation-fix.md`
- Spec: Fix max_tokens truncation causing POST /query 500 — `docs/superpowers/specs/2026-07-13-synthesis-max-tokens-truncation-fix.md`

## Related Topics

- [[known-issues]]
- [[query-graph]]
- [[node-base-class-refactor]]
- [[otel-phoenix-tracing]]
