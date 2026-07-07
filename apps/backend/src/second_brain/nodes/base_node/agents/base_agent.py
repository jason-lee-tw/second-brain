from abc import ABC

from langchain.chat_models.base import BaseChatModel


class BaseAgent(ABC):
  __model: BaseChatModel

  def __init__(self, model: BaseChatModel):
    super().__init__()
    self.__model = model

  def get_model(self) -> BaseChatModel:
    return self.__model
