from abc import ABC, abstractmethod
from collections.abc import Awaitable

from .agents import BaseAgent


class BaseAgentNode[InputStateType, ResultStateType](ABC):
  _agent: BaseAgent

  def __init__(self, agent: BaseAgent):
    super().__init__()
    self._agent = agent

  @abstractmethod
  def __call__(
    self, state: InputStateType
  ) -> Awaitable[ResultStateType] | ResultStateType: ...
