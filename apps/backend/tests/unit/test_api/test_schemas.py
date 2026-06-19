# apps/backend/tests/unit/test_api/test_schemas.py
import pytest
from pydantic import ValidationError

from second_brain.api.schemas import IngestFileResponse, IngestUrlRequest


def test_ingest_file_response_valid():
    resp = IngestFileResponse(numberOfFilePassed=5, failedFiles=["bad.md"])
    assert resp.numberOfFilePassed == 5
    assert resp.failedFiles == ["bad.md"]


def test_ingest_file_response_serializes_to_camel_case_keys():
    resp = IngestFileResponse(numberOfFilePassed=2, failedFiles=[])
    data = resp.model_dump()
    assert "numberOfFilePassed" in data
    assert "failedFiles" in data


def test_ingest_file_response_defaults_empty_failed_files():
    resp = IngestFileResponse(numberOfFilePassed=0, failedFiles=[])
    assert resp.failedFiles == []


def test_ingest_url_request_valid():
    req = IngestUrlRequest(urls=["https://example.com", "https://other.com"])
    assert len(req.urls) == 2
    assert req.urls[0] == "https://example.com"


def test_ingest_url_request_rejects_missing_urls():
    with pytest.raises(ValidationError):
        IngestUrlRequest()  # urls is required
