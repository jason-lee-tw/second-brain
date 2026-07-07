# Node Base-Class Refactor — Design

**Date:** 2026-07-07
**Status:** Approved (pending spec self-review)

## Context

`c84ce97` introduced OOP base classes for LangGraph nodes:
`nodes/base_node/base_node.py` (`BaseNode[InputStateType, ResultStateType]`) and
`nodes/base_node/base_agent_node.py` (`BaseAgentNode[InputStateType, ResultStateType]`,
which wraps a `BaseAgent`), plus `nodes/base_node/agents/` (`BaseAgent`, `ClaudeAgent`).

All 9 existing node modules under `nodes/` are still plain functions with
module-level LLM client singletons. This refactor converts every node to
extend one of the two base classes, per two constraints from the requester:

1. Every node must extend `BaseNode` or `BaseAgentNode`.
2. The LLM model is defined inside the node; graphs (`graphs/query_graph.py`,
   `graphs/ingestion_graph.py`) only register nodes — they never construct or
   name a model.

## Decisions (resolved via grilling + brainstorming)

1. **Fix `base_agent_node.py:7`**: `_agent = BaseAgent` (assigns the class
   object) → `_agent: BaseAgent` (type annotation), matching `BaseAgent`'s own
   `__model: BaseChatModel` style. Zero-risk, the line is currently dead
   (immediately overwritten in `__init__`).

2. **Consolidate onto `ClaudeAgent`.** `orchestrator.py`, `memory_agent.py`,
   and `synthesis.py` currently instantiate `ChatAnthropic(model=...)`
   directly, bypassing `ClaudeAgent` entirely. `synthesis.py` uses the stale
   model string `"claude-sonnet-4-6"` (drift from `CLAUDE_MODEL_NAME.SONNET =
   "claude-sonnet-5"`). All three move to `ClaudeAgent(CLAUDE_MODEL_NAME.HAIKU
   | SONNET)`, fixing the drift as a side effect.

3. **Temperature default.** The three raw `ChatAnthropic(...)` calls never set
   `temperature` (defaults to `None`, i.e. the Anthropic API default, ~1.0).
   `ClaudeAgent.__init__` defaults `temperature=0.7`. Accepted as-is — no
   per-node override. This is a deliberate behavior change (more determinism
   for routing/classification, no meaningful downside for synthesis).

4. **Agent ownership.** Each `BaseAgentNode` subclass constructs its own
   `ClaudeAgent(...)` inside `__init__` and calls `super().__init__(agent)`.
   Graphs never see a model name.

5. **Instantiation pattern: module-level singleton.** Each node module
   defines one instance at import time. Graphs import and register that
   instance directly (`workflow.add_node("orchestrator", route_query)`) —
   this matches the existing module-level LLM-singleton pattern and (per
   point 8 below) keeps every existing `unittest.mock.patch` pattern working
   with only a one-attribute-deeper target. Cached-model instance attributes
   keep today's module-level singleton names exactly (`_structured_llm` in
   `orchestrator.py`/`synthesis.py`, `_llm` in `memory_agent.py`) so the only
   change to each patch target is inserting `.<public_name>` before the
   attribute.

6. **`ingestion_agent.py` migrates onto `ClaudeAgent`.** Today it uses the raw
   `anthropic.AsyncAnthropic` SDK client (not LangChain) for one call —
   contextual header generation — scanning `response.content` for a
   `TextBlock`. This becomes `ClaudeAgent(CLAUDE_MODEL_NAME.HAIKU)` +
   `ChatAnthropic.ainvoke(prompt)`, reading `.content` as a plain string
   (confirmed: for a non-tool text completion, LangChain's `AIMessage.content`
   is already a string — no list-scanning needed). This is a real behavioral
   change, not a pure move, accepted for consistency: every agent-based node
   now goes through the same `BaseAgent` abstraction.

7. **`settings.ingestion_model` (config.py:22) is deleted.** It's the only
   caller of that config field (confirmed via repo-wide grep — no test or
   other code overrides it), and it becomes dead once `IngestionAgentNode`
   hardcodes `CLAUDE_MODEL_NAME.HAIKU` (same default value, "claude-haiku-4-5").

