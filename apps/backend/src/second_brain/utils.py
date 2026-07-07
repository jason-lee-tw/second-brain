from langchain_core.messages import BaseMessage, HumanMessage


def get_str_content(msg: BaseMessage) -> str:
  if not isinstance(msg.content, str):
    raise TypeError(f"Expected str content, got {type(msg.content).__name__}")  # pyright: ignore[reportUnknownArgumentType]
  return msg.content


def last_human_message(messages: list[BaseMessage]) -> HumanMessage | None:
  """Return the most recent HumanMessage by walking the list in reverse."""
  for msg in reversed(messages):
    if isinstance(msg, HumanMessage):
      return msg
  return None
