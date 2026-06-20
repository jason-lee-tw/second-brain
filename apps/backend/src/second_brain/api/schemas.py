from pydantic import AnyHttpUrl, BaseModel


class IngestFileResponse(BaseModel):
    numberOfFilePassed: int
    failedFiles: list[str]


class IngestUrlRequest(BaseModel):
    urls: list[AnyHttpUrl]
