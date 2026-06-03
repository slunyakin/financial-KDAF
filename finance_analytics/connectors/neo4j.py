"""Neo4j connector — KG context fetches and enrichment writes.

Not a DataLakeConnector: Neo4j serves the knowledge graph layer, not SQL queries.
The bolt driver is used directly by execution/cypher.py.

Per ADR-002: requires Neo4j Enterprise Edition.
Pool sizing: max_connection_pool_size=200 supports ≤50 concurrent users at
3–5 KG queries per request average. Read replicas are a v2 scaling option.
"""
from __future__ import annotations

from neo4j import AsyncDriver, AsyncGraphDatabase


class Neo4jConnector:
    """Manages the Neo4j async driver with a bounded connection pool."""

    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        max_pool_size: int = 200,
    ) -> None:
        self.driver: AsyncDriver = AsyncGraphDatabase.driver(
            uri,
            auth=(user, password),
            max_connection_pool_size=max_pool_size,
            # Fail fast under load rather than queue indefinitely
            connection_timeout=5.0,
            max_transaction_retry_time=3.0,
        )

    async def close(self) -> None:
        await self.driver.close()
