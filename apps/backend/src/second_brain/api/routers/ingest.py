from pathlib import Path

from fastapi import APIRouter

from second_brain.api.schemas import IngestFileResponse, IngestUrlRequest
from second_brain.graphs.ingestion_graph import ingestion_graph
from second_brain.graphs.state import IngestionState
from second_brain.services.tavily import crawl_and_save

router = APIRouter(prefix="/ingest", tags=["ingest"])

PENDING_DOCS_DIR = Path("temp/pending-digest-docs")


@router.post("/file", response_model=IngestFileResponse)
async def ingest_file() -> IngestFileResponse:
    """Ingest all .md files currently in temp/pending-digest-docs/."""
    PENDING_DOCS_DIR.mkdir(parents=True, exist_ok=True)
    files = [f.name for f in PENDING_DOCS_DIR.glob("*.md")]

    if not files:
        return IngestFileResponse(numberOfFilePassed=0, failedFiles=[])

    initial_state: IngestionState = {
        "files": files,
        "in_progress": [],
        "processed": [],
        "retry_queue": [],
        "failed": [],
    }

    final_state = await ingestion_graph.ainvoke(initial_state)

    return IngestFileResponse(
        numberOfFilePassed=len(final_state["processed"]),
        failedFiles=[f["filename"] for f in final_state["failed"]],
    )


@router.post("/url", response_model=IngestFileResponse)
async def ingest_url(request: IngestUrlRequest) -> IngestFileResponse:
    """Crawl each URL via Tavily, save as markdown, then ingest."""
    saved_files: list[str] = []
    for url in request.urls:
        filepath = await crawl_and_save(url)
        saved_files.append(filepath.name)

    if not saved_files:
        return IngestFileResponse(numberOfFilePassed=0, failedFiles=[])

    initial_state: IngestionState = {
        "files": saved_files,
        "in_progress": [],
        "processed": [],
        "retry_queue": [],
        "failed": [],
    }

    final_state = await ingestion_graph.ainvoke(initial_state)

    return IngestFileResponse(
        numberOfFilePassed=len(final_state["processed"]),
        failedFiles=[f["filename"] for f in final_state["failed"]],
    )
