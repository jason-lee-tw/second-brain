# Multi-Agent Architecture

The capstone requires a system of specialized agents that collaborate via LangGraph orchestration, with evaluation evidence proving that multi-agent coordination beats a simpler single-agent approach.

## Key Concepts

- Core goal: design a multi-agent system that ingests data from various sources (notes, meeting transcriptions, cooking recipes, or any personal content).
- Must include at least three specialized agents working together to research, synthesize information, and learn from interactions — these are the minimum agent roles: research, synthesis, and learning-from-interaction.
- Must show clear evidence via evaluation metrics of concrete benefits from multi-agent architecture (alongside RAG and/or memory systems) versus simpler approaches — the architecture is not just built, it must be justified by measurement.
- Agent orchestration/coordination is done via LangGraph (in-scope requirement).
- Multi-agent orchestration pattern itself (which specific pattern to use) is optional/recommended, not mandated — any multi-agent pattern is acceptable.
- Architectural decision: each agent-backed LangGraph node owns its own LLM model internally rather than the graph constructing or naming a model. Nodes extend `BaseNode` (plain nodes) or `BaseAgentNode` (agent-backed nodes, which wrap a `BaseAgent`/`ClaudeAgent`); the model is constructed inside the node's own `__init__`. Graphs (`graphs/query_graph.py`, `graphs/ingestion_graph.py`) only register nodes — they never construct or name a model.
- This keeps agent identity (which LLM a specialized agent uses) encapsulated per-node instead of centralized in the graph definition, reinforcing the "specialized agents" requirement above: each required role (e.g. orchestrator, memory, synthesis) is its own node class with its own model choice. See [[node-base-class-refactor]] for the full per-node conversion, including the base-class shapes and the complete file-by-file breakdown.

## Sources

- "Second Brain" Capstone Assignment — `docs/business/001-raw-requirement.md`
- Node Base-Class Refactor — Design — `docs/superpowers/specs/2026-07-07-node-base-class-refactor-design.md`

## Related Topics

- [[capstone-requirements]]
- [[tech-stack]]
- [[query-graph]]
- [[second-brain-architecture]]
- [[evaluation-harness]]
- [[autonomous-feature-development-loop]]
- [[git-worktrees]]
- [[query-workflow]]
- [[second-brain-requirements]]
- [[node-base-class-refactor]]
