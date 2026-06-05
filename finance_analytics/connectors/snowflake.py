"""Snowflake connector — thread-pool-backed DataLakeConnector for customer Snowflake accounts.

Snowflake's official Python connector is synchronous. All blocking operations are
dispatched to a thread pool via asyncio.to_thread() so the async event loop is
never blocked.

Pool design:
  A queue.Queue of pre-created snowflake.connector.SnowflakeConnection objects
  acts as the connection pool. Pool size should be ≤ the Snowflake warehouse's
  MAX_CONCURRENCY_LEVEL (default 8 per warehouse cluster, auto-scales with
  multi-cluster). Default pool_size=10 works for a single-cluster warehouse.

Authentication:
  Supports username/password via config. For production, prefer key-pair auth
  (SNOWFLAKE_PRIVATE_KEY_PATH) or OAuth — both can be passed via SNOWFLAKE_PASSWORD
  overrides at the connector level. See Snowflake docs for key-pair setup.

Required settings (set via environment / .env):
  SNOWFLAKE_ACCOUNT    e.g. abc12345.us-east-1
  SNOWFLAKE_USER
  SNOWFLAKE_PASSWORD
  SNOWFLAKE_DATABASE
  SNOWFLAKE_SCHEMA     default schema within the database
  SNOWFLAKE_WAREHOUSE
  SNOWFLAKE_ROLE       optional; uses the user's default role if unset
"""
from __future__ import annotations

import asyncio
import queue
import time
from typing import Optional

import snowflake.connector
from snowflake.connector import DictCursor

from finance_analytics.connectors.base import DataLakeConnector
from finance_analytics.schemas.agent_outputs import SQLQueryOutput

_SCHEMA_QUERY = """
SELECT
    table_schema,
    table_name,
    column_name,
    data_type
FROM information_schema.columns
WHERE table_schema != 'INFORMATION_SCHEMA'
ORDER BY table_schema, table_name, ordinal_position
"""


class SnowflakeConnector(DataLakeConnector):
    """Production Snowflake connector backed by a thread-pool of sync connections."""

    dialect = "snowflake"

    dialect_examples: dict[str, str] = {
        "date_trunc_month": "DATE_TRUNC('month', event_date)",
        "date_trunc_quarter": "DATE_TRUNC('quarter', fiscal_date)",
        "date_diff_days": "DATEDIFF('day', start_date, end_date)",
        "date_add_days": "DATEADD('day', 30, order_date)",
        "current_timestamp": "CURRENT_TIMESTAMP()  -- or SYSDATE()",
        "quarter_number": "QUARTER(fiscal_date)  -- returns 1-4",
        "year_from_date": "YEAR(fiscal_date)",
        "string_agg": "LISTAGG(col, ',') WITHIN GROUP (ORDER BY col)",
        "approx_distinct_count": "APPROX_COUNT_DISTINCT(user_id)  -- HyperLogLog; faster than COUNT(DISTINCT)",
        "null_coalesce": "COALESCE(col, 0)  -- or NVL(col, 0)",
        "window_lag": "LAG(revenue, 1) OVER (PARTITION BY segment ORDER BY quarter)",
        "window_row_number": "ROW_NUMBER() OVER (PARTITION BY segment ORDER BY arr DESC)",
        "qualify_top_n": "SELECT ... FROM t QUALIFY ROW_NUMBER() OVER (...) = 1  -- filter on window result",
        "pct_of_total": "1.0 * revenue / NULLIF(SUM(revenue) OVER (), 0) * 100",
        "safe_divide": "DIV0(numerator, denominator)  -- returns 0 (not NULL) on division by zero",
        "quarter_over_quarter_pct": "(curr - prev) / NULLIF(prev, 0.0) * 100.0",
        "semi_structured_field": "col:field::VARCHAR  -- dot-notation extraction from VARIANT column",
        "array_agg": "ARRAY_AGG(col) WITHIN GROUP (ORDER BY col)  -- produces ARRAY type",
    }

    def __init__(
        self,
        account: str,
        user: str,
        password: str,
        database: str,
        schema: str,
        warehouse: str,
        role: str = "",
        pool_size: int = 10,
    ) -> None:
        self._account = account
        self._user = user
        self._password = password
        self._database = database
        self._schema = schema
        self._warehouse = warehouse
        self._role = role
        self._pool_size = pool_size
        self._pool: Optional[queue.Queue] = None

    async def init_pool(self) -> None:
        self._pool = await asyncio.to_thread(self._create_pool)

    def _create_pool(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=self._pool_size)
        connect_kwargs: dict = dict(
            account=self._account,
            user=self._user,
            password=self._password,
            database=self._database,
            schema=self._schema,
            warehouse=self._warehouse,
            session_parameters={"QUERY_TAG": "financial-kdaf"},
        )
        if self._role:
            connect_kwargs["role"] = self._role
        for _ in range(self._pool_size):
            q.put(snowflake.connector.connect(**connect_kwargs))
        return q

    def _acquire(self) -> snowflake.connector.SnowflakeConnection:
        if self._pool is None:
            raise RuntimeError("SnowflakeConnector pool not initialized — call init_pool()")
        return self._pool.get(timeout=10)

    def _release(self, conn: snowflake.connector.SnowflakeConnection) -> None:
        if self._pool is not None:
            self._pool.put(conn)

    def _execute_sync(self, query: str) -> SQLQueryOutput:
        conn = self._acquire()
        try:
            start_ms = int(time.monotonic() * 1000)
            with conn.cursor(DictCursor) as cur:
                cur.execute(query)
                rows = list(cur.fetchall())
            execution_ms = int(time.monotonic() * 1000) - start_ms
            return SQLQueryOutput(
                sql=query,
                rows=rows,
                row_count=len(rows),
                execution_ms=execution_ms,
            )
        finally:
            self._release(conn)

    def _schema_sync(self) -> str:
        conn = self._acquire()
        try:
            with conn.cursor(DictCursor) as cur:
                cur.execute(_SCHEMA_QUERY)
                rows = list(cur.fetchall())
            return _format_schema(rows)
        finally:
            self._release(conn)

    def _close_sync(self) -> None:
        if self._pool is None:
            return
        while True:
            try:
                conn = self._pool.get_nowait()
                conn.close()
            except queue.Empty:
                break
        self._pool = None

    async def execute(self, query: str, params: dict | None = None) -> SQLQueryOutput:
        if self._pool is None:
            raise RuntimeError("SnowflakeConnector pool not initialized — call init_pool()")
        return await asyncio.to_thread(self._execute_sync, query)

    async def schema_description(self) -> str:
        if self._pool is None:
            raise RuntimeError("SnowflakeConnector pool not initialized — call init_pool()")
        return await asyncio.to_thread(self._schema_sync)

    async def close(self) -> None:
        await asyncio.to_thread(self._close_sync)


def _format_schema(rows: list) -> str:
    """Format information_schema rows as a markdown schema description."""
    tables: dict[tuple[str, str], list] = {}
    for row in rows:
        key = (row["TABLE_SCHEMA"], row["TABLE_NAME"])
        tables.setdefault(key, []).append(row)

    if not tables:
        return "No user tables found in this Snowflake database."

    lines = ["## Available tables (Snowflake)\n"]
    for (schema, table), cols in sorted(tables.items()):
        lines.append(f"### {schema}.{table}")
        lines.append("| column | type |")
        lines.append("|--------|------|")
        for col in cols:
            lines.append(f"| {col['COLUMN_NAME']} | {col['DATA_TYPE']} |")
        lines.append("")

    return "\n".join(lines)
