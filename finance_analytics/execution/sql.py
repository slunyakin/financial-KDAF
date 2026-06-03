"""Connector-agnostic SQL execution with SELECT-only guard.

execution/sql.py never speaks to a database engine directly — it always goes
through the DataLakeConnector interface. SQL dialect is a property of the
connector and is injected into the Text-to-SQL agent's system prompt upstream
of this module (by the agent, not here).

Security (T6):
  assert_select_only() blocks INSERT/UPDATE/DELETE/DROP and other mutation
  keywords before the query reaches the connector. LLM-generated SQL must pass
  this guard — the guard is evaluated at execution time, not generation time.
"""
from __future__ import annotations

import re

from finance_analytics.connectors.base import DataLakeConnector
from finance_analytics.schemas.agent_outputs import SQLQueryOutput

# SQL statement-level mutation keywords that are never permitted on the query path
_MUTATION_PATTERN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|CREATE|ALTER|TRUNCATE|EXECUTE|EXEC|CALL|GRANT|REVOKE)\b",
    re.IGNORECASE,
)


def assert_select_only(sql: str) -> None:
    """Raise ValueError if sql contains non-SELECT mutation keywords.

    Checks the full statement, not just the leading keyword, to catch
    multi-statement injections like 'SELECT 1; DROP TABLE revenue'.
    """
    match = _MUTATION_PATTERN.search(sql)
    if match:
        raise ValueError(
            f"SQL mutation keyword '{match.group().upper()}' is not permitted "
            "on the query path. Only SELECT statements are allowed."
        )


async def execute_sql(
    sql: str,
    connector: DataLakeConnector,
    params: dict | None = None,
) -> SQLQueryOutput:
    """Execute a SELECT query through the active DataLakeConnector.

    The connector determines the execution engine (Postgres demo, Snowflake,
    BigQuery, etc.) and the SQL dialect. This function is connector-agnostic.
    """
    assert_select_only(sql)
    return await connector.execute(sql, params or {})
