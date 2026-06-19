from typing import TypedDict


class FailedFile(TypedDict):
    filename: str
    error: str
    retry_count: int


class IngestionState(TypedDict):
    files: list[str]                # original input queue (first-attempt files)
    in_progress: list[str]          # crash-safe in-flight tracking (0 or 1 item)
    processed: list[str]            # successfully ingested filenames
    retry_queue: list[FailedFile]   # retry_count < 3 (terminal threshold)
    failed: list[FailedFile]        # terminal failures: retry_count >= 3
