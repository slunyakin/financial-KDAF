"""Unit tests for DataLakeConnector implementations.

Tests the interface contract and dialect metadata. No live database required —
asyncpg pool is mocked at the acquire() boundary; Snowflake sync methods are
tested directly against a mock connection queue.
"""
from __future__ import annotations

import queue
from unittest.mock import AsyncMock, MagicMock

import pytest

from finance_analytics.connectors.base import DataLakeConnector
from finance_analytics.connectors.postgres import PostgresConnector
from finance_analytics.connectors.redshift import RedshiftConnector
from finance_analytics.connectors.redshift import _format_schema as _redshift_format_schema
from finance_analytics.connectors.snowflake import SnowflakeConnector
from finance_analytics.connectors.snowflake import _format_schema as _snowflake_format_schema
from finance_analytics.schemas.agent_outputs import SQLQueryOutput

# ── Interface contract ─────────────────────────────────────────────────────────

def test_postgres_implements_base():
    assert issubclass(PostgresConnector, DataLakeConnector)


def test_redshift_implements_base():
    assert issubclass(RedshiftConnector, DataLakeConnector)


# ── Dialect metadata ───────────────────────────────────────────────────────────

def test_postgres_dialect():
    assert PostgresConnector.dialect == "postgresql"


def test_redshift_dialect():
    assert RedshiftConnector.dialect == "redshift"


def test_postgres_dialect_examples_non_empty():
    assert len(PostgresConnector.dialect_examples) > 0


def test_redshift_dialect_examples_non_empty():
    assert len(RedshiftConnector.dialect_examples) > 0


def test_redshift_dialect_examples_cover_key_patterns():
    examples = RedshiftConnector.dialect_examples
    assert "date_diff_days" in examples
    assert "string_agg" in examples
    assert "safe_divide" in examples
    assert "window_lag" in examples


def test_postgres_and_redshift_date_diff_differ():
    # Redshift uses DATEDIFF(); Postgres uses subtraction — they must not be identical
    assert RedshiftConnector.dialect_examples["date_diff_days"] != \
           PostgresConnector.dialect_examples["date_diff_days"]


# ── Pool-not-initialized guard ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_redshift_execute_without_pool_raises():
    connector = RedshiftConnector(dsn="postgresql://user:pass@host:5439/db")
    with pytest.raises(RuntimeError, match="not initialized"):
        await connector.execute("SELECT 1")


@pytest.mark.asyncio
async def test_redshift_schema_description_without_pool_raises():
    connector = RedshiftConnector(dsn="postgresql://user:pass@host:5439/db")
    with pytest.raises(RuntimeError, match="not initialized"):
        await connector.schema_description()


# ── execute() with mocked pool ────────────────────────────────────────────────

def _make_mock_record(data: dict):
    """Return a dict-like object that asyncpg's dict(row) pattern converts correctly."""
    return data


@pytest.mark.asyncio
async def test_redshift_execute_returns_sql_output():
    connector = RedshiftConnector(dsn="postgresql://user:pass@host:5439/db")

    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = [{"segment": "APAC", "amount": 1000}]

    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    connector._pool = mock_pool

    result = await connector.execute("SELECT segment, amount FROM revenue")

    assert isinstance(result, SQLQueryOutput)
    assert result.sql == "SELECT segment, amount FROM revenue"
    assert result.row_count == 1
    assert result.rows == [{"segment": "APAC", "amount": 1000}]
    assert result.execution_ms >= 0


@pytest.mark.asyncio
async def test_redshift_execute_empty_result():
    connector = RedshiftConnector(dsn="postgresql://user:pass@host:5439/db")

    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = []

    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    connector._pool = mock_pool

    result = await connector.execute("SELECT segment FROM revenue WHERE 1=0")
    assert result.row_count == 0
    assert result.rows == []


# ── schema_description() ──────────────────────────────────────────────────────

def _make_schema_rows(table_schema: str, table_name: str, cols: list[tuple[str, str]]) -> list:
    return [
        {"table_schema": table_schema, "table_name": table_name,
         "column_name": col, "data_type": dtype}
        for col, dtype in cols
    ]


def test_redshift_format_schema_produces_markdown():
    rows = _make_schema_rows("public", "revenue", [
        ("segment", "character varying"),
        ("amount", "numeric"),
        ("year", "integer"),
    ])
    output = _redshift_format_schema(rows)
    assert "### public.revenue" in output
    assert "| segment | character varying |" in output
    assert "| amount | numeric |" in output


def test_redshift_format_schema_groups_multiple_tables():
    rows = (
        _make_schema_rows("public", "revenue", [("amount", "numeric")])
        + _make_schema_rows("public", "contracts", [("arr", "numeric")])
    )
    output = _redshift_format_schema(rows)
    assert "### public.revenue" in output
    assert "### public.contracts" in output


def test_redshift_format_schema_empty_returns_message():
    output = _redshift_format_schema([])
    assert "No user tables" in output


@pytest.mark.asyncio
async def test_redshift_schema_description_calls_pool():
    connector = RedshiftConnector(dsn="postgresql://user:pass@host:5439/db")

    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = _make_schema_rows(
        "public", "revenue", [("segment", "character varying"), ("amount", "numeric")]
    )

    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    connector._pool = mock_pool

    desc = await connector.schema_description()
    assert "### public.revenue" in desc
    assert "| segment |" in desc