8. **`ingestion_agent.py`'s `shutdown()` is deleted**, along with its two call
   sites in `main.py` (the import at line 12, the `await
   ingestion_agent.shutdown()` in the lifespan handler at line 36). Confirmed
   via codebase search: no `ChatAnthropic` instance anywhere in this repo has
   explicit teardown (`.close`/`.aclose` doesn't exist on the class) — every
   other agent-based node already leaves its client to GC. Once ingestion
   moves off the raw SDK client, there's nothing left to close.

9. **`pick_file_node` moves into scope.** It currently lives in
   `graphs/ingestion_graph.py` (not `nodes/`) but is registered via
   `add_node`, making it a real LangGraph node in spirit. It relocates to a
   new `nodes/pick_file.py` as a `BaseNode` subclass. Conditional-edge
   *routing* functions (`_route_retrieval` in `query_graph.py`,
   `_route_after_ingest` in `ingestion_graph.py`) stay put — they're routing
   predicates, not nodes registered via `add_node`.

10. **Layout: in-place conversion (not subpackage-per-node or a registry
    file).** Every existing node file keeps its name and import path. The
    module-level function becomes a class; the module-level LLM client
    becomes a module-level class-instance singleton. Rejected alternatives:
    subpackage-per-node (9 files → ~18 for no behavioral gain) and a single
    registry file (merge-conflict magnet, no isolation benefit).

11. **Naming rule — public symbol names do not change.** Each module's
    existing public name gets rebound from a function to a singleton
    instance (e.g. `orchestrator.py`'s `route_query`, `memory_agent.py`'s
    `memory_agent_node`). This means `query_graph.py` needs **zero line
    changes** — only `ingestion_graph.py` changes, because `pick_file_node`
    is relocating out of it.

12. **Method rule — only `self`-dependent helpers become methods.** Private
    helpers that don't touch `self._agent`/`self._structured_llm` (e.g.
    `_row_to_chunk_metadata`, `_format_messages`, `_search_facts`,
    `_write_fact`, `_embed_query`, `_conflict_check`, `_retry_write`,
    `_prior_ai_content`) stay as module-level private functions called from
    inside `__call__`. Forcing them onto the class when they never touch
    `self` would be a regression, not an improvement.

## Component breakdown

| File | Class | Base | Model | Public name (unchanged) |
|---|---|---|---|---|
| orchestrator.py | `OrchestratorNode` | `BaseAgentNode[SecondBrainState, RouteQueryOutput]` | `ClaudeAgent(HAIKU)` + structured output | `route_query` |
| memory_agent.py | `MemoryAgentNode` | `BaseAgentNode[SecondBrainState, dict[str, object]]` | `ClaudeAgent(HAIKU)` + structured output | `memory_agent_node` |
| synthesis.py | `SynthesisNode` | `BaseAgentNode[SecondBrainState, SynthesisNodeOutput]` | `ClaudeAgent(SONNET)` + structured output | `synthesize_answer` |
| ingestion_agent.py | `IngestionAgentNode` | `BaseAgentNode[IngestionState, IngestionAgentOutput]` | `ClaudeAgent(HAIKU)`, plain `ainvoke` | `ingestion_agent_node` |
| pii_redaction.py | `RedactInboundNode`, `RedactOutboundNode` | `BaseNode[...]` ×2 | none | `redact_inbound`, `redact_outbound` |
| web_research.py | `WebResearchNode` | `BaseNode[SecondBrainState, WebResearchOutput]` | none | `search_web` |
| rag_retrieval.py | `RagRetrievalNode` | `BaseNode[SecondBrainState, RagRetrievalOutput]` | none | `retrieve_from_rag` |
| memory_retrieval.py | `MemoryRetrievalNode` | `BaseNode[SecondBrainState, RetrieveMemoryOutput]` | none | `memory_retrieval_node` |
| memory_persistence.py | `MemoryPersistenceNode` | `BaseNode[SecondBrainState, dict[str, Any]]` | none | `memory_persistence_node` |
| **nodes/pick_file.py (new)** | `PickFileNode` | `BaseNode[IngestionState, PickFileOutput]` | none | `pick_file_node` |

`BaseNode` subclasses with no instance state skip defining `__init__`
entirely (inherit the no-op from `BaseNode`).

## Data flow

Unchanged. All `TypedDict` schemas in `graphs/state.py` stay exactly as they
are — this is a structural refactor, not a schema change.

## Error handling

Unchanged everywhere except `ingestion_agent`'s header generation (see
decision 6): the manual `TextBlock`-scan-and-raise is replaced by reading
`AIMessage.content` as a plain string, since there's no list to scan once the
raw SDK response format goes away.

## Testing impact

Because `await route_query(state)` works identically whether `route_query` is
a function or a `__call__`-able instance, and because `self`-independent
helpers stay as module-level functions (decision 12), only **4 of 10** test
files need edits — and only because their LLM-patch target grows one
attribute hop:

- `test_orchestrator.py`: `patch("...orchestrator._structured_llm")` →
  `patch("...orchestrator.route_query._structured_llm")`
- `test_memory_agent.py`: `..._llm` → `...memory_agent_node._llm`
- `test_synthesis.py`: `..._structured_llm` →
  `...synthesize_answer._structured_llm`
- `test_ingestion_agent.py`: full rewrite of the mock — target moves from
  `_anthropic.messages.create` (raw SDK, `Message` with `TextBlock` content)
  to the cached model's `.ainvoke` (LangChain, mock returns something with a
  plain `.content` string)

The other 6 (`pii_redaction`, `web_research`, `rag_retrieval`,
`memory_retrieval`, `memory_persistence`, `ingestion_graph`) patch
module-level helper functions unrelated to node structure — zero changes
needed.

## Out of scope

- Conditional-edge routing functions (`_route_retrieval`, `_route_after_ingest`)
  — not `add_node`-registered nodes.
- Any change to `BaseNode`/`BaseAgentNode`'s public shape beyond the
  `_agent` annotation fix in decision 1.
- Any change to state schemas, retrieval logic, prompts, or business logic
  beyond what's required to relocate code into classes.
