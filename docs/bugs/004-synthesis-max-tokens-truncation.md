# Bug: POST /query — 500 when synthesis LLM output is truncated by max_tokens

**Date:** 2026-07-13  
**Branch:** refactor/agent-pattern  
**Severity:** P1 — intermittent 500, triggered by verbose RAG/web/memory context or long answers

---

## Symptom

`POST /query` returns HTTP 500. Backend log:

```
pydantic_core._pydantic_core.ValidationError: 1 validation error for _SynthesisOutput
reasoning
  Field required [type=missing, input_value={'final_answer': 'There a...s.', 'confidence': 0.75}, input_type=dict]
During task with name 'synthesis' and id '823cdc84-8160-a4fb-2046-0c94a97068fd'
```

## Reproduction

```bash
curl -X POST http://localhost:3001/query \
  -H "Content-Type: application/json" \
  -d '{"message": "What is the bug causing the endpoint POST /query keep failing from responding to user?", "sessionId": null}'
# → 500 Internal Server Error
```

Reliably reproduces when the RAG-retrieved context is large enough that the model's answer runs long (e.g. asking about `docs/bugs/002-query-graph-autocommit.md`, which pulls in a multi-section five-why table).

## Stack Trace (abbreviated)

```
File "second_brain/nodes/synthesis.py", line 104, in __call__
    output: _SynthesisOutput = await self._structured_llm.ainvoke(prompt)
File "langchain_core/output_parsers/openai_tools.py", line 343, in parse_result
    pydantic_objects.append(name_dict[res["type"]](**res["args"]))
pydantic_core._pydantic_core.ValidationError: 1 validation error for _SynthesisOutput
reasoning
  Field required [type=missing]
```

## Evidence Gathered (Phoenix trace, span `0714a461...`)

```json
"stop_reason": "max_tokens",
"usage": {"input_tokens": 1860, "output_tokens": 1024}
```

Tool-call arguments contained only `final_answer` and `confidence` — generation was cut off by the 1024-token cap before the model reached `reasoning` (the last field in `_SynthesisOutput`).

## Five-Why Root Cause

| Why | Finding |
| --- | --- |
| Why does `/query` 500? | `PydanticToolsParser` raises `ValidationError` — `reasoning` missing from the parsed tool call |
| Why is `reasoning` missing? | Anthropic returned `stop_reason: max_tokens` — generation was truncated mid tool-call before `reasoning` was written |
| Why did it hit `max_tokens`? | `SynthesisNode`'s `ClaudeAgent(CLAUDE_MODEL_NAME.SONNET, temperature=None)` never overrides `max_tokens`, so it falls back to `ChatAnthropic`'s library default of 1024 |
| Why does a 500 propagate instead of degrading gracefully? | `with_structured_output(...)` is called with the default `include_raw=False`, and `synthesis.py:104` has no try/except — a parse failure raises straight through LangGraph into FastAPI, which has no handler for it |
| Why did this surface now and not on `main`? | Same defect shape exists on `main` (`_SynthesisOutput.reasoning` required, no `max_tokens` override, no error handling) but is dormant there — `main` uses `claude-sonnet-4-6`, which answers the repro prompt in ~720 tokens. This branch's refactor (`d65f194`) switched the model to `claude-sonnet-5` (`claude_agent.py:12`), which is markedly more verbose on the same prompt and blows through the same pre-existing 1024 cap |

Confirmed empirically — identical prompt/schema/`max_tokens=1024`, model swapped:

| Model | stop_reason | output_tokens | `reasoning` present |
| --- | --- | --- | --- |
| `claude-sonnet-4-6` (main) | `tool_use` | 720 | yes |
| `claude-sonnet-5` (this branch) | `max_tokens` | 1024 | no (didn't even reach `confidence`) |

## Root Cause

`synthesis.py:45` — `ClaudeAgent(CLAUDE_MODEL_NAME.SONNET, temperature=None)` doesn't pass `max_tokens`, so `ChatAnthropic` defaults to 1024. Combined with `_SynthesisOutput` requiring `reasoning` with no default, and no error handling around `.ainvoke()`, any completion that gets truncated at the cap crashes the whole `/query` request with a 500. The refactor's model swap to `claude-sonnet-5` made this defect load-bearing by producing longer completions for the same prompts.

**Related latent defect (not yet triggered):** `memory_agent.py` has the same shape — `MemoryAgentOutput` required fields, no `max_tokens` override, no error handling. Lower risk today since its outputs are shorter, but the same class of bug.

## Fix

Implemented per `docs/superpowers/specs/2026-07-13-synthesis-max-tokens-truncation-fix.md`
and `docs/superpowers/plans/2026-07-13-synthesis-max-tokens-truncation-fix.md`:

- `SynthesisNode` and `MemoryAgentNode` now construct their `ClaudeAgent` with
  `max_tokens=4096` (was: unset, defaulting to `ChatAnthropic`'s library default of 1024).
- `BaseAgentNode._ainvoke_structured` retries a structured-output `.ainvoke()` call
  exactly once on `pydantic.ValidationError`, absorbing residual truncation without
  masking a genuine second failure.

Verified: replaying the original repro curl against a fresh backend now returns 200.
