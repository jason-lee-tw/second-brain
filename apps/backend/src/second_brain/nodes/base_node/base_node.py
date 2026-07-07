from abc import ABC, abstractmethod
from collections.abc import Awaitable

type ResponseStateType = object


class BaseNode[InputStateType, ResultStateType](ABC):
  def __init__(self):
    super().__init__()

  @abstractmethod
  def __call__(
    self, state: InputStateType
  ) -> Awaitable[ResultStateType] | ResultStateType: ...
