from abc import ABC, abstractmethod
from collections.abc import Awaitable

from langchain_core.language_models import LanguageModelInput
from langchain_core.runnables import Runnable
from pydantic import ValidationError

from .agents import BaseAgent


class BaseAgentNode[InputStateType, ResultStateType](ABC):
  _agent: BaseAgent

  def __init__(self, agent: BaseAgent):
    super().__init__()
    self._agent = agent

  async def _ainvoke_structured[T](
    self, structured_llm: Runnable[LanguageModelInput, T], prompt: str
  ) -> T:
    """Invoke a structured-output Runnable, retrying once on ValidationError.

    Anthropic's tool-use `required` schema fields are advisory only — a
    completion truncated by max_tokens can omit one, which PydanticToolsParser
    surfaces as a ValidationError. One retry absorbs that transient
    truncation; a second failure means it isn't transient.
    """
    try:
      return await structured_llm.ainvoke(prompt)
    except ValidationError:
      return await structured_llm.ainvoke(prompt)

  @abstractmethod
  def __call__(
    self, state: InputStateType
  ) -> Awaitable[ResultStateType] | ResultStateType: ...
