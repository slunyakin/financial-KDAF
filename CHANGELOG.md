# Changelog

All notable changes to this project will be documented in this file.

## [0.2.1.0] - 2026-06-20

### Added
- `GET /api/v1/enrichment/tasks/{task_id}` — fetch a single `EnrichmentTask` by
  application-assigned `t.id`; requires `knowledge_engineer` role; `task_id` path
  parameter validated server-side against `^[\w-]{1,128}$` via `Path()`.
- `PATCH /api/v1/enrichment/tasks/{task_id}` — update task status (`open` | `resolved`);
  requires `knowledge_engineer` role. Fixes a silent 405 that left tasks permanently
  unresolved after a successful KG write-back (`resolveTask()` in the frontend called
  PATCH but no handler existed).
- Fast-path optimization in `text_to_cypher_node` — skips the Neo4j fetch entirely when
  `refiner_output.domain_terms` is empty, saving ~200ms on simple aggregation queries
  that have no matching `BusinessRule` or `KnownAnomaly` context.

### Fixed
- `_ENRICHMENT_TASK_BY_ID_CYPHER` and `_ENRICHMENT_TASK_PATCH_CYPHER` now both carry
  `LIMIT 1` to guard against duplicate `t.id` nodes.
- `task-detail.spec.ts` invalid-taskId test route handler now calls `route.abort()`;
  previously the no-op handler caused potential Playwright hangs.
- `getTask()` failures now surface a `fetchError` UI state ("Failed to load task: …")
  instead of leaving the user with a broken empty form on any API error.
- AgentState field names in `test_fast_path.py` corrected to match `schemas/agent_state.py`
  (`reflection_output` not `reflection`; removed non-existent `sql_query`, `sql_rows`,
  `solver_code`, `solver_result`, `enrichment_task_id` — TypedDict `total=False` silently
  accepted the wrong keys at runtime, masking the mismatch).

### Tests
- 3 new unit tests for PATCH endpoint: resolve task, reject invalid status (422), return
  404 for unknown task ID.
- 2 new unit tests covering enrichment report endpoint edge cases (coverage audit).
- New `test_chain_executor_helpers.py`: 19 tests for `_extract_sql`, `_extract_code`,
  `_format_kg_items` helper functions.
- New Playwright test: `getTask` API error → `fetchError` state shows error message.
- Totals: 237 Python unit tests, 17 Playwright e2e tests; coverage 68%.

## [0.2.0.0] - 2026-06-07

### Added
- `POST /api/v1/enrichment/report` — any authenticated user can submit a knowledge gap
  report; creates an `EnrichmentTask` node in Neo4j with sha256-based 15-min idempotency
  so client retries within the window produce one record, not duplicates
- `GET /api/v1/enrichment/tasks` — knowledge engineers can list `EnrichmentTask` nodes
  filtered by status (`open` | `resolved` | `all`), newest first, limit 1–200
- `require_role(role)` FastAPI dependency factory in `api/auth.py`; raises HTTP 403
  when the JWT lacks the required role
- `EnrichmentReportRequest`, `EnrichmentReportResponse`, `EnrichmentTaskItem`,
  `EnrichmentTasksResponse` Pydantic schemas in `schemas/enrichment.py`

### Changed
- `EnrichmentTaskItem.status` narrowed to `Literal["open", "resolved"]` (was `str`)
- `EnrichmentTaskItem.created_at` is now optional (`datetime | None`) to handle
  reflection-written nodes that may have a NULL timestamp
- `EnrichmentReportResponse` now includes `api_version: "1"` for consistency with all
  other response envelopes
- `scripts/neo4j_seed.cypher`: added `created_at` index on `EnrichmentTask` to support
  efficient `ORDER BY t.created_at DESC` in the tasks list query

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
