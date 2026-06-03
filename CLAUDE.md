# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

**financial-KDAF** is a knowledge-based finance analytics system that lets hundreds of concurrent users (and other agents) query a customer's data lake or data warehouse alongside a knowledge graph using natural language. The system translates questions into SQL (executed against the customer's own Snowflake, BigQuery, Redshift, S3/Parquet, Databricks, or Postgres instance via a connector-agnostic interface) and Cypher (for a Neo4j knowledge graph), then orchestrates multiple specialized agents to refine, execute, validate, and enrich the results.

## Architecture

### Hybrid routing: direct drivers vs. MCP (ADR-001)

80% of operations use **direct database drivers** (Neo4j bolt, Redshift, Redis) for performance-critical paths. 20% use **MCP servers** for external integrations (market data, compliance, document retrieval). MCP adds 300–500ms overhead per call; direct drivers are 10–20x faster. GraphRAG requires 10–50 rapid queries per user request, so the direct path is non-negotiable for those.

- Direct driver path target latency: ~480ms
- MCP path latency: ~600ms
- End-to-end P95 (warm cache): <2s | Cold-cache simple: 2–5s | Deep thinking: 5–30s (all acceptable — precision over speed)

### Knowledge graph: Neo4j (ADR-002)

Neo4j is the single source of truth for table metadata, column relationships, business rules, and embeddings. All SQL/Cypher generation is grounded in context fetched from Neo4j first. Connection pool must support 200+ concurrent connections.

### Multi-agent orchestration (ADR-003)

The **Supervisor** agent coordinates all other agents and decides the routing:

```
Supervisor → check Redis cache → hit: return cached answer
           → Refiner (sets requires_solver, domain_terms, max_retries)
           → Text-to-Cypher (fetch BusinessRules/KnownAnomalies from Neo4j → AgentState.cypher_context)
           → Text-to-SQL (reads cypher_context from AgentState; injects KG context into SQL prompt)
           → PythonExecutor (subprocess sandbox; only if requires_solver=True)
           → Validator → Reflection → Cache Write → Response
           (on Validator failure + retry_count < max_retries: back to Refiner with context_notes)
           (on retry exhaustion: Reflection(confidence_score=0.0) + EnrichmentTask write)
```

Routing: cache-first, always-exploratory. Supervisor checks Redis first; cache hit returns immediately. Cache miss runs the full sequential chain. No LLM classifier. Chain is **sequential** (not parallel) — Text-to-Cypher runs first so its KG context is available to Text-to-SQL.

Agents: `supervisor.py`, `refiner.py`, `chain_executor.py`, `validator.py`, `reflection.py`. The `thinking.py` module is the Supervisor's deep-mode event emitter — it is merged into `supervisor.py`, not a standalone chain node.

## Proposed project structure

```
finance_analytics/
├── config.py              # Centralized config & secret management (DATA_LAKE_ENGINE env var selects connector)
├── main.py                # FastAPI entrypoint
├── api/                   # Auth (JWT), routing, REST endpoints
│                          # FastAPI Depends: get_current_user_roles() → injects user_id + user_roles into chain
├── agents/                # supervisor.py, refiner.py, chain_executor.py, validator.py, reflection.py
│                          # NOTE: parallel_executor.py renamed → chain_executor.py (chain is sequential)
├── execution/             # sql.py, cypher.py, python_executor.py
│                          # cypher.py: includes Cypher write-guard (blocks MERGE/CREATE/SET/DELETE/DROP)
│                          # sql.py: includes SELECT-only guard (blocks non-SELECT statements)
│                          # python_executor.py: subprocess sandbox; import allowlist (numpy/scipy/pandas only)
│                          #   cypher_context + sql_rows injected as named exec variables (data provenance contract)
├── connectors/            # base.py (DataLakeConnector ABC), neo4j.py, postgres.py (demo/dev), redis.py
│                          # future: snowflake.py, bigquery.py, redshift.py, duckdb.py (S3/Parquet)
├── schemas/               # agent_outputs.py, agent_state.py (AgentState TypedDict), query_response.py
│                          # agent_state.py: must be defined BEFORE any agent code
│                          # query_response.py: QueryResponse Pydantic model (summary, citations, confidence_score)
├── tools/                 # cache_key.py (build_cache_key), kg_cache.py (KG context Redis cache)
├── data/
│   └── eval/              # golden_dataset.yaml (5 golden TCs — commit FIRST, before any agent code)
├── docs/
│   └── adr/               # ADR-001 through ADR-005 (see list below)
├── tests/
│   ├── unit/              # routing, guards, retry logic (no LLM; fast)
│   └── integration/       # TC1-TC5 golden tests + security paths (live Docker Compose stack)
└── scripts/               # smoke_test.sh, postgres_seed.sql, neo4j_seed.cypher, CI/CD
```

