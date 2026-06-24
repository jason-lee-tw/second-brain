import asyncio
from pathlib import Path

from fastapi import APIRouter

from second_brain.api.schemas import IngestFileResponse, IngestUrlRequest
from second_brain.config import settings
from second_brain.graphs.ingestion_graph import ingestion_graph
from second_brain.graphs.state import IngestionState
from second_brain.services.tavily import crawl_and_save, url_to_slug

router = APIRouter(prefix="/ingest", tags=["ingest"])

PENDING_DOCS_DIR = settings.pending_docs_dir  # patchable in tests


async def _run_ingestion(
    files: list[str],
    source_urls: dict[str, str] | None = None,
) -> IngestFileResponse:
    """Run the ingestion graph and return a response."""
    initial_state: IngestionState = {
        "files": files,
        "in_progress": None,
        "processed": [],
        "retry_queue": [],
        "failed": [],
        "source_urls": source_urls or {},
    }
    final_state = await ingestion_graph.ainvoke(initial_state)
    return IngestFileResponse(
        numberOfFilePassed=len(final_state["processed"]),
        failedFiles=[f["filename"] for f in final_state["failed"]],
    )


@router.post("/file", response_model=IngestFileResponse)
async def ingest_file() -> IngestFileResponse:
    """Ingest all .md files currently in temp/pending-digest-docs/."""
    PENDING_DOCS_DIR.mkdir(parents=True, exist_ok=True)
    files = [f.name for f in PENDING_DOCS_DIR.glob("*.md")]

    if not files:
        return IngestFileResponse(numberOfFilePassed=0, failedFiles=[])

    return await _run_ingestion(files)


@router.post("/url", response_model=IngestFileResponse)
async def ingest_url(request: IngestUrlRequest) -> IngestFileResponse:
    """Crawl each URL via Tavily concurrently, then ingest successfully saved files."""
    results = await asyncio.gather(
        *[crawl_and_save(str(url)) for url in request.urls],
        return_exceptions=True,
    )

    saved_paths: list[Path] = []
    source_urls: dict[str, str] = {}
    failed_crawl_names: list[str] = []

    for url, result in zip(request.urls, results):
        # BaseException (not Exception): asyncio.CancelledError is
        # BaseException in Python 3.8+; gather(return_exceptions=True)
        # returns it in the results list, so plain Exception would miss it.
        if isinstance(result, BaseException):
            # note: failed-crawl names use slug-only (no hash);
            # they are best-effort error labels
            failed_crawl_names.append(f"{url_to_slug(str(url))}.md")
        else:
            saved_paths.append(result)
            source_urls[result.name] = str(url)

    if not saved_paths:
        return IngestFileResponse(numberOfFilePassed=0, failedFiles=failed_crawl_names)

    ingestion_result = await _run_ingestion(
        [p.name for p in saved_paths], source_urls=source_urls
    )
    return ingestion_result.model_copy(
        update={"failedFiles": failed_crawl_names + ingestion_result.failedFiles}
    )
