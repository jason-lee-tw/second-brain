# Node Base-Class Refactor

A behavior-preserving structural refactor converting every LangGraph node under `apps/backend/src/second_brain/nodes/` to extend `BaseNode` or `BaseAgentNode`, so each agent-based node owns its own `ClaudeAgent` internally and graph files never construct or name a model directly.

## Key Concepts

- Two requester constraints drove the refactor: (1) every node must extend `BaseNode` or `BaseAgentNode`; (2) the LLM model is defined inside the node itself — graphs (`graphs/query_graph.py`, `graphs/ingestion_graph.py`) only register nodes, never construct or name a model.
- The base classes (`nodes/base_node/base_node.py` — `BaseNode[InputStateType, ResultStateType]` — and `nodes/base_node/base_agent_node.py` — `BaseAgentNode[InputStateType, ResultStateType]`, which wraps a `BaseAgent`) already existed (introduced in commit `c84ce97`); the 9 existing node modules were still plain functions with module-level LLM client singletons, not yet converted.
- Architecture is an **in-place conversion**: every node module keeps its file path and its existing public symbol name, rebound from a bare function to a `__call__`-able class instance — graph files call `add_node("name", instance)` exactly as before, since instances are callables. Consequence: `query_graph.py` needed zero line changes across the whole refactor; only `ingestion_graph.py` changed, because `pick_file_node` relocated out of it.
- **Method rule**: only helpers that touch `self` (`self._agent`, a cached model) become instance methods. Helpers that don't touch `self` (e.g. `_row_to_chunk_metadata`, `_format_messages`, `_search_facts`, `_write_fact`, `_embed_query`, `_conflict_check`, `_retry_write`, `_prior_ai_content`) stay as module-level private functions — forcing them onto the class when they never touch `self` is explicitly framed as a regression, not an improvement.
- **Instantiation pattern**: module-level singleton per node module, created at import time (e.g. `route_query = OrchestratorNode()`); graphs import and register that instance directly. This matches the pre-existing module-level LLM-singleton pattern and keeps every `unittest.mock.patch` target working with only a one-attribute-deeper hop (e.g. `second_brain.nodes.orchestrator._structured_llm` → `second_brain.nodes.orchestrator.route_query._structured_llm`).
- Cross-cutting pattern for every agent-based node: `__init__` constructs its own `ClaudeAgent(CLAUDE_MODEL_NAME.<TIER>)` and derives a cached LLM handle (`_structured_llm`, `_llm`, or `_model`) from `self._agent.get_model()` — nodes own their models, graphs stay model-agnostic.
- `BaseNode` subclasses with no instance state skip defining `__init__` entirely, inheriting the no-op from `BaseNode`.
- Data flow, error handling, prompts, and business logic are unchanged except where explicitly called out as an approved exception (see Approved Behavior Exceptions) — all `TypedDict` schemas in `graphs/state.py` stay exactly as they are.
- Out of scope: conditional-edge routing functions (`_route_retrieval` in `query_graph.py`, `_route_after_ingest` in `ingestion_graph.py`) since they aren't `add_node`-registered nodes; any change to `BaseNode`/`BaseAgentNode`'s public shape beyond the two contract-bug fixes below; any change to state schemas or retrieval logic.

## Contract Bugs Fixed (Task 1)

- **`_agent` annotation bug**: `base_agent_node.py:7` had `_agent = BaseAgent` (assigns the class object itself, a bug) instead of `_agent: BaseAgent` (a type annotation), matching `BaseAgent`'s own `__model: BaseChatModel` style. Zero-risk fix because the line was dead — immediately overwritten in `__init__`.
- **`__call__` return-type bug**: both `BaseNode.__call__` and `BaseAgentNode.__call__` declared a sync-only abstract return type (`ResultStateType`), but 8 of the 11 planned node subclasses override with `async def __call__`. Verified live against the repo's basedpyright config: this fails `just type-check` with a hard `reportIncompatibleMethodOverride` on every async override, plus a `reportImplicitOverride` warning (which still fails the `just` recipe's exit code) on every subclass lacking `@override`. Fix: widen both abstract `__call__` return types to `Awaitable[ResultStateType] | ResultStateType` (`from collections.abc import Awaitable`), and require `@override` (`from typing import override`) on every concrete subclass — keeps real override-safety checking active instead of suppressing it project-wide.
- `CLAUDE_MODEL_NAME` was also exported alongside `ClaudeAgent`/`BaseAgent` from `second_brain.nodes.base_node.agents.__init__` so later tasks can `from second_brain.nodes.base_node.agents import CLAUDE_MODEL_NAME, ClaudeAgent`.

## Approved Behavior Exceptions

Framed as an explicitly behavior-preserving refactor with 4 approved exceptions:

