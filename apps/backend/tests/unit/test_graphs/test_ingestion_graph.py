# apps/backend/tests/unit/test_graphs/test_ingestion_graph.py
from unittest.mock import patch

import pytest

from second_brain.graphs.state import IngestionState


def _make_state(**overrides) -> IngestionState:
  base: IngestionState = {
    "files": [],
    "in_progress": None,
    "processed": [],
    "retry_queue": [],
    "failed": [],
  }
  base.update(overrides)
  return base


_PATCH_TARGET = "second_brain.graphs.ingestion_graph.ingestion_agent_node"


@pytest.mark.asyncio
async def test_graph_processes_single_file():
  """Graph with one file in files[] should result in that file in processed."""

  async def fake_ingest_node(state):
    filename = state["in_progress"]
    return {
      "processed": state["processed"] + [filename],
      "in_progress": None,
      "retry_queue": state["retry_queue"],
    }

  with patch(_PATCH_TARGET, fake_ingest_node):
    from second_brain.graphs.ingestion_graph import build_ingestion_graph

    graph = build_ingestion_graph()
    initial = _make_state(files=["a.md"])
    result = await graph.ainvoke(initial)

  assert "a.md" in result["processed"]
  assert result["failed"] == []
  assert result["in_progress"] is None


@pytest.mark.asyncio
async def test_graph_processes_multiple_files_sequentially():
  """Graph with two files must process both."""

  async def fake_ingest_node(state):
    filename = state["in_progress"]
    return {
      "processed": state["processed"] + [filename],
      "in_progress": None,
      "retry_queue": [],
    }

  with patch(_PATCH_TARGET, fake_ingest_node):
    from second_brain.graphs.ingestion_graph import build_ingestion_graph

    graph = build_ingestion_graph()
    initial = _make_state(files=["a.md", "b.md"])
    result = await graph.ainvoke(initial)

  assert set(result["processed"]) == {"a.md", "b.md"}
  assert result["failed"] == []


@pytest.mark.asyncio
async def test_graph_retries_failed_file():
  """A file that fails on first attempt (retry_count=1) must be retried."""
  call_count = {"n": 0}

  async def fake_ingest_node(state):
    filename = state["in_progress"]
    new_retry_queue = [f for f in state["retry_queue"] if f["filename"] != filename]
    call_count["n"] += 1

    if call_count["n"] == 1:
      return {
        "in_progress": None,
        "retry_queue": new_retry_queue
        + [{"filename": filename, "error": "transient", "retry_count": 1}],
      }
    else:
      return {
        "processed": state["processed"] + [filename],
        "in_progress": None,
        "retry_queue": new_retry_queue,
      }

  with patch(_PATCH_TARGET, fake_ingest_node):
    from second_brain.graphs.ingestion_graph import build_ingestion_graph

    graph = build_ingestion_graph()
    initial = _make_state(files=["flaky.md"])
    result = await graph.ainvoke(initial)

  assert "flaky.md" in result["processed"]
  assert result["failed"] == []
  assert call_count["n"] == 2


@pytest.mark.asyncio
async def test_graph_terminates_when_all_files_done():
  """Graph must terminate (not loop forever) once all files are processed."""

  async def fake_ingest_node(state):
    filename = state["in_progress"]
    return {
      "processed": state["processed"] + [filename],
      "in_progress": None,
      "retry_queue": [],
    }

  with patch(_PATCH_TARGET, fake_ingest_node):
    from second_brain.graphs.ingestion_graph import build_ingestion_graph

    graph = build_ingestion_graph()
    result = await graph.ainvoke(_make_state(files=["x.md"]))

  assert result["files"] == []
  assert result["retry_queue"] == []


@pytest.mark.asyncio
async def test_graph_emits_span_for_ingest_node_but_not_pick_file():
  """The 'ingest' node must emit a span; 'pick_file' (sync, no I/O) must not."""
  from opentelemetry import trace
  from opentelemetry.sdk.trace import TracerProvider
  from opentelemetry.sdk.trace.export import SimpleSpanProcessor
  from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
  )

  exporter = InMemorySpanExporter()
  provider = TracerProvider()
  provider.add_span_processor(SimpleSpanProcessor(exporter))
  original_provider = trace.get_tracer_provider()
  trace.set_tracer_provider(provider)

  async def fake_ingest_node(state):
    filename = state["in_progress"]
    return {
      "processed": state["processed"] + [filename],
      "in_progress": None,
      "retry_queue": [],
    }

  try:
    with patch(_PATCH_TARGET, fake_ingest_node):
      from second_brain.graphs.ingestion_graph import build_ingestion_graph

      graph = build_ingestion_graph()
      await graph.ainvoke(_make_state(files=["a.md"]))
  finally:
    trace.set_tracer_provider(original_provider)

  span_names = [s.name for s in exporter.get_finished_spans()]
  assert "ingest" in span_names
  assert "pick_file" not in span_names
