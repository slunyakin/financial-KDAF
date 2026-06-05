"""Customer schema ingestion pipeline.

Discovers table/column metadata from the active DataLakeConnector and writes
Table + Column nodes (with HAS_COLUMN edges) into Neo4j. Safe to re-run — all
writes use MERGE so re-running after a schema change updates existing nodes
and adds new ones without duplicating anything.

Usage:
    python -m finance_analytics.tools.ingest_schema [--dry-run]

Settings are read from .env / environment variables (same as the main app).
Set DATA_LAKE_ENGINE and the corresponding connector settings before running.

Output example:
    [ingest_schema] engine=redshift  database=PROD_DW
    [ingest_schema] discovered 42 tables, 318 columns
    [ingest_schema] writing Table nodes (batch 1/1)...
    [ingest_schema] writing Column nodes (batch 1/4)...
    [ingest_schema] writing HAS_COLUMN edges (batch 1/4)...
    [ingest_schema] done — 42 tables, 318 columns written to Neo4j
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

from neo4j import AsyncGraphDatabase

from finance_analytics.config import get_settings
from finance_analytics.connectors.factory import build_data_lake_connector

# System schemas to exclude from all engines.
_EXCLUDED_SCHEMAS = frozenset({
    "information_schema", "pg_catalog", "pg_internal", "pg_toast",
    "catalog_history", "pg_automv",
    "INFORMATION_SCHEMA",  # Snowflake uppercase variant
})

_DISCOVERY_QUERY = """\
SELECT table_schema, table_name, column_name, data_type
FROM information_schema.columns
WHERE table_schema NOT IN (
    'information_schema', 'pg_catalog', 'pg_internal',
    'pg_toast', 'catalog_history', 'pg_automv', 'INFORMATION_SCHEMA'
)
ORDER BY table_schema, table_name, ordinal_position
"""

_MERGE_TABLES_CYPHER = """\
UNWIND $rows AS t
MERGE (n:Table {id: t.id})
SET n.schema     = t.schema,
    n.name       = t.name,
    n.source_engine = t.source_engine,
    n.ingested_at   = datetime()
"""

_MERGE_COLUMNS_CYPHER = """\
UNWIND $rows AS c
MERGE (n:Column {id: c.id})
SET n.table_id      = c.table_id,
    n.name          = c.name,
    n.data_type     = c.data_type,
    n.source_engine = c.source_engine,
    n.ingested_at   = datetime()
"""

_MERGE_EDGES_CYPHER = """\
UNWIND $rows AS r
MATCH (t:Table  {id: r.table_id})
MATCH (c:Column {id: r.column_id})
MERGE (t)-[:HAS_COLUMN]->(c)
"""

_BATCH_SIZE = 500


def _normalise(row: dict[str, Any]) -> dict[str, Any]:
    """Lower-case all keys so Postgres (lowercase) and Snowflake (UPPERCASE) rows unify."""
    return {k.lower(): v for k, v in row.items()}


def build_table_nodes(rows: list[dict], source_engine: str) -> list[dict]:
    """Deduplicate rows into one dict per (schema, table)."""
    seen: set[str] = set()
    nodes: list[dict] = []
    for row in rows:
        r = _normalise(row)
        schema = r["table_schema"]
        table = r["table_name"]
        if schema in _EXCLUDED_SCHEMAS:
            continue
        node_id = f"{schema}.{table}"
        if node_id not in seen:
            seen.add(node_id)
            nodes.append({"id": node_id, "schema": schema, "name": table,
                          "source_engine": source_engine})
    return nodes


def build_column_nodes(rows: list[dict], source_engine: str) -> list[dict]:
    nodes: list[dict] = []
    for row in rows:
        r = _normalise(row)
        schema = r["table_schema"]
        if schema in _EXCLUDED_SCHEMAS:
            continue
        table_id = f"{schema}.{r['table_name']}"
        col_id = f"{table_id}.{r['column_name']}"
        nodes.append({
            "id": col_id,
            "table_id": table_id,
            "name": r["column_name"],
            "data_type": r["data_type"],
            "source_engine": source_engine,
        })
    return nodes


def build_edge_params(column_nodes: list[dict]) -> list[dict]:
    return [{"table_id": c["table_id"], "column_id": c["id"]} for c in column_nodes]


def _chunks(lst: list, size: int):
    for i in range(0, len(lst), size):
        yield lst[i : i + size]


async def _write_batches(
    session,
    cypher: str,
    rows: list[dict],
    label: str,
    dry_run: bool,
) -> None:
    total = len(rows)
    batches = list(_chunks(rows, _BATCH_SIZE))
    for i, batch in enumerate(batches, 1):
        print(f"[ingest_schema] writing {label} (batch {i}/{len(batches)})...")
        if not dry_run:
            await session.run(cypher, rows=batch)


async def run(dry_run: bool = False) -> None:
    settings = get_settings()
    engine = settings.DATA_LAKE_ENGINE.lower()

    connector = build_data_lake_connector(settings)
    await connector.init_pool()

    try:
        print(f"[ingest_schema] engine={engine}")
        result = await connector.execute(_DISCOVERY_QUERY)
    finally:
        await connector.close()

    raw_rows = result.rows
    if not raw_rows:
        print("[ingest_schema] no tables discovered — check DATA_LAKE_ENGINE settings and schema permissions")
        sys.exit(1)

    table_nodes = build_table_nodes(raw_rows, source_engine=engine)
    column_nodes = build_column_nodes(raw_rows, source_engine=engine)
    edge_params = build_edge_params(column_nodes)

    print(f"[ingest_schema] discovered {len(table_nodes)} tables, {len(column_nodes)} columns")

    if dry_run:
        print("[ingest_schema] --dry-run: skipping Neo4j writes")
        print(f"[ingest_schema] would write {len(table_nodes)} Table nodes, "
              f"{len(column_nodes)} Column nodes, {len(edge_params)} HAS_COLUMN edges")
        return

    driver = AsyncGraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
    )
    try:
        async with driver.session() as session:
            await _write_batches(session, _MERGE_TABLES_CYPHER, table_nodes, "Table nodes", dry_run)
            await _write_batches(session, _MERGE_COLUMNS_CYPHER, column_nodes, "Column nodes", dry_run)
            await _write_batches(session, _MERGE_EDGES_CYPHER, edge_params, "HAS_COLUMN edges", dry_run)
    finally:
        await driver.close()

    print(f"[ingest_schema] done — {len(table_nodes)} tables, {len(column_nodes)} columns written to Neo4j")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest customer schema into Neo4j KG")
    parser.add_argument("--dry-run", action="store_true",
                        help="Discover schema and print plan without writing to Neo4j")
    args = parser.parse_args()
    asyncio.run(run(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
