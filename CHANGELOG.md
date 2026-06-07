# Changelog

All notable changes to this project will be documented in this file.

## [0.1.0.0] - 2026-06-06

### Added
- `GET /api/v1/history` — authenticated users can now replay their past questions,
  newest first, with confidence scores and enrichment task links (limit 1–100, default 20)
- `POST /api/v1/query/stream` — agent chain progress streamed as Server-Sent Events
  with per-node summaries and a final `ResultEvent` (api_version: "2")

### Changed
- Query history is persisted automatically after every non-cached request; the
  `Question` node includes a deterministic `id` (sha256 of user + question + TTL window)
  so client retries within the cache window produce one record, not duplicates

### Fixed
- `neo4j.time.DateTime` returned by the driver's `result.data()` is now correctly
  converted to a Python `datetime` before Pydantic validation
- History write failures now log at WARNING with full traceback instead of failing
  silently, giving operators visibility into sustained Neo4j outages

### Infrastructure
- `CREATE INDEX question_user_id` and `CREATE CONSTRAINT question_id` added to
  `scripts/neo4j_seed.cypher` for history query performance and write idempotency
