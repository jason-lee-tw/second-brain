"""Unit tests for ClaudeAgent's temperature handling.

Regression guard for: claude-sonnet-5 rejects the `temperature` kwarg entirely
(anthropic.BadRequestError: "`temperature` is deprecated for this model."),
so ClaudeAgent must omit it from the ChatAnthropic call when temperature=None.
"""

from unittest.mock import MagicMock, patch

from second_brain.nodes.base_node.agents import CLAUDE_MODEL_NAME, ClaudeAgent


@patch("second_brain.nodes.base_node.agents.claude_agent.ChatAnthropic")
def test_claude_agent_omits_temperature_when_none(mock_chat_anthropic: MagicMock):
  """When temperature=None, ChatAnthropic must be constructed without `temperature`.

  Sonnet-5 rejects the parameter outright, so it must not be forwarded at all.
  """
  ClaudeAgent(CLAUDE_MODEL_NAME.SONNET, temperature=None)

  _, kwargs = mock_chat_anthropic.call_args
  assert "temperature" not in kwargs


@patch("second_brain.nodes.base_node.agents.claude_agent.ChatAnthropic")
def test_claude_agent_defaults_temperature_to_0_7(mock_chat_anthropic: MagicMock):
  """Callers that don't pass temperature explicitly still get 0.7 (e.g. HAIKU nodes)."""
  ClaudeAgent(CLAUDE_MODEL_NAME.HAIKU)

  _, kwargs = mock_chat_anthropic.call_args
  assert kwargs["temperature"] == 0.7


@patch("second_brain.nodes.base_node.agents.claude_agent.ChatAnthropic")
def test_claude_agent_forwards_explicit_temperature(mock_chat_anthropic: MagicMock):
  """An explicit non-None temperature is still forwarded as-is."""
  ClaudeAgent(CLAUDE_MODEL_NAME.HAIKU, temperature=0.2)

  _, kwargs = mock_chat_anthropic.call_args
  assert kwargs["temperature"] == 0.2
