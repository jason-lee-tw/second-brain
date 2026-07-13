"""Unit tests for BaseAgentNode._ainvoke_structured retry-on-truncation helper."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel, ValidationError

from second_brain.nodes.base_node.base_agent_node import BaseAgentNode


class _DummyOutput(BaseModel):
  value: str


class _DummyNode(BaseAgentNode[dict, dict]):
  async def __call__(self, state):  # pragma: no cover - not exercised here
    return {}


def _validation_error() -> ValidationError:
  """Build a real ValidationError the same way PydanticToolsParser triggers one."""
  try:
    _DummyOutput.model_validate({})
  except ValidationError as exc:
    return exc
  raise AssertionError("expected ValidationError")


@pytest.mark.asyncio
async def test_ainvoke_structured_returns_first_result_on_success():
  """A successful first call returns that result without a second call."""
  node = _DummyNode(MagicMock())
  structured_llm = MagicMock()
  structured_llm.ainvoke = AsyncMock(return_value=_DummyOutput(value="ok"))

  result = await node._ainvoke_structured(structured_llm, "prompt")

  assert result == _DummyOutput(value="ok")
  assert structured_llm.ainvoke.call_count == 1


@pytest.mark.asyncio
async def test_ainvoke_structured_retries_once_on_validation_error():
  """A ValidationError on the first call triggers exactly one retry."""
  node = _DummyNode(MagicMock())
  structured_llm = MagicMock()
  structured_llm.ainvoke = AsyncMock(
    side_effect=[_validation_error(), _DummyOutput(value="retried")]
  )

  result = await node._ainvoke_structured(structured_llm, "prompt")

  assert result == _DummyOutput(value="retried")
  assert structured_llm.ainvoke.call_count == 2


@pytest.mark.asyncio
async def test_ainvoke_structured_propagates_after_second_failure():
  """Two consecutive ValidationErrors propagate instead of being swallowed."""
  node = _DummyNode(MagicMock())
  structured_llm = MagicMock()
  structured_llm.ainvoke = AsyncMock(
    side_effect=[_validation_error(), _validation_error()]
  )

  with pytest.raises(ValidationError):
    await node._ainvoke_structured(structured_llm, "prompt")

  assert structured_llm.ainvoke.call_count == 2
