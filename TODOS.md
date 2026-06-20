# TODOS.md
Items deferred from the CEO plan + engineering review. Each item has a priority and a one-line rationale.

---

## P1 — Before first real customer

- [x] **Customer schema ingestion pipeline** — `finance_analytics/tools/ingest_schema.py`; run with `python -m finance_analytics.tools.ingest_schema [--dry-run]`. Writes Table + Column nodes + HAS_COLUMN edges via batched MERGE. Normalises Snowflake uppercase keys. Connector factory extracted to `connectors/factory.py`.
- [x] **Production connector: Redshift** — `connectors/redshift.py` (asyncpg, dynamic schema, SSL, dialect examples).
- [x] **Production connector: Snowflake** — `connectors/snowflake.py` (thread-pool via asyncio.to_thread, DictCursor, dialect examples including DIV0/QUALIFY/VARIANT). Install: `pip install financial-kdaf[snowflake]`.
- [x] **SQL dialect handling depth** — `dialect_examples` dict added to `DataLakeConnector` ABC and all connector implementations; injected into Text-to-SQL system prompt via `chain_executor.py`.
- [x] **Visibility attribute enforcement on Neo4j nodes** — `_visibility_clause(node_var)` in `execution/cypher.py` injects `(n.visibility IS NULL OR any(role IN $visibility_roles WHERE role IN n.visibility))` into all three KG fetch queries. `visibility_roles` passed as Neo4j parameter; never embedded via LLM output.

## P2 — Before public release

- [x] **Streaming responses** — `POST /api/v1/query/stream` returns SSE. `NodeDoneEvent` after each pipeline stage; `ResultEvent` (api_version: "2") with full answer at the end. Uses LangGraph `astream(stream_mode="updates")`. `schemas/stream_events.py`, `agents/supervisor.py::run_query_stream`, `api/routes.py`. v1 callers unaffected.
- [x] **Query history endpoint** — Replay past CFO questions. `Question` nodes written by v1 support this without migration. Scoped to `user_id` at read time.
- [x] **Knowledge engineer enrichment UI** — Chat interface for gap identification and graph mutation. `EnrichmentTask` nodes drive the conversation flow. Write-back proposals require user confirmation before `POST /api/v1/graph/write`.

## P3 — Backlog / v2

- [ ] **BFF route: CRLF SSE parsing** — `frontend/src/app/api/chat/route.ts` splits on `\n\n` but some proxies or Python SSE emitters may use `\r\n\r\n`. Low-risk in Docker Compose (same host), but harden before adding a reverse proxy. Fix: normalize `chunk.replace(/\r\n/g, '\n')` before splitting.

- [x] **taskId path-traversal validation** — `frontend/src/app/enrichment/[taskId]/page.tsx` validates `taskId` against `^[\w-]+$` before any API call; server-side `Path(..., pattern=r"^[\w-]{1,128}$")` on GET and PATCH endpoints adds defence-in-depth.

- [x] **Task list O(N) scan** — `page.tsx` now calls `GET /api/v1/enrichment/tasks/{taskId}` directly; no client-side list scan.

- [ ] **EnrichmentTask re-open after resolution** — `POST /api/v1/enrichment/report` uses `MERGE … ON CREATE SET`; if a knowledge engineer resolves a task and the same user re-submits the identical description within the 15-min idempotency window, the MERGE no-ops and the node stays `resolved` while the API response still claims `status: open`. Fix: add `ON MATCH SET t.status = 'open' WHERE t.status = 'resolved'` to the MERGE Cypher and a regression test for this path. Low-frequency edge (15-min window); deferred to keep issue #2 focused.

- [ ] **Production connector: BigQuery** — `connectors/bigquery.py`. Use `google-cloud-bigquery` with `asyncio.to_thread()` dispatch. BigQuery has no persistent connection pool — create a `bigquery.Client` per process; wrap in the `DataLakeConnector` ABC.
- [ ] **Production connector: DuckDB / S3-Parquet** — `connectors/duckdb.py`. Use `duckdb` in-process engine; reads customer Parquet files from S3 via `httpfs` extension. Pool model: single-writer lock (DuckDB is single-writer); reads can parallelize with separate in-memory DBs per request.
- [ ] **KG-as-queryable-API endpoint** — `GET /api/v1/graph/context?q=...`. Turns the KG into a platform other agents can query. Depends on v1 KG being stable.
- [x] **Fast-path for questions without KG context** — `text_to_cypher_node` short-circuits when `domain_terms` is empty, returning an empty `CypherContextOutput` without hitting Neo4j. Saves ~200ms on simple aggregation queries.
- [ ] **Per-company deployment ops tooling** — Provisioning automation, upgrade coordination, and monitoring across customer deployments. Each company runs its own Neo4j + Postgres + Redis; as customer count grows, manual ops doesn't scale.
- [ ] **Adversarial evaluation suite** — Extend beyond the 5 golden TCs: ambiguous questions, cross-domain questions, questions with no good answer, graceful-failure cases. The confidence threshold of 0.7 should be derived from evaluation data, not assumed.

---

*CEO plan source: `~/.gstack/projects/slunyakin-financial-KDAF/ceo-plans/2026-05-31-financial-kdaf-v1.md`*
*Engineering review source: `/plan-eng-review` on 2026-06-02*
