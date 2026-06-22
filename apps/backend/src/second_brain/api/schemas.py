from typing import Optional

from pydantic import AnyHttpUrl, BaseModel


class IngestFileResponse(BaseModel):
    numberOfFilePassed: int
    failedFiles: list[str]


class IngestUrlRequest(BaseModel):
    urls: list[AnyHttpUrl]


class QueryRequest(BaseModel):
    message: str
    sessionId: Optional[str] = None


class QueryResponse(BaseModel):
    answer: str
    sessionId: str
    confidence: float
    isUncertain: bool
    conflictDetected: bool
    conflictContext: list[str]
