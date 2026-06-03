"""KG context fetcher with write guard and Redis caching.

Per ADR-005: Text-to-Cypher runs BEFORE Text-to-SQL so that KG context is
stored in AgentState.cypher_context and available to the SQL generation prompt.

Security:
  - assert_read_only() blocks Cypher write mutations on the query path
  - The enrichment write path (POST /api/v1/graph/write) is separate and requires
    the knowledge_engineer role (not implemented in v1 — deferred to TODOS.md)

Caching (T8):
  - Key: kg:{sha256(sorted_domain_terms + "|" + sorted_user_roles)}, TTL=5min
  - user_roles in key for future visibility enforcement (v1: KG is world-readable)
  - Invalidated by tools/kg_cache.py::KG_INVALIDATION_LABELS writes
"""
from __future__ import annotations

import json
import re
from typing import List

from neo4j import AsyncDriver

from finance_analytics.connectors.redis import RedisConnector
from finance_analytics.schemas.agent_outputs import CypherContextOutput
from finance_analytics.tools.kg_cache import KG_CACHE_TTL, kg_cache_key

# Cypher clause keywords that mutate the graph
_WRITE_PATTERN = re.compile(
    r"\b(MERGE|CREATE|SET|DELETE|DETACH\s+DELETE|REMOVE|DROP)\b",
    re.IGNORECASE,
)


def assert_read_only(cypher: str) -> None:
    """Raise ValueError if cypher contains write mutation keywords.

    Called on all Cypher strings before execution on the query path.
    LLM-generated Cypher must pass this guard — the LLM cannot be trusted
    to omit write clauses; the guard enforces it at execution time.
    """
    match = _WRITE_PATTERN.search(cypher)
    if match:
        raise ValueError(
            f"Cypher write operation '{match.group().upper()}' is not permitted "
            "on the read path. Use the enrichment write endpoint."
        )


async def fetch_kg_context(
    domain_terms: List[str],
    user_roles: List[str],
    neo4j_driver: AsyncDriver,
    redis_client: RedisConnector,
) -> CypherContextOutput:
    """Fetch BusinessRules, KnownAnomalies, and Concepts matching domain_terms.

    Cache-first: returns cached result on Redis hit. On miss, queries Neo4j
    with three separate reads in one session, caches the result, and returns it.

    Per v1 KG access control: visibility filtering is NOT applied (KG is
    world-readable for all authenticated company users). user_roles is included
    in the cache key so future enforcement produces separate entries per role.
    """
    cache_key = kg_cache_key(domain_terms, user_roles)

    cached = await redis_client.get(cache_key)
    if cached:
        return CypherContextOutput(**json.loads(cached))

    # Cache miss — query Neo4j
    br_cypher = (
        "MATCH (r:BusinessRule) "
        "WHERE any(term IN $terms WHERE toLower(r.description) CONTAINS toLower(term)) "
        "RETURN properties(r) AS r LIMIT 20"
    )
    ka_cypher = (
        "MATCH (a:KnownAnomaly) "
        "WHERE any(term IN $terms WHERE toLower(a.description) CONTAINS toLower(term)) "
        "RETURN properties(a) AS a LIMIT 10"
    )
    concept_cypher = (
        "MATCH (c:Concept) "
        "WHERE any(term IN $terms WHERE toLower(c.name) CONTAINS toLower(term) "
        "   OR any(s IN coalesce(c.synonyms, []) WHERE toLower(s) CONTAINS toLower(term))) "
        "RETURN properties(c) AS c LIMIT 20"
    )

    for q in (br_cypher, ka_cypher, concept_cypher):
        assert_read_only(q)

    business_rules: list = []
    known_anomalies: list = []
    concepts: list = []

    async with neo4j_driver.session() as session:
        br_result = await session.run(br_cypher, terms=domain_terms)
        business_rules = [rec["r"] for rec in await br_result.data()]

        ka_result = await session.run(ka_cypher, terms=domain_terms)
        known_anomalies = [rec["a"] for rec in await ka_result.data()]

        c_result = await session.run(concept_cypher, terms=domain_terms)
        concepts = [rec["c"] for rec in await c_result.data()]

    context = CypherContextOutput(
        business_rules=business_rules,
        known_anomalies=known_anomalies,
        concepts=concepts,
        cypher_used="; ".join([br_cypher, ka_cypher, concept_cypher]),
    )

    await redis_client.setex(cache_key, KG_CACHE_TTL, json.dumps(context.model_dump()))
    return context
