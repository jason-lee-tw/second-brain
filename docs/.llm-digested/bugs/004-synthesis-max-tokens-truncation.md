# Bug: POST /query — 500 when synthesis LLM output is truncated by max_tokens

Source: docs/bugs/004-synthesis-max-tokens-truncation.md
Primary-Topic: synthesis-max-tokens-truncation-fix
Secondary-Topics: query-graph, otel-phoenix-tracing

## Key Concepts

- Symptom: `POST /query` intermittently returns HTTP 500 with `pydantic_core._pydantic_core.ValidationError: 1 validation error for _SynthesisOutput — reasoning: Field required`, raised during the LangGraph task named `synthesis`.
- Severity P1, intermittent — triggered whenever RAG/web/memory context fed into synthesis is verbose enough to make the model's answer run long (e.g. asking about `docs/bugs/002-query-graph-autocommit.md`, which pulls a multi-section five-why table into context).
- Reproduction: `curl -X POST http://localhost:3001/query -H "Content-Type: application/json" -d '{"message": "What is the bug causing the endpoint POST /query keep failing from responding to user?", "sessionId": null}'` reliably reproduced the 500 before the fix.
- Stack trace shows failure in `second_brain/nodes/synthesis.py:104` inside `await self._structured_llm.ainvoke(prompt)`, surfaced through `langchain_core/output_parsers/openai_tools.py`'s `PydanticToolsParser.parse_result`, which does `name_dict[res["type"]](**res["args"])` and raises when required fields are missing from the parsed tool-call args.
- Phoenix trace evidence (span `0714a461...`) showed `"stop_reason": "max_tokens"` with `"usage": {"input_tokens": 1860, "output_tokens": 1024}` — the tool-call arguments contained only `final_answer` and `confidence`, meaning generation was cut off by the 1024-token cap before the model reached `reasoning`, the last field defined on `_SynthesisOutput`.
- Five-why root cause chain:
  1. `/query` 500s because `PydanticToolsParser` raises `ValidationError` when `reasoning` is missing from the parsed tool call.
  2. `reasoning` is missing because Anthropic returned `stop_reason: max_tokens` — generation was truncated mid tool-call before the `reasoning` field was written.
  3. It hit `max_tokens` because `SynthesisNode`'s `ClaudeAgent(CLAUDE_MODEL_NAME.SONNET, temperature=None)` never overrides `max_tokens`, so it silently falls back to `ChatAnthropic`'s library default of 1024 tokens.
  4. A 500 propagates (instead of degrading gracefully) because `with_structured_output(...)` is called with the default `include_raw=False`, and `synthesis.py:104` wraps the call in no try/except — a parse failure raises straight through LangGraph into FastAPI, which has no handler for it.
  5. This surfaced now (not on `main`) because the same defect shape (`_SynthesisOutput.reasoning` required, no `max_tokens` override, no error handling) already existed on `main` but was dormant — `main` uses `claude-sonnet-4-6`, which answered the repro prompt in ~720 tokens, staying under the 1024 cap. This branch's agent-pattern refactor (commit `d65f194`) switched the model to `claude-sonnet-5` (`claude_agent.py:12`), which is markedly more verbose on the same prompt and blows through the same pre-existing 1024 cap.
- Empirical confirmation table (identical prompt/schema/`max_tokens=1024`, only the model swapped): `claude-sonnet-4-6` (main) → `stop_reason: tool_use`, 720 output tokens, `reasoning` present; `claude-sonnet-5` (this branch) → `stop_reason: max_tokens`, 1024 output tokens, `reasoning` absent (didn't even reach `confidence`).
- Root cause statement: `synthesis.py:45` constructs `ClaudeAgent(CLAUDE_MODEL_NAME.SONNET, temperature=None)` without passing `max_tokens`, so `ChatAnthropic` defaults to 1024. Combined with `_SynthesisOutput` requiring `reasoning` with no default value, and no error handling around `.ainvoke()`, any completion truncated at the cap crashes the entire `/query` request with a 500. The refactor's model swap to `claude-sonnet-5` made this latent defect load-bearing by producing longer completions for the same prompts.
- Related latent defect (not yet triggered at time of writing): `memory_agent.py` has the identical shape — `MemoryAgentOutput` has required fields, no `max_tokens` override, and no error handling around structured-output calls. Currently lower risk because its outputs are shorter, but it is the same class of bug and should be watched.
- Fix (implemented per `docs/superpowers/specs/2026-07-13-synthesis-max-tokens-truncation-fix.md` and `docs/superpowers/plans/2026-07-13-synthesis-max-tokens-truncation-fix.md`):
  - `SynthesisNode` and `MemoryAgentNode` now construct their `ClaudeAgent` with `max_tokens=4096` (previously unset, defaulting to `ChatAnthropic`'s library default of 1024).
  - `BaseAgentNode._ainvoke_structured` now retries a structured-output `.ainvoke()` call exactly once on `pydantic.ValidationError`, absorbing residual truncation without masking a genuine second failure (i.e. it still raises if the retry also fails).
- Verification performed: replaying the original repro curl against a fresh backend after the fix returned HTTP 200 (previously 500).
- Branch where bug was found and fixed: `refactor/agent-pattern`. Date logged: 2026-07-13.
