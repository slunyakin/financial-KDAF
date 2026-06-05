"""Unit tests for the schema ingestion pipeline.

Tests the pure transform functions (build_table_nodes, build_column_nodes,
build_edge_params) and the batch chunking utility. No live database required.
"""
from __future__ import annotations

import pytest

from finance_analytics.tools.ingest_schema import (
    _chunks,
    _normalise,
    build_column_nodes,
    build_edge_params,
    build_table_nodes,
)

# ── Fixtures ───────────────────────────────────────────────────────────────────

_PG_ROWS = [
    {"table_schema": "public", "table_name": "revenue",   "column_name": "segment",  "data_type": "text"},
    {"table_schema": "public", "table_name": "revenue",   "column_name": "amount",   "data_type": "numeric"},
    {"table_schema": "public", "table_name": "contracts", "column_name": "arr",      "data_type": "numeric"},
    {"table_schema": "public", "table_name": "contracts", "column_name": "sku",      "data_type": "text"},
]

# Snowflake returns uppercase keys
_SF_ROWS = [
    {"TABLE_SCHEMA": "PUBLIC", "TABLE_NAME": "REVENUE",   "COLUMN_NAME": "SEGMENT", "DATA_TYPE": "TEXT"},
    {"TABLE_SCHEMA": "PUBLIC", "TABLE_NAME": "REVENUE",   "COLUMN_NAME": "AMOUNT",  "DATA_TYPE": "NUMBER"},
]

_SYSTEM_ROWS = [
    {"table_schema": "information_schema", "table_name": "columns", "column_name": "id", "data_type": "int"},
    {"table_schema": "pg_catalog",         "table_name": "pg_class", "column_name": "id", "data_type": "int"},
    {"TABLE_SCHEMA": "INFORMATION_SCHEMA", "TABLE_NAME": "COLUMNS", "COLUMN_NAME": "ID", "DATA_TYPE": "NUMBER"},
]


# ── _normalise ─────────────────────────────────────────────────────────────────

def test_normalise_lowercases_keys():
    row = {"TABLE_SCHEMA": "PUBLIC", "TABLE_NAME": "REVENUE", "COLUMN_NAME": "AMT"}
    result = _normalise(row)
    assert "table_schema" in result
    assert "table_name" in result
    assert "column_name" in result


def test_normalise_preserves_values():
    row = {"TABLE_SCHEMA": "PUBLIC"}
    assert _normalise(row)["table_schema"] == "PUBLIC"


# ── build_table_nodes ──────────────────────────────────────────────────────────

def test_build_table_nodes_deduplicates():
    nodes = build_table_nodes(_PG_ROWS, source_engine="postgres")
    ids = [n["id"] for n in nodes]
    assert len(ids) == len(set(ids))  # no duplicates
    assert len(nodes) == 2


def test_build_table_nodes_correct_ids():
    nodes = build_table_nodes(_PG_ROWS, source_engine="postgres")
    ids = {n["id"] for n in nodes}
    assert "public.revenue" in ids
    assert "public.contracts" in ids


def test_build_table_nodes_sets_source_engine():
    nodes = build_table_nodes(_PG_ROWS, source_engine="redshift")
    assert all(n["source_engine"] == "redshift" for n in nodes)


def test_build_table_nodes_handles_snowflake_uppercase():
    nodes = build_table_nodes(_SF_ROWS, source_engine="snowflake")
    assert len(nodes) == 1
    assert nodes[0]["id"] == "PUBLIC.REVENUE"


def test_build_table_nodes_excludes_system_schemas():
    nodes = build_table_nodes(_SYSTEM_ROWS, source_engine="postgres")
    assert nodes == []


def test_build_table_nodes_mixed_user_and_system():
    rows = _PG_ROWS + _SYSTEM_ROWS
    nodes = build_table_nodes(rows, source_engine="postgres")
    schemas = {n["schema"] for n in nodes}
    assert "information_schema" not in schemas
    assert "pg_catalog" not in schemas
    assert "public" in schemas


# ── build_column_nodes ─────────────────────────────────────────────────────────

def test_build_column_nodes_count():
    nodes = build_column_nodes(_PG_ROWS, source_engine="postgres")
    assert len(nodes) == 4


def test_build_column_nodes_ids():
    nodes = build_column_nodes(_PG_ROWS, source_engine="postgres")
    ids = {n["id"] for n in nodes}
    assert "public.revenue.segment" in ids
    assert "public.revenue.amount" in ids
    assert "public.contracts.arr" in ids


def test_build_column_nodes_table_id_links_to_table():
    col_nodes = build_column_nodes(_PG_ROWS, source_engine="postgres")
    table_nodes = build_table_nodes(_PG_ROWS, source_engine="postgres")
    table_ids = {n["id"] for n in table_nodes}
    for col in col_nodes:
        assert col["table_id"] in table_ids


def test_build_column_nodes_preserves_data_type():
    nodes = build_column_nodes(_PG_ROWS, source_engine="postgres")
    by_id = {n["id"]: n for n in nodes}
    assert by_id["public.revenue.amount"]["data_type"] == "numeric"


def test_build_column_nodes_handles_snowflake_uppercase():
    nodes = build_column_nodes(_SF_ROWS, source_engine="snowflake")
    assert len(nodes) == 2
    ids = {n["id"] for n in nodes}
    assert "PUBLIC.REVENUE.SEGMENT" in ids


def test_build_column_nodes_excludes_system_schemas():
    nodes = build_column_nodes(_SYSTEM_ROWS, source_engine="postgres")
    assert nodes == []


# ── build_edge_params ──────────────────────────────────────────────────────────

def test_build_edge_params_count_matches_columns():
    col_nodes = build_column_nodes(_PG_ROWS, source_engine="postgres")
    edges = build_edge_params(col_nodes)
    assert len(edges) == len(col_nodes)


def test_build_edge_params_structure():
    col_nodes = build_column_nodes(_PG_ROWS, source_engine="postgres")
    edges = build_edge_params(col_nodes)
    for edge in edges:
        assert "table_id" in edge
        assert "column_id" in edge


def test_build_edge_params_table_id_matches_column_table_id():
    col_nodes = build_column_nodes(_PG_ROWS, source_engine="postgres")
    edges = build_edge_params(col_nodes)
    for edge, col in zip(edges, col_nodes):
        assert edge["table_id"] == col["table_id"]
        assert edge["column_id"] == col["id"]


# ── _chunks ────────────────────────────────────────────────────────────────────

def test_chunks_splits_evenly():
    result = list(_chunks(list(range(10)), 5))
    assert len(result) == 2
    assert result[0] == [0, 1, 2, 3, 4]
    assert result[1] == [5, 6, 7, 8, 9]


def test_chunks_handles_remainder():
    result = list(_chunks(list(range(7)), 3))
    assert len(result) == 3
    assert result[-1] == [6]


def test_chunks_smaller_than_batch():
    result = list(_chunks([1, 2], 500))
    assert len(result) == 1
    assert result[0] == [1, 2]


def test_chunks_empty():
    result = list(_chunks([], 10))
    assert result == []
