"""Unit tests for chain_executor helper functions.

Covers _extract_sql, _extract_code, and _format_kg_items — all pure functions
that need no external dependencies (no LLM, no database, no connectors).
"""
from __future__ import annotations

import pytest

from finance_analytics.agents.chain_executor import (
    _extract_code,
    _extract_sql,
    _format_kg_items,
)


# ── _extract_sql ──────────────────────────────────────────────────────────────

def test_extract_sql_strips_sql_fence():
    raw = "```sql\nSELECT * FROM orders\n```"
    assert _extract_sql(raw) == "SELECT * FROM orders"


def test_extract_sql_strips_generic_fence():
    raw = "```\nSELECT 1\n```"
    assert _extract_sql(raw) == "SELECT 1"


def test_extract_sql_passthrough_bare_sql():
    raw = "SELECT id, amount FROM trades WHERE date > '2026-01-01'"
    assert _extract_sql(raw) == raw


def test_extract_sql_strips_surrounding_whitespace_from_bare():
    raw = "  SELECT 1  "
    assert _extract_sql(raw) == "SELECT 1"


def test_extract_sql_case_insensitive_fence_label():
    raw = "```SQL\nSELECT 2\n```"
    assert _extract_sql(raw) == "SELECT 2"


def test_extract_sql_multiline_inside_fence():
    raw = "```sql\nSELECT a,\n       b\nFROM t\n```"
    assert _extract_sql(raw) == "SELECT a,\n       b\nFROM t"


# ── _extract_code ─────────────────────────────────────────────────────────────

def test_extract_code_strips_python_fence():
    raw = "```python\nresult = 42\n```"
    assert _extract_code(raw) == "result = 42"


def test_extract_code_strips_generic_fence():
    raw = "```\nresult = sum(x for x in sql_rows)\n```"
    assert _extract_code(raw) == "result = sum(x for x in sql_rows)"


def test_extract_code_passthrough_bare_code():
    raw = "result = 1 + 1"
    assert _extract_code(raw) == raw


def test_extract_code_case_insensitive_fence_label():
    raw = "```Python\nresult = 0\n```"
    assert _extract_code(raw) == "result = 0"


def test_extract_code_multiline_inside_fence():
    raw = "```python\nwacc = 0.08\nresult = {'npv': 1 / (1 + wacc)}\n```"
    assert _extract_code(raw) == "wacc = 0.08\nresult = {'npv': 1 / (1 + wacc)}"


# ── _format_kg_items ──────────────────────────────────────────────────────────

def test_format_kg_items_empty_returns_none():
    assert _format_kg_items([]) == "None"


def test_format_kg_items_single_item_with_description():
    items = [{"description": "Revenue must exclude intercompany transfers"}]
    result = _format_kg_items(items)
    assert "Revenue must exclude intercompany transfers" in result


def test_format_kg_items_prefixes_rule_id():
    items = [{"rule_id": "BR-001", "description": "WACC must be >= 8%"}]
    result = _format_kg_items(items)
    assert "[BR-001]" in result
    assert "WACC must be >= 8%" in result


def test_format_kg_items_uses_period_as_rule_id_for_known_anomalies():
    items = [{"period": "Q3-2025", "description": "Revenue spike due to one-time item"}]
    result = _format_kg_items(items)
    assert "[Q3-2025]" in result


def test_format_kg_items_falls_back_to_name_when_no_description():
    items = [{"name": "WACC"}]
    result = _format_kg_items(items)
    assert "WACC" in result


def test_format_kg_items_multiple_items_one_line_each():
    items = [
        {"rule_id": "BR-001", "description": "Rule one"},
        {"rule_id": "BR-002", "description": "Rule two"},
    ]
    lines = _format_kg_items(items).splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("- [BR-001]")
    assert lines[1].startswith("- [BR-002]")


def test_format_kg_items_no_id_omits_brackets():
    items = [{"description": "No ID rule"}]
    result = _format_kg_items(items)
    assert "[" not in result
    assert "No ID rule" in result


def test_format_kg_items_unknown_shape_falls_back_to_str():
    items = [{"unknown_key": "some_value"}]
    result = _format_kg_items(items)
    # Falls back to str(item)
    assert result  # non-empty
    assert result != "None"
