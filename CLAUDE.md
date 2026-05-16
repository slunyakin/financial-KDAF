# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

**financial-KDAF** is a knowledge-based finance analytics system that lets hundreds of concurrent users (and other agents) query a data lake and a knowledge graph using natural language. The system translates questions into SQL (for the data lake via Redshift/DuckDB/Trino) and Cypher (for a Neo4j knowledge graph), then orchestrates multiple specialized agents to refine, execute, validate, and enrich the results.

## Architecture

### Hybrid routing: direct drivers vs. MCP (ADR-001)

80% of operations use **direct database drivers** (Neo4j bolt, Redshift, Redis) for performance-critical paths. 20% use **MCP servers** for external integrations (market data, compliance, document retrieval). MCP adds 300–500ms overhead per call; direct drivers are 10–20x faster. GraphRAG requires 10–50 rapid queries per user request, so the direct path is non-negotiable for those.

- Direct driver path target latency: ~480ms
- MCP path latency: ~600ms
- End-to-end P95 target: 1–2 seconds

### Knowledge graph: Neo4j (ADR-002)

Neo4j is the single source of truth for table metadata, column relationships, business rules, and embeddings. All SQL/Cypher generation is grounded in context fetched from Neo4j first. Connection pool must support 200+ concurrent connections.

### Multi-agent orchestration (ADR-003)

The **Supervisor** agent coordinates all other agents and decides the routing:

```
Supervisor → Question Refiner → [Text-to-Cypher (Neo4j) + Text-to-SQL (Data Lake)] → Validator → Reflection
```

Each specialized agent (`refiner`, `validator`, `thinking`, `reflection`) has a single responsibility and can be scaled independently.

## Proposed project structure

```
finance_analytics/
├── config.py              # Centralized config & secret management
├── main.py                # FastAPI entrypoint
├── api/                   # Auth, routing, REST endpoints
├── agents/                # supervisor.py, refiner.py, validator.py, thinking.py, reflection.py
├── execution/             # sql.py, cypher.py, reranker.py, enricher.py
├── connectors/            # neo4j.py, redshift.py, redis.py, mcp.py (connection pools)
├── mcp_tools/             # compliance_server.py, metadata_server.py, document_server.py
├── tools/                 # Shared utility helpers
├── data/                  # Schemas, datalake models, business rule definitions
├── tests/
└── scripts/               # K8s manifests, DB migrations, CI/CD
```

## Tech stack

- **Language:** Python
- **Orchestration framework:** Langchain or Strands (decision pending — evaluate trade-offs before committing)
- **Cloud:** AWS Agent Core
- **Knowledge graph:** Neo4j (with vector search for embeddings)
- **Data lake:** S3 (Parquet/Delta), queried via Redshift/DuckDB/Spark/Trino
- **Cache:** Redis (5-minute TTL on query results)

## Key constraints

- **Do not route performance-critical paths through MCP** — Neo4j metadata lookups, SQL generation context, and cache checks must use direct drivers.
- **Connection pooling is critical** — Neo4j requires 200+ connections; Redshift pool must handle 500+ concurrent users.
- The Supervisor must check Redis cache before dispatching to any execution engine.
- Business rule validation against Neo4j must happen before returning results to the user.

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
