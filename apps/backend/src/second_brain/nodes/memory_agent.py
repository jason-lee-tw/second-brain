"""MemoryAgentNode: classifies user message into one of three MemoryCase values."""

from __future__ import annotations

from typing import override

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from second_brain.graphs.state import (
  ConflictContext,
  MemoryAgentOutput,
  SecondBrainState,
)
from second_brain.nodes.base_node import BaseAgentNode
from second_brain.nodes.base_node.agents import CLAUDE_MODEL_NAME, ClaudeAgent
from second_brain.utils import get_str_content, last_human_message


def _prior_ai_content(messages: list[BaseMessage]) -> str:
  last_human_idx: int | None = None
  for i in range(len(messages) - 1, -1, -1):
    if isinstance(messages[i], HumanMessage):
      last_human_idx = i
      break
  if last_human_idx is None or last_human_idx == 0:
    return ""
  for i in range(last_human_idx - 1, -1, -1):
    if isinstance(messages[i], AIMessage):
      return get_str_content(messages[i])
  return ""


class MemoryAgentNode(BaseAgentNode[SecondBrainState, dict[str, object]]):
  """Three-case memory classification via LangChain-Anthropic structured output."""

  def __init__(self):
    super().__init__(ClaudeAgent(CLAUDE_MODEL_NAME.HAIKU, max_tokens=4096))
    self._llm = self._agent.get_model().with_structured_output(MemoryAgentOutput)

  @override
  async def __call__(self, state: SecondBrainState) -> dict[str, object]:
    messages = state["messages"]
    awaiting_correction: bool = state.get("awaiting_correction", False)  # type: ignore[union-attr]
    awaiting_conflict: bool = state.get("awaiting_conflict_clarification", False)  # type: ignore[union-attr]
    conflict_context: list[ConflictContext] = state.get("conflict_context", [])  # type: ignore[union-attr]

    human_msg = last_human_message(messages)
    if human_msg is None:
      return {"fact_updates": [], "correction_updates": []}
    user_text = get_str_content(human_msg)

    if awaiting_conflict:
      # Case 3: conflict clarification — pass existing_ids so LLM can populate
      # conflicts_with; persistence uses that to delete replaced facts (F1 fix)
      conflict_summary = "\n".join(
        f'- existing_id={c["existing_id"]} | Existing: "{c["existing"]}"'
        f' | New: "{c["new"]}"'
        for c in conflict_context
      )
      prompt = (
        "The user previously had a memory conflict that needs clarifying.\n\n"
        f"Conflicts:\n{conflict_summary}\n\n"
        f"User clarification: {user_text!r}\n\n"
        "case=conflict_resolution. Populate fact_updates with the resolved "
        "fact(s). Set conflicts_with to the existing_id(s) of the facts being "
        "replaced — this triggers deletion of the old facts before writing "
        "the new one. If the user chose to keep the existing fact, return "
        "empty fact_updates."
      )
    elif awaiting_correction:
      # Case 2: correction check
      prior_ai = _prior_ai_content(messages)
      prompt = (
        f"The AI gave an uncertain answer: {prior_ai!r}\n"
        f"The user responded: {user_text!r}\n\n"
        "Decide: is the user explicitly correcting the AI's answer on the "
        "SAME topic, or are they asking a completely different question?\n\n"
        "CORRECTION (case=correction): user directly contradicts or fixes the "
        "AI's answer on the same topic (e.g. 'Actually it is X', 'You are "
        "wrong, the answer is Y'). Populate correction_updates with "
        "original_answer, correction, root_cause.\n\n"
        "NOT a correction (case=fact_extraction): user asks about a "
        "completely different topic, ignores the prior answer, or asks a "
        "question unrelated to what the AI was uncertain about. In this case "
        "extract any self-referential facts into fact_updates (or leave "
        "empty).\n\n"
        "If in doubt, prefer case=fact_extraction over case=correction."
      )
    else:
      # Case 1: normal fact extraction
      prompt = (
        f"User message: {user_text!r}\n\n"
        "case=fact_extraction. Extract self-referential facts (statements "
        "where the user describes themselves, e.g. 'I work as X', 'I live "
        "in Y', 'I prefer Z'). Return empty fact_updates if none exist. "
        "Set conflicts_with=[] for every fact."
      )

    output: MemoryAgentOutput = await self._ainvoke_structured(  # pyright: ignore[reportAssignmentType]
      self._llm, prompt
    )

    # F1 fix: in Case 3 the LLM may omit conflicts_with UUIDs (unreliable).
    # The pending_facts stored in state["fact_updates"] from the previous turn
    # already carry the correct conflicts_with — copy those over when empty so
    # _persist_fact can delete the replaced fact without re-running _conflict_check.
    fact_updates_out = list(output.fact_updates)
    if awaiting_conflict:
      pending_facts = state.get("fact_updates") or []  # type: ignore[union-attr]
      annotated = []
      for i, llm_fact in enumerate(fact_updates_out):
        if not llm_fact.get("conflicts_with") and i < len(pending_facts):
          annotated.append(
            {**llm_fact, "conflicts_with": pending_facts[i]["conflicts_with"]}
          )
        else:
          annotated.append(llm_fact)
      fact_updates_out = annotated

    updates: dict[str, object] = {
      "fact_updates": fact_updates_out,
      "correction_updates": list(output.correction_updates),
    }

    # State machine transitions
    if awaiting_conflict:
      # D4: mutually exclusive — reset both flags
      updates["awaiting_conflict_clarification"] = False
      updates["awaiting_correction"] = False
      updates["conflict_context"] = []
    elif awaiting_correction:
      updates["awaiting_correction"] = False

    return updates


memory_agent_node = MemoryAgentNode()