# ── close() ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_redshift_close_calls_pool_close():
    connector = RedshiftConnector(dsn="postgresql://user:pass@host:5439/db")
    mock_pool = AsyncMock()
    connector._pool = mock_pool

    await connector.close()

    mock_pool.close.assert_called_once()
    assert connector._pool is None


@pytest.mark.asyncio
async def test_redshift_close_without_pool_is_noop():
    connector = RedshiftConnector(dsn="postgresql://user:pass@host:5439/db")
    await connector.close()  # must not raise


# ── SnowflakeConnector ─────────────────────────────────────────────────────────

def _make_snowflake_connector() -> SnowflakeConnector:
    return SnowflakeConnector(
        account="abc123.us-east-1",
        user="svc_user",
        password="secret",
        database="PROD_DW",
        schema="PUBLIC",
        warehouse="KDAF_WH",
    )


def _make_snowflake_pool(rows: list) -> queue.Queue:
    """Build a one-connection pool with a mock Snowflake connection."""
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=False)
    mock_cursor.fetchall.return_value = rows

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    q: queue.Queue = queue.Queue(maxsize=1)
    q.put(mock_conn)
    return q


def _make_snowflake_schema_rows(schema: str, table: str, cols: list[tuple[str, str]]) -> list:
    return [
        {"TABLE_SCHEMA": schema, "TABLE_NAME": table, "COLUMN_NAME": col, "DATA_TYPE": dtype}
        for col, dtype in cols
    ]


# Interface contract

def test_snowflake_implements_base():
    assert issubclass(SnowflakeConnector, DataLakeConnector)


def test_snowflake_dialect():
    assert SnowflakeConnector.dialect == "snowflake"


def test_snowflake_dialect_examples_non_empty():
    assert len(SnowflakeConnector.dialect_examples) > 0


def test_snowflake_dialect_examples_cover_key_patterns():
    examples = SnowflakeConnector.dialect_examples
    assert "safe_divide" in examples
    assert "qualify_top_n" in examples
    assert "semi_structured_field" in examples
    assert "approx_distinct_count" in examples


def test_snowflake_safe_divide_uses_div0():
    assert "DIV0" in SnowflakeConnector.dialect_examples["safe_divide"]


def test_snowflake_string_agg_uses_listagg():
    assert "LISTAGG" in SnowflakeConnector.dialect_examples["string_agg"]


# Pool-not-initialized guard

@pytest.mark.asyncio
async def test_snowflake_execute_without_pool_raises():
    connector = _make_snowflake_connector()
    with pytest.raises(RuntimeError, match="not initialized"):
        await connector.execute("SELECT 1")


@pytest.mark.asyncio
async def test_snowflake_schema_description_without_pool_raises():
    connector = _make_snowflake_connector()
    with pytest.raises(RuntimeError, match="not initialized"):
        await connector.schema_description()


# _execute_sync with mocked pool

def test_snowflake_execute_sync_returns_sql_output():
    connector = _make_snowflake_connector()
    connector._pool = _make_snowflake_pool([{"SEGMENT": "APAC", "AMOUNT": 1000}])

    result = connector._execute_sync("SELECT segment, amount FROM revenue")

    assert isinstance(result, SQLQueryOutput)
    assert result.sql == "SELECT segment, amount FROM revenue"
    assert result.row_count == 1
    assert result.rows == [{"SEGMENT": "APAC", "AMOUNT": 1000}]
    assert result.execution_ms >= 0


def test_snowflake_execute_sync_empty_result():
    connector = _make_snowflake_connector()
    connector._pool = _make_snowflake_pool([])

    result = connector._execute_sync("SELECT segment FROM revenue WHERE 1=0")
    assert result.row_count == 0
    assert result.rows == []


def test_snowflake_execute_sync_returns_connection_to_pool():
    connector = _make_snowflake_connector()
    connector._pool = _make_snowflake_pool([{"COL": "val"}])

    assert connector._pool.qsize() == 1
    connector._execute_sync("SELECT 1")
    assert connector._pool.qsize() == 1  # connection returned after use


# _schema_sync with mocked pool

def test_snowflake_schema_sync_produces_markdown():
    connector = _make_snowflake_connector()
    connector._pool = _make_snowflake_pool(
        _make_snowflake_schema_rows("PUBLIC", "REVENUE", [
            ("SEGMENT", "TEXT"),
            ("AMOUNT", "NUMBER"),
        ])
    )
    desc = connector._schema_sync()
    assert "### PUBLIC.REVENUE" in desc
    assert "| SEGMENT | TEXT |" in desc


# _format_schema (Snowflake)

def test_snowflake_format_schema_produces_markdown():
    rows = _make_snowflake_schema_rows("PUBLIC", "CONTRACTS", [
        ("ARR", "NUMBER"), ("RENEWAL_DATE", "DATE")
    ])
    output = _snowflake_format_schema(rows)
    assert "### PUBLIC.CONTRACTS" in output
    assert "| ARR | NUMBER |" in output


def test_snowflake_format_schema_empty_returns_message():
    output = _snowflake_format_schema([])
    assert "No user tables" in output


# close()

def test_snowflake_close_sync_drains_pool_and_closes_connections():
    connector = _make_snowflake_connector()
    mock_conn = MagicMock()
    q: queue.Queue = queue.Queue(maxsize=2)
    q.put(mock_conn)
    q.put(MagicMock())
    connector._pool = q

    connector._close_sync()

    mock_conn.close.assert_called_once()
    assert connector._pool is None


def test_snowflake_close_sync_without_pool_is_noop():
    connector = _make_snowflake_connector()
    connector._close_sync()  # must not raise
