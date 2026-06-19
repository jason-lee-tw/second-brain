# Complex Review Summary

**Date:** 2026-06-19

## Round 2 (feat/003-ingestion post-review-fixes)

**Issues found:** 10
**Issues fixed:** 10
**Review rounds:** 2 (plan review + implementation code review per group)

### Groups
- **Group A** (I1+I2+I6+I7+I8): async DB via `asyncio.to_thread`, `_CHUNK_SEMAPHORE`, inline helper, `in_progress: str | None`, remove config dirs
- **Group B** (I3+I4): Tavily empty-content ValueError, URL hash slug uniqueness
- **Group C** (I5): Ollama error-body ValueError guard
- **Group D** (I9+I10): `model_copy` for response merge, always include `source_urls`

**Final state:** 85 unit tests pass, lint clean, 11 ACs verified on running system.

---

## Round 1 (original complex review)

**Issues found:** 26 (3 MUST FIX, 9 SHOULD FIX, 14 NICE TO HAVE)
**Issues fixed:** 22 (all MUST FIX + SHOULD FIX + selected NICE TO HAVE)
**Review rounds:** 1

## Issues addressed

### MUST FIX (all resolved)
- MF-1: source_url never threaded through IngestionState → fixed (source_urls field + graph threading)
- MF-2: Bad URL in /ingest/url caused 500 → fixed (asyncio.gather + return_exceptions=True)
- MF-3: Services bypassed Settings → fixed (embeddings, tavily, ingestion_agent all use settings)

### SHOULD FIX (all resolved)
- SF-1: PENDING_DOCS_DIR defined 3 times → consolidated via settings
- SF-2: httpx.AsyncClient per embed_text call → module-level singleton
- SF-3: AsyncTavilyClient per crawl_url call → module-level singleton
- SF-4: Sequential chunk processing → asyncio.gather for concurrent header+embed
- SF-5: Sequential URL crawling → asyncio.gather
- SF-6: url_to_slug trailing dash → slice[:80].strip("-")
- SF-7: Hardcoded model name → settings.ingestion_model
- SF-8: Dead target param in _merge_into_chunks → removed
- SF-9: No guard on in_progress[0] → ValueError guard added

### NICE TO HAVE (selected)
- NH-1: typing imports → builtins (all files)
- NH-2: PROCESSED_DIR.mkdir() twice → single call at top of _do_ingest
- NH-3: Duplicate initial_state in router → _run_ingestion helper
- NH-5: counter=[0] closure workaround → nonlocal counter
- NH-6: Redundant "failed" in retry return → skipped (would break tests without TDD update)
- NH-4: camelCase schemas → skipped (intentional per spec)
- NH-7: ChunkingConfig dataclass → skipped (YAGNI for now)
- NH-8: build_ingestion_graph inline → skipped (aids testability)
