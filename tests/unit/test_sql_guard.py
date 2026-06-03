"""Unit tests for the SQL SELECT-only guard.

No external dependencies — pure function tests.
"""
import pytest

from finance_analytics.execution.sql import assert_select_only


# ── Blocked cases ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("sql", [
    "INSERT INTO revenue (segment, amount) VALUES ('APAC', 1000)",
    "UPDATE revenue SET amount = 0 WHERE segment = 'APAC'",
    "DELETE FROM revenue WHERE quarter = 'Q4'",
    "DROP TABLE revenue",
    "CREATE TABLE temp_revenue AS SELECT * FROM revenue",
    "ALTER TABLE revenue ADD COLUMN notes TEXT",
    "TRUNCATE revenue",
    "EXEC sp_executesql @stmt",
    "EXECUTE immediate 'DROP TABLE x'",
    "CALL update_procedure()",
    "GRANT SELECT ON revenue TO analyst",
    "REVOKE SELECT ON revenue FROM analyst",
    # Multi-statement injection
    "SELECT * FROM revenue; DROP TABLE revenue",
    "SELECT 1; INSERT INTO revenue VALUES (1)",
    # Case insensitive
    "insert into revenue values (1, 2)",
    "delete from revenue",
])
def test_mutation_keywords_are_blocked(sql: str) -> None:
    with pytest.raises(ValueError, match="mutation keyword"):
        assert_select_only(sql)


# ── Allowed cases ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("sql", [
    "SELECT segment, SUM(amount) FROM revenue GROUP BY segment",
    "SELECT * FROM revenue WHERE quarter = 'Q4' AND year = 2025",
    "SELECT r.segment, e.coefficient FROM revenue r JOIN elasticity e ON r.segment_id = e.segment_id",
    "WITH base AS (SELECT * FROM revenue) SELECT * FROM base",
    "SELECT COUNT(*) FROM contracts WHERE status = 'active'",
])
def test_select_queries_pass(sql: str) -> None:
    assert_select_only(sql)  # must not raise
