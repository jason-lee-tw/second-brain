# Type Checking

A 50-error, 12-file basedpyright remediation pass across the backend, fixed with three repeatable categories — targeted stub-gap ignores, per-node `TypedDict`s, and a shared content-narrowing helper — under a hard no-`Any`-in-owned-code rule, later joined by a second pass that widened `BaseNode`/`BaseAgentNode`'s `__call__` return type to keep `just type-check` green across the node base-class refactor.

## Key Concepts

- **Checker and entry point**: `just type-check` runs basedpyright; before the fix it exited 1 with 50 actual errors across 12 backend files (plus additional warnings that also blocked the check).
- **Hard constraint**: never use `Any` in code the team owns. `cast(SomeType, ...)` is allowed at system boundaries such as raw DB reads. Two narrow, explicitly documented exceptions to the no-`Any` rule exist because they are imposed by third-party stubs, not project code: the `Any` type parameter on `AsyncConnectionPool[Any]`'s row-factory type in `query_graph.py`'s return type, and `Settings()`/pydantic-settings' inability to see env-injected required fields.
- **Three fix categories**:
  1. Targeted `# type: ignore[<code>]` comments for third-party stub gaps where runtime behavior is correct but the stub disagrees — always with the specific error code attached, never a bare `# type: ignore`.
  2. Per-LangGraph-node output `TypedDict`s in `graphs/state.py`, replacing bare `dict` return types, so each node's return shape is precisely checkable.
  3. A new `second_brain/utils.py` module with `get_str_content(msg: BaseMessage) -> str`, narrowing `BaseMessage.content` (typed `str | list[...]` for multi-modal support this app never uses) down to `str`, raising `TypeError` (not a bare `assert`) with a message naming the actual type when content isn't a string.
- **Design decisions (D1–D10)**, recorded in `docs/bugs/001-fix-typecheck-error.md` as the "why" behind each fix category:
  - D1 — library stub gaps get targeted `# type: ignore[<code>]` rather than casts/wrappers: `ChatAnthropic(model=...)`, `Settings()`, SQLModel `__tablename__` (`declared_attr[Unknown]`), `AsyncPostgresSaver(pool)`, `.with_structured_output().ainvoke()` (`dict | BaseModel`), presidio `RecognizerResult` mismatch.
  - D2 — `response.content[0].text` in `ingestion_agent.py` replaced with `isinstance` narrowing against `anthropic.types.TextBlock` (`next(b for b in response.content if isinstance(b, TextBlock)).text.strip()`) — raises a clear `StopIteration` if the API ever returns a non-text block first, instead of a confusing `AttributeError`.
  - D3 — `ingest.py`'s `asyncio.gather(return_exceptions=True)` check changed from `isinstance(result, Exception)` to `isinstance(result, BaseException)`, since the narrower check doesn't correctly narrow `BaseException` away in the `else` branch.
  - D4 — `build_ingestion_graph()` return type corrected from `StateGraph` to `CompiledStateGraph[IngestionState, None, IngestionState, IngestionState]`, which also fixed a downstream `ainvoke` typing error in `ingest.py` for free.
  - D5 — per-node output `TypedDict`s with no `Any`: `PickFileOutput`, `IngestionAgentOutput`, `RedactInboundOutput`, `RedactOutboundOutput`, `RetrieveMemoryOutput`, `RouteQueryOutput`, `RagRetrievalOutput`, `WebResearchOutput`, `SynthesisNodeOutput`.
  - D6 — `get_str_content` helper centralizes a pattern repeated across 4+ nodes; placed in a dedicated `utils.py`, not `state.py`, since it's a utility function, not a state definition.
  - D7 — presidio `RecognizerResult` mismatch fixed with `# type: ignore[arg-type]` on the `anonymize()` call — same runtime class, different stub import paths.
  - D8 — `query_graph.py` returns `tuple[CompiledStateGraph[...], AsyncConnectionPool[Any]]`; the `Any` is an approved exception since it's the psycopg row-factory type imposed by the library.
  - D9 — `__tablename__` in `db/models.py` annotated `ClassVar[str]` — the correct SQLAlchemy annotation, not a workaround.
  - D10 — `ChatAnthropic(model=...)` → `ChatAnthropic(model_name=...)` in `orchestrator.py` and `synthesis.py`, since `model=` is a runtime-only alias invisible to the stubs.
- **Task sequence** (implementation plan, one task per commit, tracked via checkboxes): Task 1 adds `get_str_content` to new `utils.py`; Task 2 adds the 7 query-graph node `TypedDict`s plus `PickFileOutput`/`IngestionAgentOutput` to `state.py`, retypes `RagResult.metadata` to `dict[str, str | int]`, and adds a `ChunkMetadata` TypedDict to `services/chunking.py`; Task 3 is pure annotation fixes (`ClassVar[str]` on all `__tablename__`s, `dict` field retyping, the `Settings()` and presidio ignores); Task 4 fixes both graph builders' return types and the `AsyncPostgresSaver` ignore; Task 5 applies the `TextBlock` narrowing in `ingestion_agent.py`; Task 6 renames `model=` to `model_name=` in the orchestrator and synthesis nodes; Task 7 applies `get_str_content` at every `messages[-1].content` read site and fixes the `BaseException` narrowing bug in `ingest.py` — this task's final type-check pass is called out as "the milestone," the first time `just type-check` exits 0; Task 8 is final verification (`just lint && just format && just type-check` all exit 0, full `just test-unit` green, manual scan for stray errors/warnings, `enhanced-review` on the diff, then a PR titled `fix(types): resolve all 50 basedpyright errors` on branch `fix/typecheck-errors`).
- Every one of D1–D10 is mapped to the task(s) implementing it in a self-review coverage table, confirming no decision was dropped during implementation.
- Global constraints re-checked after every task: `just type-check` exits 0 (at the end), `just test-unit` stays green throughout, `just lint` passes, every targeted ignore names its specific error code.
- **Second pass — `[[node-base-class-refactor]]` `__call__` return-type fix**: converting the 9 node modules to extend `BaseNode`/`BaseAgentNode` surfaced a fresh basedpyright failure, because 8 of the 11 planned node subclasses override `__call__` with `async def` while the abstract base declared a sync-only `ResultStateType` return. That produced a hard `reportIncompatibleMethodOverride` error on every async override, plus a `reportImplicitOverride` warning (which still fails the `just` recipe's exit code) on every subclass lacking `@override`. Fixed by widening both `BaseNode.__call__` and `BaseAgentNode.__call__` to return `Awaitable[ResultStateType] | ResultStateType` (`from collections.abc import Awaitable`) and requiring `@override` (`from typing import override`) on every concrete override — keeping the real override-safety check active rather than suppressing it project-wide. Full task-by-task detail of the refactor this fix unblocked lives on `[[node-base-class-refactor]]`, not duplicated here.

## Sources

- Task 001 — Fix Type-Check Errors — `docs/bugs/001-fix-typecheck-error.md`
- Fix Type-Check Errors Implementation Plan — `docs/superpowers/plans/2026-06-24-fix-typecheck-errors.md`
- Node Base-Class Refactor — Design — `docs/superpowers/specs/2026-07-07-node-base-class-refactor-design.md`

## Related Topics

- [[query-graph]]
- [[known-issues]]
- [[python-3-13-upgrade]]
- [[document-ingestion-pipeline]]
- [[node-base-class-refactor]]
