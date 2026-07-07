"""PickFileNode: moves the next pending or retry file into in_progress."""

from typing import override

from second_brain.graphs.state import IngestionState, PickFileOutput
from second_brain.nodes.base_node import BaseNode


class PickFileNode(BaseNode[IngestionState, PickFileOutput]):
  """Move the next pending or retry file into in_progress.

  Priority: files[] (first-timers) before retry_queue.
  Does NOT remove the item from retry_queue — ingestion_agent_node does that
  after the attempt to preserve retry metadata for retry_count tracking.
  """

  @override
  def __call__(self, state: IngestionState) -> PickFileOutput:
    if state["files"]:
      return {
        "files": state["files"][1:],
        "in_progress": state["files"][0],
      }
    if state["retry_queue"]:
      return {
        "in_progress": state["retry_queue"][0]["filename"],
      }
    return {"in_progress": None}


pick_file_node = PickFileNode()
