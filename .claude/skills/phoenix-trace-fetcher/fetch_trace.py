#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "arize-phoenix-client==2.7.0",
# ]
# ///
"""Fetch and print a Phoenix trace as an indented span tree.

Usage:
    uv run .claude/skills/phoenix-trace-fetcher/fetch_trace.py [TRACE_ID]
    uv run .claude/skills/phoenix-trace-fetcher/fetch_trace.py
    PHOENIX_HOST=http://phoenix:6006 uv run ... fetch_trace.py [TRACE_ID]
"""

import os
import sys
from datetime import datetime

from phoenix.client import Client
from phoenix.client.__generated__ import v1

PROJECT = os.getenv("PHOENIX_PROJECT", "investment-report-app-backend-local")
HOST = os.getenv("PHOENIX_HOST", "http://localhost:6006")


def _duration(start: str, end: str | None) -> str:
    if not end:
        return "?"
    try:
        delta = datetime.fromisoformat(end) - datetime.fromisoformat(start)
        ms = int(delta.total_seconds() * 1000)
        return f"{ms}ms"
    except Exception:
        return "?"


def _token_info(attrs: dict[str, object]) -> str:
    total = attrs.get("llm.token_count.total")
    if total is None:
        return ""
    prompt = attrs.get("llm.token_count.prompt", "?")
    completion = attrs.get("llm.token_count.completion", "?")
    return f"  [{prompt}→{completion}={total} tok]"


def print_tree(
    spans: list[v1.Span],
    parent_id: str | None = None,
    depth: int = 0,
) -> None:
    children = [s for s in spans if s.get("parent_id") == parent_id]
    for span in children:
        indent = "  " * depth
        ctx = span["context"]
        dur = _duration(span["start_time"], span.get("end_time"))
        status = span.get("status_code", "UNSET")
        status_flag = " [ERROR]" if status == "ERROR" else ""
        tok = _token_info(span.get("attributes") or {})  # type: ignore[arg-type]
        span_id: str = ctx["span_id"]
        print(
            f"{indent}[{span['span_kind']}] {span['name']}"
            f"  ({dur}){tok}{status_flag}"
            f"  span={span_id[:8]}"
        )
        print_tree(spans, parent_id=span_id, depth=depth + 1)


def resolve_trace_id(client: Client, explicit: str | None) -> str:
    if explicit:
        return explicit
    traces = client.traces.get_traces(
        project_identifier=PROJECT,
        limit=1,
        sort="start_time",
        order="desc",
    )
    if not traces:
        print("No traces found.", file=sys.stderr)
        sys.exit(1)
    trace_id: str = traces[0]["trace_id"]
    print(f"Most recent trace: {trace_id}\n")
    return trace_id


def main() -> None:
    explicit_id = sys.argv[1] if len(sys.argv) > 1 else None
    client = Client(base_url=HOST)

    trace_id = resolve_trace_id(client, explicit_id)

    spans = client.spans.get_spans(
        project_identifier=PROJECT,
        trace_ids=[trace_id],
        limit=200,
    )

    if not spans:
        print(f"No spans found for trace {trace_id}", file=sys.stderr)
        sys.exit(1)

    spans.sort(key=lambda s: s["start_time"])

    root = next((s for s in spans if s.get("parent_id") is None), None)
    start = root["start_time"] if root else spans[0]["start_time"]
    end = root.get("end_time") if root else None
    total = _duration(start, end)

    print(f"Trace: {trace_id}  ({len(spans)} spans, {total} total)\n")
    print_tree(spans)


if __name__ == "__main__":
    main()
