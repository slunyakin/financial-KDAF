"""Unit tests for the Cypher write guard.

These tests have no external dependencies (no Neo4j, no Redis, no LLM).
They verify that assert_read_only() blocks all write mutation keywords and
passes legitimate read-only queries.
"""
import pytest

from finance_analytics.execution.cypher import assert_read_only


# ── Blocked cases ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("cypher", [
    "MERGE (n:BusinessRule {rule_id: 'BR-001'})",
    "CREATE (n:Concept {name: 'margin'})",
    "MATCH (n) SET n.description = 'updated'",
    "MATCH (n:KnownAnomaly) DELETE n",
    "MATCH (n:Covenant) DETACH DELETE n",
    "MATCH (n) REMOVE n.visibility",
    "DROP CONSTRAINT rule_id_unique",
    # Case insensitive
    "merge (n:BusinessRule {rule_id: 'x'})",
    "create (:Concept {name: 'test'})",
    # Inline within a longer query
    "MATCH (n:Table) WHERE n.name = 'revenue' SET n.owner = 'finance'",
    "MATCH (n) DETACH DELETE n",
])
def test_write_mutations_are_blocked(cypher: str) -> None:
    with pytest.raises(ValueError, match="write operation"):
        assert_read_only(cypher)


# ── Allowed cases ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("cypher", [
    "MATCH (r:BusinessRule) RETURN r",
    "MATCH (r:BusinessRule) WHERE any(term IN $terms WHERE r.description CONTAINS term) RETURN r",
    "MATCH (a:KnownAnomaly) RETURN a LIMIT 10",
    "MATCH (c:Concept) WHERE c.name CONTAINS $term RETURN c",
    "MATCH (s:Segment)-[:HAS_METRIC]->(e:Elasticity) RETURN s, e",
    # MATCH + RETURN is always safe
    "MATCH (n) RETURN count(n) AS total",
])
def test_read_only_queries_pass(cypher: str) -> None:
    assert_read_only(cypher)  # must not raise
