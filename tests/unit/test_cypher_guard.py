"""Unit tests for the Cypher write guard and visibility enforcement.

These tests have no external dependencies (no Neo4j, no Redis, no LLM).
They verify that assert_read_only() blocks all write mutation keywords,
passes legitimate read-only queries, and that _visibility_clause() produces
correct Cypher predicates that themselves pass the read-only guard.
"""
import pytest

from finance_analytics.execution.cypher import _visibility_clause, assert_read_only


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


# ── _visibility_clause ─────────────────────────────────────────────────────────

def test_visibility_clause_structure():
    clause = _visibility_clause("r")
    assert "r.visibility IS NULL" in clause
    assert "$visibility_roles" in clause
    assert "any(role IN $visibility_roles WHERE role IN r.visibility)" in clause


def test_visibility_clause_uses_correct_variable():
    for var in ("r", "a", "c", "node", "x"):
        clause = _visibility_clause(var)
        assert f"{var}.visibility IS NULL" in clause
        assert f"role IN {var}.visibility" in clause


def test_visibility_clause_is_parenthesised():
    clause = _visibility_clause("r")
    assert clause.startswith("(")
    assert clause.endswith(")")


def test_visibility_clause_passes_read_only_guard():
    # The visibility predicate must not trip the write guard when embedded in a query
    for var in ("r", "a", "c"):
        clause = _visibility_clause(var)
        query = (
            f"MATCH (n:{var.upper()}) "
            f"WHERE {clause} "
            f"RETURN n"
        )
        assert_read_only(query)  # must not raise


def test_visibility_clause_embedded_in_and_passes_guard():
    clause = _visibility_clause("r")
    query = (
        "MATCH (r:BusinessRule) "
        "WHERE any(term IN $terms WHERE toLower(r.description) CONTAINS toLower(term)) "
        f"  AND {clause} "
        "RETURN properties(r) AS r LIMIT 20"
    )
    assert_read_only(query)  # must not raise


@pytest.mark.parametrize("roles,expected_visibility_param", [
    (["analyst"],                  True),
    (["finance", "executive"],     True),
    ([],                           True),   # empty roles → no access to restricted nodes; clause still present
])
def test_visibility_clause_format_independent_of_roles(roles, expected_visibility_param):
    # The clause itself doesn't embed the role values — they're passed as $visibility_roles parameter
    clause = _visibility_clause("r")
    assert "$visibility_roles" in clause  # always a parameter reference, never inline values
