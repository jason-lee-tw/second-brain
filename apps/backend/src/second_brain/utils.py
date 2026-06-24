from langchain_core.messages import BaseMessage


def get_str_content(msg: BaseMessage) -> str:
    if not isinstance(msg.content, str):
        raise TypeError(f"Expected str content, got {type(msg.content).__name__}")
    return msg.content
