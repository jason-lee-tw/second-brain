from abc import ABC, abstractmethod
from collections.abc import Awaitable


class BaseNode[InputStateType, ResultStateType](ABC):
  def __init__(self):
    super().__init__()

  @abstractmethod
  def __call__(
    self, state: InputStateType
  ) -> Awaitable[ResultStateType] | ResultStateType: ...
