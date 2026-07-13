# OTEL + Phoenix Tracing

OpenTelemetry instruments the FastAPI backend and exports traces to Arize Phoenix, with the backend reaching Phoenix only through a host-published port rather than a shared Docker network.

## Key Concepts

- **Setup flow**: `setup_tracing(phoenix_collection_endpoint, service_name="second-brain")` (in `apps/backend/src/second_brain/observability/tracing.py`) is called once at FastAPI startup, inside the app's `lifespan`, and delegates to `phoenix.otel.register(project_name=service_name, endpoint=phoenix_collection_endpoint)` — the call that both configures and returns the global OTEL `TracerProvider`.
- **HTTP-level spans**: `FastAPIInstrumentor.instrument_app(app)` is wired at module level (immediately after `app = FastAPI(lifespan=lifespan)`, not inside the lifespan) so the OTEL middleware exists before any request arrives, giving every HTTP request an automatic root span (e.g. `GET /health`).
- **Node-level spans**: a `trace_node(name)` decorator wraps async LangGraph node functions with a child span (via `trace.get_tracer(__name__).start_as_current_span(name)`), nesting under whichever span is active when the node runs — e.g. `@trace_node("orchestrator")`.
- **Config**: `Settings.phoenix_collection_endpoint` defaults to `"http://host.docker.internal:4317"` (documented in `.env.template` as `PHOENIX_COLLECTION_ENDPOINT`, with an override note for Linux hosts).
- **Network isolation is the core architectural rule**: the backend container never joins `phoenix_network` — it lives in `app_network` alongside `app_postgres`, while Phoenix and its own `phoenix_postgres` live in the isolated `phoenix_network`. Traces reach Phoenix only via OTLP gRPC on host port 4317; the Phoenix UI itself is served separately at `localhost:6006`.
- **Linux Docker hosts need `extra_hosts`**: `docker-compose.yml` adds `extra_hosts: ["host.docker.internal:host-gateway"]` to the `backend` service (the `ollama-checker` service already carried the same entry for the same reason) because Docker Desktop (Mac/Windows) auto-resolves `host.docker.internal` inside containers but Linux Docker hosts do not.
- **Three levels of observability per `/query` request**: LLM call level (prompt/completion, token counts, latency), agent/node level (which agents ran, order, duration, routing decision), and request level (end-to-end HTTP request → response).
- **FastAPI instrumentation caveat (from tests)**: never call `FastAPIInstrumentor().uninstrument()` in teardown — it strips instrumentation globally from every app in the process, including the real `main.app`, breaking other tests in the same session.
- **Verification pattern**: `docker compose up -d`, `curl -s http://localhost:8000/health` → `{"status": "ok"}`, then open the Phoenix UI at `http://localhost:6006`, navigate to Projects → `second-brain`, and confirm a root span named `GET /health` appears with duration/status in the waterfall.
- **Later refinement — LangChain/LangGraph spans**: this initial build only wired HTTP-level spans explicitly; LangChain/LangGraph internals (`LLM`/`CHAIN`/`TOOL` span kinds) needed a separate fix — enabling `auto_instrument=True` on `phoenix.otel.register()` plus the `openinference-instrumentation-langchain` package. See [[langchain-otel-instrumentation]] for that fix rather than duplicating it here.

## Open Questions

- **Backend published port**: this page's verification step curls `http://localhost:8000/health`, but [[docker-compose]], [[database-migration-container]], [[langchain-otel-instrumentation]], and [[asyncpg-jsonb-codec]] consistently use port `3001`. Unresolved — needs source verification of which port is correct.

## Sources

- OpenTelemetry + Arize Phoenix Tracing Implementation Plan — `docs/superpowers/plans/2026-06-16-ticket-2-otel-phoenix.md`
- Tech Stack — `docs/codebase/001-tech-stack.md`
- System Architecture — `docs/codebase/003-system-architecture.md`

## Related Topics

- [[langchain-otel-instrumentation]]
- [[docker-compose]]
- [[system-architecture]]
- [[tech-stack]]
- [[capstone-requirements]]
- [[implementation-plan]]
- [[second-brain-architecture]]
- [[second-brain-requirements]]
