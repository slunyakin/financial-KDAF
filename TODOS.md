# TODOS.md
Items deferred from the CEO plan + engineering review. Each item has a priority and a one-line rationale.

---

## P1 — Before first real customer

- [ ] **Customer schema ingestion pipeline** — Onboarding script that connects to customer's data source via the `DataLakeConnector` and populates Neo4j `Table`/`Column` nodes from the customer's actual schema. Replaces manual seeding.
- [ ] **Production connector implementations** — `connectors/snowflake.py`, `connectors/bigquery.py`, `connectors/redshift.py`, `connectors/duckdb.py` (S3/Parquet). Each implements `DataLakeConnector` ABC. One file per engine.
- [ ] **SQL dialect handling depth** — A single dialect string injected into the Text-to-SQL prompt is insufficient for Snowflake vs. Postgres differences in window functions, date handling, and string functions. Connectors should also carry a `dialect_examples` dict of common patterns.
- [ ] **Visibility attribute enforcement on Neo4j nodes** — v1 ships with all KG content world-readable (all authenticated company users). When access control on specific node types is needed: implement Cypher post-processing in `execution/cypher.py` to inject the visibility filter clause before execution. Never rely on the LLM including it.

## P2 — Before first public release

- [ ] **Streaming responses** — `StreamingResponse` + `astream_events` from LangGraph. Add before first real user scenario. API clients must not hardcode sync assumptions — version the response envelope (`api_version: "1"`) so streaming can be added as `api_version: "2"` without breaking v1 callers.
- [ ] **Query history endpoint** — Replay past CFO questions. `Question` nodes written by v1 support this without migration. Scoped to `user_id` at read time.
- [ ] **Knowledge engineer enrichment UI** — Chat interface for gap identification and graph mutation. `EnrichmentTask` nodes drive the conversation flow. Write-back proposals require user confirmation before `POST /api/v1/graph/write`.

## P3 — Future / v2

- [ ] **KG-as-queryable-API endpoint** — `GET /api/v1/graph/context?q=...`. Turns the KG into a platform other agents can query. Depends on v1 KG being stable.
- [ ] **Fast-path for questions without KG context** — A simple aggregation question that has no matching BusinessRule or KnownAnomaly should short-circuit the Text-to-Cypher step (or run it with a timeout cap). Reduces cold-cache latency for simple queries by ~200ms.
- [ ] **Per-company deployment ops tooling** — Provisioning automation, upgrade coordination, and monitoring across customer deployments. Each company runs its own Neo4j + Postgres + Redis; as customer count grows, manual ops doesn't scale.
- [ ] **Adversarial evaluation suite** — Extend beyond the 5 golden TCs: ambiguous questions, cross-domain questions, questions with no good answer, graceful-failure cases. The confidence threshold of 0.7 should be derived from evaluation data, not assumed.

---

*CEO plan source: `~/.gstack/projects/slunyakin-financial-KDAF/ceo-plans/2026-05-31-financial-kdaf-v1.md`*
*Engineering review source: `/plan-eng-review` on 2026-06-02*
