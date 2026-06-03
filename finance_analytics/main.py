"""FastAPI application entrypoint.

Lifespan:
  startup  — initialize connectors (Neo4j, Redis, DataLakeConnector), warm graph
  shutdown — close all connector pools gracefully

The LangGraph StateGraph is compiled lazily on first request via supervisor.get_graph().
Calling get_graph() during startup is optional but warms the compilation cache.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

import finance_analytics.connectors as connectors
from finance_analytics.agents.supervisor import get_graph
from finance_analytics.api.routes import router
from finance_analytics.config import get_settings
from finance_analytics.connectors.neo4j import Neo4jConnector
from finance_analytics.connectors.postgres import PostgresConnector
from finance_analytics.connectors.redis import RedisConnector


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # Initialize connectors
    neo4j = Neo4jConnector(
        uri=settings.NEO4J_URI,
        user=settings.NEO4J_USER,
        password=settings.NEO4J_PASSWORD,
        max_pool_size=settings.NEO4J_MAX_POOL_SIZE,
    )
    redis = RedisConnector(url=settings.REDIS_URL)
    data_lake = _build_data_lake_connector(settings)
    await data_lake.init_pool()

    connectors.init_connectors(neo4j=neo4j, redis=redis, data_lake=data_lake)

    # Warm the LangGraph compilation (avoids first-request latency spike)
    get_graph()

    yield

    await connectors.close_connectors()


def _build_data_lake_connector(settings) -> PostgresConnector:
    """Instantiate the active DataLakeConnector based on DATA_LAKE_ENGINE.

    v1: only "postgres" is implemented. Future engines:
      snowflake → PostgresConnector  (replace with SnowflakeConnector)
      bigquery  → BigQueryConnector
      redshift  → RedshiftConnector
      duckdb    → DuckDBConnector
    """
    engine = settings.DATA_LAKE_ENGINE.lower()
    if engine == "postgres":
        return PostgresConnector(
            dsn=settings.POSTGRES_DSN,
            max_pool_size=settings.POSTGRES_MAX_POOL_SIZE,
        )
    raise ValueError(
        f"Unsupported DATA_LAKE_ENGINE='{engine}'. "
        "Available in v1: postgres. "
        "See TODOS.md for production connector implementations."
    )


app = FastAPI(
    title="financial-KDAF",
    version="1.0.0",
    description="Knowledge-based finance analytics — NL questions answered with citations.",
    lifespan=lifespan,
)

app.include_router(router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
