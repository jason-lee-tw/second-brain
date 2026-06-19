# Task 2: validate-urls-with-anyhttpurl

## Attempt 1 — 2026-06-19

### Plan
1. Write failing test: `IngestUrlRequest(urls=["not-a-url"])` raises `ValidationError`
2. Confirm test fails (bare `str` accepts anything)
3. Change schema: `urls: list[AnyHttpUrl]`
4. Update router: wrap `str(url)` around `AnyHttpUrl` objects
5. Fix any tests that break
6. Run `just lint && just test-unit`

### Result: SUCCESS (attempt 1)

- Wrote failing test `test_ingest_url_request_rejects_non_url_string` — confirmed FAILED with `list[str]`
- Changed `schemas.py`: `urls: list[str]` → `urls: list[AnyHttpUrl]` (import from pydantic)
- Changed `ingest.py`: `crawl_and_save(url)` → `crawl_and_save(str(url))`, same for `_url_to_slug` and `source_urls` assignment
- Updated `test_ingest_url_request_valid`: `assert req.urls[0] == "https://example.com"` → `assert "example.com" in str(req.urls[0])` (AnyHttpUrl objects are not bare strings)
- `just lint` — All checks passed
- `just test-unit` — 74 passed
- Committed: `b452b2d fix(schemas): validate IngestUrlRequest.urls with AnyHttpUrl`
