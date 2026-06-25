# Spec: Fix Missing LangChain OTEL Spans in Phoenix

**Date:** 2026-06-25

---

## Problem

Phoenix shows only FastAPI HTTP spans (`UNKNOWN` kind) when `/query` is called.  
Zero `LLM`, `CHAIN`, or `TOOL` spans appear — LangChain and LangGraph node activity is invisible.

**Confirmed via trace `88001bbe15d4bc3641ab5da122f45f75`:**
```
[UNKNOWN] POST /query          (16057ms)
  [UNKNOWN] POST /query http receive
  [UNKNOWN] POST /query http send
  [UNKNOWN] POST /query http send
```

---

## Root Cause

Two gaps:

1. **Missing package:** `openinference-instrumentation-langchain` is not in `pyproject.toml`.  
   This is the OpenInference instrumentor that patches LangChain's callback system to emit OTEL spans.

2. **Auto-instrumentation not enabled:** `phoenix.otel.register()` is called with `auto_instrument=False` (the default).  
   Even if the package were installed, it would not be activated without this flag.

`FastAPIInstrumentor.instrument_app(app)` is explicitly wired, but the equivalent for LangChain is absent.

---

## Fix

### 1. Add dependency

```
openinference-instrumentation-langchain
```

Added to `apps/backend/pyproject.toml` dependencies.  
Install via `uv sync --all-extras` (or `just init`).

### 2. Enable auto-instrumentation in `setup_tracing()`

Change `register()` call in `src/second_brain/observability/tracing.py`:

```python
return register(
    project_name="second-brain",
    endpoint=phoenix_collection_endpoint,
    auto_instrument=True,   # activates openinference-instrumentation-langchain
)
```

`auto_instrument=True` discovers and activates all installed `openinference-instrumentation-*` packages at startup — no separate `LangChainInstrumentor().instrument()` call needed.

---

## Acceptance Criteria

1. `just test-unit` passes (updated test asserts `auto_instrument=True`).
2. `just lint` and `just type-check` pass clean.
3. After `just up-all`, a `/query` request produces Phoenix spans with `span_kind=LLM` and `span_kind=CHAIN` visible in the `second-brain` project.

---

## Files Changed

| Action | Path |
|--------|------|
| Modify | `apps/backend/pyproject.toml` |
| Modify | `apps/backend/src/second_brain/observability/tracing.py` |
| Modify | `apps/backend/tests/unit/test_observability/test_tracing.py` |
| Modify | `docs/codebase/001-tech-stack.md` |
