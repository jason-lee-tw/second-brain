from typing import Optional

from pydantic import AnyHttpUrl, BaseModel


class IngestFileResponse(BaseModel):
    numberOfFilePassed: int
    failedFiles: list[str]


class IngestUrlRequest(BaseModel):
    urls: list[AnyHttpUrl]


class QueryRequest(BaseModel):
    message: str
    sessionId: Optional[str] = None  # UUID7 or null for new session


class QueryResponse(BaseModel):
    answer: str
    sessionId: str  # UUID7 — use this in the next call to continue the session
    confidence: float  # 0.0-1.0
    isUncertain: bool  # True when confidence < 0.7; prompts user to optionally correct
    conflictDetected: bool  # True when a new fact conflicts with existing memory
    conflictContext: list[str]  # Descriptions of detected conflicts, if any
