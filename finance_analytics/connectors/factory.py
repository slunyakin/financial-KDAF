"""DataLakeConnector factory — shared by the FastAPI app and the ingestion CLI.

Reads DATA_LAKE_ENGINE from Settings and instantiates the correct connector.
"""
from __future__ import annotations

from finance_analytics.connectors.base import DataLakeConnector


def build_data_lake_connector(settings) -> DataLakeConnector:
    """Instantiate the active DataLakeConnector from Settings."""
    engine = settings.DATA_LAKE_ENGINE.lower()

    if engine == "postgres":
        from finance_analytics.connectors.postgres import PostgresConnector
        return PostgresConnector(
            dsn=settings.POSTGRES_DSN,
            max_pool_size=settings.POSTGRES_MAX_POOL_SIZE,
        )

    if engine == "redshift":
        if not settings.REDSHIFT_DSN:
            raise ValueError(
                "DATA_LAKE_ENGINE=redshift requires REDSHIFT_DSN to be set. "
                "Format: postgresql://user:pass@cluster.region.redshift.amazonaws.com:5439/db?sslmode=require"
            )
        from finance_analytics.connectors.redshift import RedshiftConnector
        return RedshiftConnector(
            dsn=settings.REDSHIFT_DSN,
            max_pool_size=settings.REDSHIFT_MAX_POOL_SIZE,
            connection_timeout=settings.REDSHIFT_CONNECTION_TIMEOUT,
        )

    if engine == "snowflake":
        missing = [
            f for f in ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD",
                        "SNOWFLAKE_DATABASE", "SNOWFLAKE_WAREHOUSE")
            if not getattr(settings, f, "")
        ]
        if missing:
            raise ValueError(
                f"DATA_LAKE_ENGINE=snowflake requires these settings: {', '.join(missing)}"
            )
        from finance_analytics.connectors.snowflake import SnowflakeConnector
        return SnowflakeConnector(
            account=settings.SNOWFLAKE_ACCOUNT,
            user=settings.SNOWFLAKE_USER,
            password=settings.SNOWFLAKE_PASSWORD,
            database=settings.SNOWFLAKE_DATABASE,
            schema=settings.SNOWFLAKE_SCHEMA,
            warehouse=settings.SNOWFLAKE_WAREHOUSE,
            role=settings.SNOWFLAKE_ROLE,
            pool_size=settings.SNOWFLAKE_POOL_SIZE,
        )

    raise ValueError(
        f"Unsupported DATA_LAKE_ENGINE='{engine}'. "
        "Available: postgres, redshift, snowflake. "
        "See TODOS.md for remaining connectors (bigquery, duckdb)."
    )
