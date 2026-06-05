"""Connector singletons — initialized during FastAPI lifespan, shared across requests.

Usage in main.py:
    from finance_analytics.connectors import init_connectors
    init_connectors(neo4j=..., redis=..., data_lake=...)

Usage in agents:
    from finance_analytics.connectors import get_neo4j, get_redis, get_data_lake
"""
from __future__ import annotations

from finance_analytics.connectors.base import DataLakeConnector
from finance_analytics.connectors.neo4j import Neo4jConnector
from finance_analytics.connectors.redis import RedisConnector

_neo4j: Neo4jConnector | None = None
_redis: RedisConnector | None = None
_data_lake: DataLakeConnector | None = None


def init_connectors(
    neo4j: Neo4jConnector,
    redis: RedisConnector,
    data_lake: DataLakeConnector,
) -> None:
    global _neo4j, _redis, _data_lake
    _neo4j = neo4j
    _redis = redis
    _data_lake = data_lake


def get_neo4j() -> Neo4jConnector:
    if _neo4j is None:
        raise RuntimeError("Neo4j connector not initialized — check FastAPI lifespan")
    return _neo4j


def get_redis() -> RedisConnector:
    if _redis is None:
        raise RuntimeError("Redis connector not initialized — check FastAPI lifespan")
    return _redis


def get_data_lake() -> DataLakeConnector:
    if _data_lake is None:
        raise RuntimeError("DataLake connector not initialized — check FastAPI lifespan")
    return _data_lake


async def close_connectors() -> None:
    if _neo4j:
        await _neo4j.close()
    if _redis:
        await _redis.close()
    if _data_lake:
        await _data_lake.close()
