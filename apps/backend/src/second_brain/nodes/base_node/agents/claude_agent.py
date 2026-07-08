from enum import StrEnum
from typing import Any

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
    temperature: float | None = 0.7,
    max_retries: int = 3,
  ):
    api_key = settings.anthropic_api_key

    kwargs: dict[str, Any] = dict(
      api_key=api_key,
      model_name=model_name,
      stop=None,
      timeout=timeout_in_second,
      max_retries=max_retries,
    )
    # Some models (e.g. claude-sonnet-5) reject the `temperature` kwarg outright,
    # so it must be omitted entirely rather than forwarded as None.
    if temperature is not None:
      kwargs["temperature"] = temperature

    model = ChatAnthropic(**kwargs)

    super().__init__(model)