**ADRs (in `docs/adr/`):**
- ADR-001: Hybrid routing — direct drivers (Neo4j bolt, Postgres asyncpg, Redis) for hot path; MCP for external integrations only
- ADR-002: Neo4j Enterprise — connection pool 200+; Community Edition insufficient for concurrent users
- ADR-003: LangGraph StateGraph — replaces Strands; Docker Compose compatible; sequential chain with conditional retry edge
- ADR-004: Python subprocess sandbox — process isolation over RestrictedPython; import allowlist (numpy/scipy/pandas); CPU/memory limits
- ADR-005: Sequential Cypher→SQL — Text-to-Cypher runs first; KG context injected into Text-to-SQL prompt via AgentState; correctness over latency

## Tech stack

- **Language:** Python
- **Orchestration framework:** LangChain + LangGraph (decided — replaces Strands; runs locally in Docker Compose, open source, maps directly to the Supervisor→Agent StateGraph pattern)
- **Cloud:** AWS Agent Core
- **Knowledge graph:** Neo4j (with vector search for embeddings)
- **Data lake:** `DataLakeConnector` abstract interface in `connectors/base.py`; `execution/sql.py` is connector-agnostic. Customer data sources: Snowflake, BigQuery, Redshift, S3/Parquet (DuckDB/Athena), Databricks. **Demo/dev fixture:** Postgres (asyncpg, Docker Compose) — used to run the golden evaluation dataset end-to-end without a real customer data source. `DATA_LAKE_ENGINE` env var selects the active connector.
- **Execution tools:** Python REPL / code executor required in the agent chain — all 5 golden evaluation cases require mathematical solvers (LP optimizer, DCF, elasticity solver, sequencing algorithm, delta engine) beyond what SQL can express
- **Cache:** Redis (5-minute TTL on query results and KG context fetches)

## Key constraints

- **Do not route performance-critical paths through MCP** — Neo4j metadata lookups, SQL generation context, and cache checks must use direct drivers.
- **Connection pooling is critical** — Neo4j Enterprise requires 200+ connections (pool=200); set `connection_timeout` and `max_transaction_retry_time` on the bolt driver to fail fast under load. Demo Postgres asyncpg pool max_size=50 (dev ceiling: ~20 concurrent users). Each production connector implementation must define its own pool sizing appropriate to the target engine.
- **SQL dialect is connector-owned** — each `DataLakeConnector` implementation declares its SQL dialect string; `execution/sql.py` injects it into the Text-to-SQL agent's system prompt. Never hardcode Postgres SQL syntax in the agent chain.
- **KG context caching** — `execution/cypher.py` caches Neo4j context fetch results in Redis: key = `kg:{sha256(domain_terms + "|" + "|".join(sorted(user_roles)))}`, TTL=5min. Invalidated on any write to `BusinessRule`, `KnownAnomaly`, `Covenant`, `LaborContract`, `LaborRate`, or `CostOfCapital` nodes.
- **PythonExecutor data provenance** — `cypher_context` and `sql_rows` must be injected as named Python variables in the subprocess exec context. Generated solver code MUST reference these variables. Validator checks variable usage before accepting the result.
- **AgentState schema first** — `finance_analytics/schemas/agent_state.py` must be written before any agent code. All agents read/write named fields from this TypedDict; mismatched field names cause silent KeyErrors.
- **v1 KG access control** — v1: all authenticated company users can read all KG nodes. Visibility attribute enforcement (for sensitive node types) is deferred to TODOS.md. Data warehouse access is managed by the customer's own connector permissions.
- **Intra-company visibility control** — sensitive Neo4j nodes carry `visibility: List[str]` property; FastAPI middleware injects user roles into LangGraph state; all Cypher queries filter on visibility. Each company gets its own deployment (no cross-company data sharing).
- **Execution order in agent chain** — Text-to-Cypher and Text-to-SQL run in parallel (Phase 1); PythonExecutor runs sequentially after both complete and only if `RefinerOutput.requires_solver = True` (Phase 2).
- The Supervisor must check Redis cache before dispatching to any execution engine.
- Business rule validation against Neo4j must happen before returning results to the user.
- **The Python executor tool runs sandboxed** — generated solver code must never have filesystem, network, or shell access; use RestrictedPython or a subprocess sandbox.
- **Evaluation harness is the source of truth** — all agent chain changes must be validated against the 5 golden test cases in `data/eval/golden_dataset.yaml` before merge.

## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues for `slunyakin/financial-KDAF`. See `docs/agents/issue-tracker.md`.

### Triage labels

Using the five canonical label strings (needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout — one `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. When in doubt, invoke the skill.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Strategy/scope → invoke /plan-ceo-review
- Architecture → invoke /plan-eng-review
- Design system/plan review → invoke /design-consultation or /plan-design-review
- Full review pipeline → invoke /autoplan
- Bugs/errors → invoke /investigate
- QA/testing site behavior → invoke /qa or /qa-only
- Code review/diff check → invoke /review
- Visual polish → invoke /design-review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
- Save progress → invoke /context-save
- Resume context → invoke /context-restore
