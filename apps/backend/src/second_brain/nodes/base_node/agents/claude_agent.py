from enum import StrEnum

from langchain_anthropic import ChatAnthropic

from second_brain.config import settings

from .base_agent import BaseAgent


class CLAUDE_MODEL_NAME(StrEnum):
  SONNET = "claude-sonnet-5"
  HAIKU = "claude-haiku-4-5-20251001"


class ClaudeAgent(BaseAgent):
  def __init__(
    self,
    model_name: CLAUDE_MODEL_NAME,
    timeout_in_second: int = 180,
    temperature: float = 0.7,
    max_retries: int = 3,
  ):
    api_key = settings.anthropic_api_key

    model = ChatAnthropic(
      api_key=api_key,
      temperature=temperature,
      model_name=model_name,
      stop=None,
      timeout=timeout_in_second,
      max_retries=max_retries,
    )

    super().__init__(model)
