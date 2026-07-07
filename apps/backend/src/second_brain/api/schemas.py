from pydantic import AnyHttpUrl, BaseModel


class IngestFileResponse(BaseModel):
  numberOfFilePassed: int
  failedFiles: list[str]


class IngestUrlRequest(BaseModel):
  urls: list[AnyHttpUrl]


class QueryRequest(BaseModel):
  message: str
  sessionId: str | None = None


class ConflictContextItem(BaseModel):
  existing: str
  existing_id: str
  new: str


class QueryResponse(BaseModel):
  answer: str
  sessionId: str
  confidence: float
  isUncertain: bool
  conflictDetected: bool
  conflictContext: list[ConflictContextItem]
  retrievedContexts: list[str]
