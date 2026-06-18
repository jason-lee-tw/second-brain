---
name: phoenix-trace-fetcher
description: Use when the user asks to fetch, inspect, or grep a trace from Arize Phoenix — either by trace ID or "most recent trace". Also use when debugging agent/LLM workflows and needing to see span details, token counts, or span tree hierarchy from Phoenix tracing.
---

# Phoenix Trace Fetcher

Fetch and display traces from Arize Phoenix. The script is self-contained — `uv run` reads its inline dependency block and manages an isolated venv automatically. No project venv needed.

## Default Hosts

| Protocol           | Default URL             |
| ------------------ | ----------------------- |
| HTTP (UI + REST)   | `http://localhost:6006` |
| gRPC (OTLP ingest) | `http://localhost:4317` |

Use the HTTP URL for all client API calls. Inside Docker, replace `localhost` with `phoenix`.

## Quick Decision

- User gives a **trace ID** → fetch spans by that trace ID
- User asks for **most recent trace** → list traces (desc), grab first, then fetch its spans
- **Project name unknown** → list projects first, pick the right one

## Step-by-Step

### 1. Resolve project identifier

```python
from phoenix.client import Client
client = Client(base_url="http://localhost:6006")

resp = client._client.get("v1/projects", headers={"accept": "application/json"}, timeout=5)
projects = resp.json()["data"]
for p in projects:
    print(p["name"], p["id"])
```

Default project in this repo: `investment-report-app-backend-local`

### 2a. Fetch by trace ID

```python
trace_id = "693f03113899b868b23c8d1d1fdebf15"
spans = client.spans.get_spans(
    project_identifier="investment-report-app-backend-local",
    trace_ids=[trace_id],
    limit=200,
)
```

### 2b. Fetch most recent trace

```python
traces = client.traces.get_traces(
    project_identifier="investment-report-app-backend-local",
    limit=1,
    sort="start_time",
    order="desc",
)
trace_id = traces[0]["trace_id"]

spans = client.spans.get_spans(
    project_identifier="investment-report-app-backend-local",
    trace_ids=[trace_id],
    limit=200,
)
```

### 3. Print span tree

`fetch_trace.py` uses PEP 723 inline script metadata — `uv run` installs its own isolated venv on first run (cached afterwards):

```bash
# by trace ID
uv run .claude/skills/phoenix-trace-fetcher/fetch_trace.py 693f03113899b868b23c8d1d1fdebf15

# most recent trace
uv run .claude/skills/phoenix-trace-fetcher/fetch_trace.py

# override project or host
PHOENIX_PROJECT=default PHOENIX_HOST=http://phoenix:6006 \
  uv run .claude/skills/phoenix-trace-fetcher/fetch_trace.py [TRACE_ID]
```

## Span Object Shape

```
{
  "id": "U3Bhbjo5MjY=",         # Phoenix GlobalID
  "name": "ChatAnthropic",
  "context": {
    "trace_id": "693f...",
    "span_id": "573361a1..."     # OTel hex span ID
  },
  "span_kind": "LLM",           # CHAIN | LLM | TOOL | RETRIEVER | UNKNOWN
  "parent_id": "abc123...",     # null for root span
  "start_time": "2026-06-09T02:01:36.774107+00:00",
  "end_time": "...",
  "status_code": "OK",          # OK | ERROR | UNSET
  "status_message": "",
  "attributes": { ... },        # LLM token counts, HTTP fields, etc.
  "events": [ ... ]
}
```

Key attributes for LLM spans:

- `llm.token_count.prompt` / `llm.token_count.completion` / `llm.token_count.total`
- `llm.input_messages` / `llm.output_messages`
- `llm.model_name`

## Common Mistakes

| Mistake                                                          | Fix                                                                        |
| ---------------------------------------------------------------- | -------------------------------------------------------------------------- |
| Hitting `http://localhost:6006/v1/traces` as REST — returns HTML | Use `client.spans.get_spans()` or `client.traces.get_traces()` instead     |
| `trace_ids` param needs server >= 13.9.0                         | Current install is 17.x, safe to use                                       |
| Only 100 spans returned                                          | Default `limit=100`; set `limit=200` for large traces                      |
| Project not found                                                | List projects first; name is `investment-report-app-backend-local` locally |
