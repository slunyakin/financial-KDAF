# ADR-002: Neo4j Enterprise Edition

**Status:** Accepted
**Date:** 2026-06-02

## Context

The system requires a Neo4j connection pool sized to 200+ connections to serve concurrent users. Neo4j Community Edition caps concurrent connections well below this threshold.

The KG is the single source of truth for table metadata, column relationships, business rules, and embeddings. All SQL/Cypher generation is grounded in context fetched from Neo4j first, meaning KG availability is on the critical path for every query.

## Decision

Use **Neo4j Enterprise Edition** for all environments.

Docker Compose dev configuration:
- Image: `neo4j:enterprise`
- `NEO4J_ACCEPT_LICENSE_AGREEMENT=yes` (free for development)
- JVM heap: `NEO4J_server_memory_heap_initial__size=2g`, `NEO4J_server_memory_heap_max__size=4g`
- Connection pool: `AsyncGraphDatabase.driver(max_connection_pool_size=200)`

v1 concurrent user ceiling: ≤50 concurrent users (200-connection pool / avg 3–5 KG queries per request).

## Consequences

- Development requires accepting the Neo4j Enterprise license agreement
- Community Edition is not usable — any dev switching to Community will hit connection limits immediately
- Read replicas for burst handling are a v2 scaling option; not required for v1 ≤50 user ceiling
