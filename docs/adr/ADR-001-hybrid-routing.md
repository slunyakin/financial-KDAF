# ADR-001: Hybrid Routing — Direct Drivers vs. MCP

**Status:** Accepted
**Date:** 2026-06-02

## Context

The system serves 200+ concurrent users querying a Neo4j knowledge graph and a customer data lake. Two integration mechanisms are available: direct database drivers (Neo4j bolt, asyncpg, Redis) and MCP servers (external integrations).

Each GraphRAG-style request requires 3–5 KG context lookups before SQL generation. At 200 concurrent users, this is 600–1000 Neo4j queries per second during peak load.

## Decision

80% of operations — all performance-critical paths — use **direct database drivers**:
- Neo4j bolt driver with `AsyncGraphDatabase.driver(max_connection_pool_size=200)`
- asyncpg connection pool for Postgres demo connector
- Redis client for cache reads/writes

20% of operations — external integrations only — use **MCP servers**:
- Market data feeds
- Compliance document retrieval
- Third-party metadata sources

MCP is never used on the hot path (KG context fetches, SQL generation, cache checks).

## Consequences

- Direct driver path: ~10–20x faster than MCP; target latency 480ms
- MCP path: 300–500ms overhead per call; acceptable for external integrations only
- End-to-end P95: <2s warm cache; 2–5s cold simple; 5–30s deep thinking
