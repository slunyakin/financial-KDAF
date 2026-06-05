"""AWS Redshift connector — asyncpg-backed DataLakeConnector for customer Redshift clusters.

Redshift speaks the PostgreSQL wire protocol (port 5439) so asyncpg works directly.
SSL is required for all production connections — include `sslmode=require` in the DSN.

Pool sizing guidance:
  Redshift clusters default to 500 WLM connection slots. Start with max_size=200
  and tune down based on your WLM queue configuration. connection_timeout=5.0
  fails fast under saturation rather than queuing indefinitely.

DSN format:
  postgresql://user:password@cluster.region.redshift.amazonaws.com:5439/dbname?sslmode=require
"""
from __future__ import annotations

import time
from typing import Optional

import asyncpg

from finance_analytics.connectors.base import DataLakeConnector
from finance_analytics.schemas.agent_outputs import SQLQueryOutput

# System schemas to exclude from schema_description() output.
_SYSTEM_SCHEMAS = frozenset({
    "information_schema",
    "pg_catalog",
    "pg_internal",
    "pg_toast",
    "catalog_history",
    "pg_automv",
})

_SCHEMA_QUERY = """
SELECT
    table_schema,
    table_name,
    column_name,
    data_type
FROM information_schema.columns
WHERE table_schema NOT IN (
    'information_schema', 'pg_catalog', 'pg_internal',
    'pg_toast', 'catalog_history', 'pg_automv'
)
ORDER BY table_schema, table_name, ordinal_position
"""


class RedshiftConnector(DataLakeConnector):
    """Production Redshift connector backed by an asyncpg connection pool."""

    dialect = "redshift"

    dialect_examples: dict[str, str] = {
        "date_trunc_month": "DATE_TRUNC('month', event_date)",
        "date_trunc_quarter": "DATE_TRUNC('quarter', fiscal_date)",
        "date_diff_days": "DATEDIFF('day', start_date, end_date)  -- not subtraction",
        "date_add_days": "DATEADD('day', 30, order_date)  -- not INTERVAL syntax",
        "current_timestamp": "GETDATE()  -- not NOW()",
        "quarter_number": "DATE_PART('qtr', fiscal_date)::INTEGER",
        "year_from_date": "DATE_PART('year', fiscal_date)::INTEGER",
        "string_agg": "LISTAGG(col, ',') WITHIN GROUP (ORDER BY col)  -- not STRING_AGG",
        "approx_distinct_count": "APPROXIMATE COUNT(DISTINCT user_id)  -- HyperLogLog; faster on large tables",
        "null_coalesce": "NVL(col, 0)  -- or COALESCE(col, 0); both work",
        "window_lag": "LAG(revenue, 1) OVER (PARTITION BY segment ORDER BY quarter)",
        "window_row_number": "ROW_NUMBER() OVER (PARTITION BY segment ORDER BY arr DESC)",
        "pct_of_total": "1.0 * revenue / NULLIF(SUM(revenue) OVER (), 0) * 100",
        "safe_divide": "1.0 * numerator / NULLIF(denominator, 0)",
        "quarter_over_quarter_pct": "(curr - prev) / NULLIF(prev, 0.0) * 100.0",
    }

    def __init__(
        self,
        dsn: str,
        max_pool_size: int = 200,
        connection_timeout: float = 5.0,
    ) -> None:
        self._dsn = dsn
        self._max_pool_size = max_pool_size
        self._connection_timeout = connection_timeout
        self._pool: Optional[asyncpg.Pool] = None

    async def init_pool(self) -> None:
        self._pool = await asyncpg.create_pool(
            self._dsn,
            min_size=5,
            max_size=self._max_pool_size,
            timeout=self._connection_timeout,
            statement_cache_size=0,  # Redshift does not support server-side prepared statements
        )

    async def execute(self, query: str, params: dict | None = None) -> SQLQueryOutput:
        if self._pool is None:
            raise RuntimeError("RedshiftConnector pool not initialized — call init_pool()")
        start_ms = int(time.monotonic() * 1000)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query)
        execution_ms = int(time.monotonic() * 1000) - start_ms
        row_dicts = [dict(row) for row in rows]
        return SQLQueryOutput(
            sql=query,
            rows=row_dicts,
            row_count=len(row_dicts),
            execution_ms=execution_ms,
        )

    async def schema_description(self) -> str:
        """Query information_schema.columns and return a markdown schema description."""
        if self._pool is None:
            raise RuntimeError("RedshiftConnector pool not initialized — call init_pool()")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(_SCHEMA_QUERY)
        return _format_schema(rows)

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None


def _format_schema(rows: list) -> str:
    """Format information_schema rows as a markdown schema description."""
    tables: dict[tuple[str, str], list] = {}
    for row in rows:
        key = (row["table_schema"], row["table_name"])
        tables.setdefault(key, []).append(row)

    if not tables:
        return "No user tables found in this Redshift cluster."

    lines = ["## Available tables (Redshift)\n"]
    for (schema, table), cols in sorted(tables.items()):
        lines.append(f"### {schema}.{table}")
        lines.append("| column | type |")
        lines.append("|--------|------|")
        for col in cols:
            lines.append(f"| {col['column_name']} | {col['data_type']} |")
        lines.append("")

    return "\n".join(lines)