1. **Temperature default**: `orchestrator`/`memory_agent`/`synthesis` previously instantiated `ChatAnthropic(...)` directly with no `temperature` set (defaulting to `None`, effectively ~1.0 via the Anthropic API default). Moving onto `ClaudeAgent` picks up its default `temperature=0.7` — a deliberate behavior change (more determinism for routing/classification, no meaningful downside for synthesis), with no per-node override.
2. **Ingestion header generation** moves from the raw `anthropic.AsyncAnthropic` SDK client to `ClaudeAgent`/`ChatAnthropic`. The old code scanned `response.content` for a `TextBlock`; the new code reads `AIMessage.content` as a plain string (confirmed: for a non-tool text completion, LangChain's `.content` is already a string). This is the one piece of the whole refactor verified with a genuine test-first red/green cycle rather than a structural-move-only cycle.
3. **Dead-code removal**: `settings.ingestion_model` config field (confirmed via grep as the only caller) and `ingestion_agent.shutdown()` (plus its two call sites in `main.py`'s lifespan teardown) are deleted — confirmed no `ChatAnthropic` instance anywhere in the repo has explicit teardown (`.close`/`.aclose` doesn't exist on the class).
4. **Model pin**: `orchestrator`/`memory_agent`/`ingestion_agent` move from the undated rolling alias `"claude-haiku-4-5"` to the dated snapshot `CLAUDE_MODEL_NAME.HAIKU = "claude-haiku-4-5-20251001"`, accepted for reproducibility since a rolling alias can silently change model behavior without a code change. This also fixes model-string drift in `synthesis.py`, which had used the stale string `"claude-sonnet-4-6"` instead of `CLAUDE_MODEL_NAME.SONNET = "claude-sonnet-5"`.

## Component Breakdown

| File | Class | Base | Model | Public name (unchanged) |
|---|---|---|---|---|
| `orchestrator.py` | `OrchestratorNode` | `BaseAgentNode[SecondBrainState, RouteQueryOutput]` | `ClaudeAgent(HAIKU)` + structured output | `route_query` |
| `memory_agent.py` | `MemoryAgentNode` | `BaseAgentNode[SecondBrainState, dict[str, object]]` | `ClaudeAgent(HAIKU)` + structured output | `memory_agent_node` |
| `synthesis.py` | `SynthesisNode` | `BaseAgentNode[SecondBrainState, SynthesisNodeOutput]` | `ClaudeAgent(SONNET)` + structured output | `synthesize_answer` |
| `ingestion_agent.py` | `IngestionAgentNode` | `BaseAgentNode[IngestionState, IngestionAgentOutput]` | `ClaudeAgent(HAIKU)`, plain `ainvoke` | `ingestion_agent_node` |
| `pii_redaction.py` | `RedactInboundNode`, `RedactOutboundNode` | `BaseNode[...]` ×2 | none | `redact_inbound`, `redact_outbound` |
| `web_research.py` | `WebResearchNode` | `BaseNode[SecondBrainState, WebResearchOutput]` | none | `search_web` |
| `rag_retrieval.py` | `RagRetrievalNode` | `BaseNode[SecondBrainState, RagRetrievalOutput]` | none | `retrieve_from_rag` |
| `memory_retrieval.py` | `MemoryRetrievalNode` | `BaseNode[SecondBrainState, RetrieveMemoryOutput]` | none | `memory_retrieval_node` |
| `memory_persistence.py` | `MemoryPersistenceNode` | `BaseNode[SecondBrainState, dict[str, Any]]` | none | `memory_persistence_node` |
| `nodes/pick_file.py` (new file) | `PickFileNode` | `BaseNode[IngestionState, PickFileOutput]` | none | `pick_file_node` |

`pick_file_node` relocated out of `graphs/ingestion_graph.py` into a new `nodes/pick_file.py` module — it was already registered via `add_node`, making it a real node in spirit even though it lived outside `nodes/`. Rejected layout alternatives: subpackage-per-node (9 files → ~18 for no behavioral gain) and a single registry file (merge-conflict magnet, no isolation benefit).

## Task-by-Task Conversion Notes

- **Task 1** — fix the two `BaseNode`/`BaseAgentNode` contract bugs and export `CLAUDE_MODEL_NAME` (see Contract Bugs Fixed above). No new tests needed since no subclasses existed yet.
- **Task 2** — `pii_redaction.py`: both nodes are sync, no agent; `RedactInboundNode` raises `ValueError` on empty `state["messages"]`, returns a replacement `HumanMessage` with the same id so LangGraph's `add_messages` reducer replaces in place.
- **Task 3** — `web_research.py`: async, uses module-level `TavilyClient` via `asyncio.to_thread`.
- **Task 4** — `rag_retrieval.py`: async; `_embed_query` posts to a local Ollama embedding endpoint; `_query_pgvector` runs cosine-similarity SQL (`embedding<=>$1`) via `get_pgvector_pool()`.
- **Task 5** — `memory_retrieval.py`: async, dual-table cosine search over `learned_facts` and `model_corrections` in parallel via `asyncio.gather`; fails hard on Ollama unavailability except when there's no last human message.
- **Task 6** — `memory_persistence.py`: async; contains the "F1 fix" — `skip_conflict_check` prevents re-triggering `_conflict_check` when the LLM omits `conflicts_with` during a conflict-resolution turn, avoiding an infinite loop; per-fact retry logic (`_retry_write`, up to 3 attempts).
- **Task 7** — new `nodes/pick_file.py`; `ingestion_graph.py` rewritten to wire `pick_file` → `ingest` → conditional routing (`_route_after_ingest`).
- **Task 8** — `orchestrator.py`: agent-based, caches `_structured_llm`; routes into `"rag" | "web" | "both" | "neither"`.
- **Task 9** — `memory_agent.py`: agent-based, caches `_llm`; classifies into 3 `MemoryCase` branches (normal extraction, correction check, conflict clarification); shares the "F1 fix" pattern with Task 6.
- **Task 10** — `synthesis.py`: agent-based on SONNET (not HAIKU, unlike 8/9/11), caches `_structured_llm`; builds context from RAG/web/memory, applies `_UNCERTAINTY_THRESHOLD = 0.7` and `_NEITHER_CONFIDENCE_FLOOR = 0.5`.
- **Task 11** — `ingestion_agent.py`: agent-based, caches `_model`; genuine behavior change (see Approved Behavior Exceptions #2); `_do_ingest` flow is read file → MD5 hash → duplicate check → chunk → concurrent chunk processing (`_CHUNK_CONCURRENCY = 10`) → write results → move to processed dir.
- **Task 12** — full-repo verification pass (no file changes): confirms `query_graph.py` needed zero edits; runs `just format lint type-check test-unit`; smoke-tests `POST /query` for HTTP 200 with `final_answer`/`confidence`.
- Whenever a module-level LLM handle becomes an instance attribute, every mock patch target in the corresponding test file moves one attribute hop deeper (`second_brain.nodes.<module>.<attr>` → `second_brain.nodes.<module>.<singleton_name>.<attr>`) — this affects `test_orchestrator.py` (5x), `test_memory_agent.py` (6x), `test_synthesis.py` (11x), and `test_ingestion_agent.py` plus the integration test `test_ingestion_graph.py` (3x each, full mock rewrite since the target moves from the raw SDK's `_anthropic.messages.create` to the cached model's `.ainvoke`). The other 6 test files needed zero changes since they patch module-level helper functions unrelated to node structure.

## Follow-On: Truncation Fix Built on This Refactor

The `[[synthesis-max-tokens-truncation-fix]]` spec (2026-07-13) is a direct follow-on that builds on this refactor's base classes: it fixes a `POST /query` HTTP 500 caused by `ChatAnthropic`'s default `max_tokens=1024` truncating synthesis output before the required `reasoning` field of `_SynthesisOutput` is written, which makes `PydanticToolsParser` raise an uncaught `pydantic.ValidationError`. `MemoryAgentNode` has the identical defect shape (not yet triggered in production, but fixed in the same pass since it shares the same root cause and code path as `SynthesisNode`). The fix adds a new protected async helper method directly onto `BaseAgentNode` — `_ainvoke_structured(structured_llm, prompt)` — which calls `.ainvoke(prompt)` and retries exactly once on `pydantic.ValidationError` (a second failure propagates unchanged, no silent swallow). Both `synthesis.py` (`max_tokens=4096`, `temperature=None`) and `memory_agent.py` (`max_tokens=4096`) construct their `ClaudeAgent` with the higher token cap and route their existing `.ainvoke` call through this new `self._ainvoke_structured(...)` helper instead of calling `.ainvoke` directly. This is only possible because this refactor gave `SynthesisNode` and `MemoryAgentNode` a shared `BaseAgentNode` ancestor to hang the retry helper on.

## Sources

- Node Base-Class Refactor Implementation Plan — `docs/superpowers/plans/2026-07-07-node-base-class-refactor.md`
- Node Base-Class Refactor — Design — `docs/superpowers/specs/2026-07-07-node-base-class-refactor-design.md`
- Spec: Fix max_tokens truncation causing POST /query 500 — `docs/superpowers/specs/2026-07-13-synthesis-max-tokens-truncation-fix.md`

## Related Topics

- [[synthesis-max-tokens-truncation-fix]]
- [[query-graph]]
- [[document-ingestion-pipeline]]
- [[multi-agent-architecture]]
- [[type-checking]]
