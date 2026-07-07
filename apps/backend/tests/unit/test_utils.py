# apps/backend/tests/unit/test_utils.py
"""Tests for second_brain.utils."""

import pytest
from langchain_core.messages import HumanMessage

from second_brain.utils import get_str_content


def test_get_str_content_returns_str_content():
  """Returns the string content unchanged."""
  msg = HumanMessage(content="hello world")
  assert get_str_content(msg) == "hello world"


def test_get_str_content_returns_empty_string():
  """Empty string content is a valid string — returns it as-is."""
  msg = HumanMessage(content="")
  assert get_str_content(msg) == ""


def test_get_str_content_raises_on_list_content():
  """Raises TypeError when content is a multi-modal list, not a plain string."""
  msg = HumanMessage(content=[{"type": "text", "text": "hello"}])
  with pytest.raises(TypeError, match="Expected str content"):
    get_str_content(msg)


def test_get_str_content_error_message_includes_actual_type():
  """TypeError message names the actual type so callers can diagnose the problem."""
  msg = HumanMessage(content=[{"type": "image_url", "url": "..."}])
  with pytest.raises(TypeError, match="list"):
    get_str_content(msg)
