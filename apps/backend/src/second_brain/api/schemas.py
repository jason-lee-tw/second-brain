from pydantic import BaseModel


class IngestFileResponse(BaseModel):
    numberOfFilePassed: int
    failedFiles: list[str]


class IngestUrlRequest(BaseModel):
    urls: list[str]
