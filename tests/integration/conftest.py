"""Integration test fixtures — requires live Docker Compose stack.

Run with:
    docker compose up -d
    pytest tests/integration/ -v

All fixtures are session-scoped so connectors are initialized once per run.
"""
from __future__ import annotations

import os

import asyncpg
import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from neo4j import AsyncGraphDatabase

POSTGRES_DSN = os.getenv(
    "POSTGRES_DSN",
    "postgresql://postgres:postgres@localhost:5432/financial_kdaf",
)
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "neo4jpassword")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")


@pytest_asyncio.fixture(scope="session")
async def pg_pool():
    pool = await asyncpg.create_pool(POSTGRES_DSN, min_size=2, max_size=5, statement_cache_size=0)
    yield pool
    await pool.close()


@pytest_asyncio.fixture(scope="session")
async def neo4j_driver():
    driver = AsyncGraphDatabase.driver(
        NEO4J_URI,
        auth=(NEO4J_USER, NEO4J_PASSWORD),
        max_connection_pool_size=10,
    )
    yield driver
    await driver.close()


@pytest_asyncio.fixture(scope="session")
async def redis_client():
    client = aioredis.from_url(REDIS_URL, decode_responses=True)
    yield client
    await client.aclose()


@pytest_asyncio.fixture(scope="function")
async def fresh_redis(redis_client):
    """Flush Redis before each test to avoid cache pollution."""
    await redis_client.flushdb()
    yield redis_client
    await redis_client.flushdb()
