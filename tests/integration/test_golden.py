"""Golden evaluation dataset integration tests — TC1 through TC5.

Requires:
  - Docker Compose stack running: docker compose up -d
  - ANTHROPIC_API_KEY set (skip marker applied when absent)
  - Neo4j seed applied: scripts/smoke_test.sh --seed

Design: each TC class gets one class-scoped `state` fixture that calls run_query
once and caches the result. All assertion methods within the class share that
single state, reducing LLM round-trips from ~23 to 5 per full suite run.
"""
from __future__ import annotations

import json
import os
from typing import Any

import pytest
import pytest_asyncio

import finance_analytics.connectors as connectors
from finance_analytics.agents.supervisor import run_query
from finance_analytics.connectors.neo4j import Neo4jConnector
from finance_analytics.connectors.postgres import PostgresConnector
from finance_analytics.connectors.redis import RedisConnector
from tests.integration.conftest import (
    POSTGRES_DSN,
    NEO4J_URI,
    NEO4J_USER,
    NEO4J_PASSWORD,
    REDIS_URL,
)

# ---------------------------------------------------------------------------
# Skip LLM-dependent tests when no API key is present.
# Seed-data guard tests (test_seed_data_present) are in a separate class that
# is NOT skipped so CI without an LLM key still validates Postgres seed health.
# ---------------------------------------------------------------------------
pytestmark = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set — golden tests require live LLM",
)

_TEST_USER_ID = "test-evaluator"
_TEST_USER_ROLES = ["analyst", "finance", "executive"]

# Module-level question constants shared by fixtures and test classes.
_Q_TC1 = (
    "What drove the 14% unfavorable gross margin variance in our APAC Enterprise segment "
    "last quarter, and based on our historical price elasticity in that region, what is the "
    "exact pricing increase required to recover this margin without triggering a modeled "
    "volume drop of more than 5%?"
)
_Q_TC2 = (
    "Identify all global corporate accounts with unlinked subsidiaries purchasing at different "
    "discount tiers. Calculate total annualized ARR leakage, and generate a sequenced "
    "12-month consolidation plan that minimises churn risk."
)
_Q_TC3 = (
    "If our primary logistics vendor increases freight rates by 12% next quarter, will the "
    "consolidated impact breach our 3.5x net debt-to-EBITDA covenant? If so, which levers "
    "must we activate to maintain 0.2x headroom?"
)
_Q_TC4 = (
    "If we reduce CapEx for Project Alpha by 20% to fund Project Beta, what is the net "
    "24-month FCF impact, and at what exact month does accelerated ARR from Beta create "
    "a positive cumulative NPV crossover?"
)
_Q_TC5 = (
    "Given a 50 bps hike in core inflation, calculate rolling 4-quarter margin compression "
    "on indexed UK R&D labor contracts. How much margin is recovered by freezing the 15 open "
    "UK headcounts and rerouting to the Poland hub?"
)


# ---------------------------------------------------------------------------
# Module-scoped connector init — mirrors lifespan in main.py
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture(scope="module", autouse=True)
async def init_app_connectors():
    neo4j = Neo4jConnector(
        uri=NEO4J_URI,
        user=NEO4J_USER,
        password=NEO4J_PASSWORD,
        max_pool_size=10,
    )
    redis = RedisConnector(url=REDIS_URL)
    data_lake = PostgresConnector(dsn=POSTGRES_DSN, max_pool_size=5)
    await data_lake.init_pool()
    connectors.init_connectors(neo4j=neo4j, redis=redis, data_lake=data_lake)
    yield
    await connectors.close_connectors()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _attr(obj: Any, name: str, default: Any = None) -> Any:
    """Uniform attribute access for Pydantic models and plain dicts."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _solver_result(state: dict) -> Any:
    pr = state.get("python_result")
    if pr is None:
        return None
    result = _attr(pr, "result")
    if isinstance(result, str):
        try:
            return json.loads(result)
        except (json.JSONDecodeError, TypeError):
            return result
    return result


def _citations(state: dict) -> list[dict]:
    ro = state.get("reflection_output")
    if ro is None:
        return []
    citations = _attr(ro, "citations", [])
    return [c if isinstance(c, dict) else c.model_dump() for c in citations]


def _cited_business_rules(state: dict) -> list[str]:
    return [c["business_rule_id"] for c in _citations(state) if c.get("business_rule_id")]


def _confidence(state: dict) -> float:
    ro = state.get("reflection_output")
    if ro is None:
        return 0.0
    return _attr(ro, "confidence_score", 0.0)


def _cypher_ctx(state: dict) -> Any:
    return state.get("cypher_context")


# ---------------------------------------------------------------------------
# Class-scoped state fixtures — one run_query call per TC
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture(scope="class")
async def tc1_state(redis_client):
    await redis_client.flushdb()
    return await run_query(_Q_TC1, _TEST_USER_ID, _TEST_USER_ROLES)


@pytest_asyncio.fixture(scope="class")
async def tc2_state(redis_client):
    await redis_client.flushdb()
    return await run_query(_Q_TC2, _TEST_USER_ID, _TEST_USER_ROLES)


@pytest_asyncio.fixture(scope="class")
async def tc3_state(redis_client):
    await redis_client.flushdb()
    return await run_query(_Q_TC3, _TEST_USER_ID, _TEST_USER_ROLES)


@pytest_asyncio.fixture(scope="class")
async def tc4_state(redis_client):
    await redis_client.flushdb()
    return await run_query(_Q_TC4, _TEST_USER_ID, _TEST_USER_ROLES)


@pytest_asyncio.fixture(scope="class")
async def tc5_state(redis_client):
    await redis_client.flushdb()
    return await run_query(_Q_TC5, _TEST_USER_ID, _TEST_USER_ROLES)


# ---------------------------------------------------------------------------
# TC1 — APAC Margin Recovery (LP optimizer)
# ---------------------------------------------------------------------------
class TestTC1MarginRecovery:
    question = _Q_TC1

    @pytest.mark.asyncio
    async def test_seed_data_present(self, pg_pool):
        async with pg_pool.acquire() as conn:
            q3_rev = await conn.fetchrow(
                "SELECT amount FROM revenue WHERE segment = 'APAC Enterprise' AND quarter = 'Q3' AND year = 2025"
            )
            q4_rev = await conn.fetchrow(
                "SELECT amount FROM revenue WHERE segment = 'APAC Enterprise' AND quarter = 'Q4' AND year = 2025"
            )
            q3_cogs = await conn.fetchrow(
                "SELECT amount FROM cogs WHERE segment = 'APAC Enterprise' AND quarter = 'Q3' AND year = 2025"
            )
            q4_cogs = await conn.fetchrow(
                "SELECT amount FROM cogs WHERE segment = 'APAC Enterprise' AND quarter = 'Q4' AND year = 2025"
            )
        assert q3_rev is not None, "TC1: Q3 APAC Enterprise revenue missing"
        assert q4_rev is not None, "TC1: Q4 APAC Enterprise revenue missing"
        assert q3_cogs is not None, "TC1: Q3 APAC Enterprise COGS missing"
        assert q4_cogs is not None, "TC1: Q4 APAC Enterprise COGS missing"

    @pytest.mark.asyncio
    async def test_price_increase_in_range(self, tc1_state):
        result = _solver_result(tc1_state)
        assert result is not None, "TC1: PythonExecutor produced no result"
        assert "price_increase_pct" in result or "price_increase" in result, (
            "TC1: solver result missing price_increase_pct"
        )
        price_increase = float(result.get("price_increase_pct", result.get("price_increase")))
        assert 0.03 <= price_increase <= 0.06, (
            f"TC1: price_increase_pct={price_increase:.4f} not in [0.03, 0.06]"
        )

    @pytest.mark.asyncio
    async def test_volume_impact_within_limit(self, tc1_state):
        result = _solver_result(tc1_state)
        assert result is not None, "TC1: PythonExecutor produced no result"
        assert "volume_impact_pct" in result or "volume_impact" in result, (
            "TC1: solver result missing volume_impact_pct"
        )
        vol = float(result.get("volume_impact_pct", result.get("volume_impact")))
        assert abs(vol) <= 0.05, f"TC1: volume_impact_pct={vol:.4f} exceeds 5% limit"

    @pytest.mark.asyncio
    async def test_business_rule_cited(self, tc1_state):
        rules = _cited_business_rules(tc1_state)
        assert len(rules) >= 1, f"TC1: no BusinessRule cited (got citations: {_citations(tc1_state)})"

    @pytest.mark.asyncio
    async def test_sql_tables_queried(self, tc1_state):
        sql_result = tc1_state.get("sql_result")
        assert sql_result is not None, "TC1: sql_result missing from state"
        row_count = _attr(sql_result, "row_count", 0)
        assert row_count > 0, "TC1: SQL returned no rows"

    @pytest.mark.asyncio
    async def test_confidence_above_threshold(self, tc1_state):
        score = _confidence(tc1_state)
        assert score >= 0.7, f"TC1: confidence_score={score:.3f} below 0.7 threshold"


# ---------------------------------------------------------------------------
# TC2 — Churn-Constrained Revenue Capture (sequencing algorithm)
# ---------------------------------------------------------------------------
class TestTC2ChurnSequencing:
    question = _Q_TC2

    @pytest.mark.asyncio
    async def test_seed_data_present(self, pg_pool):
        async with pg_pool.acquire() as conn:
            parents = await conn.fetch(
                "SELECT DISTINCT parent_entity_id FROM contracts WHERE parent_entity_id IS NOT NULL"
            )
            hs = await conn.fetch(
                "SELECT * FROM health_scores WHERE legal_entity_id = 'AERO_JP'"
            )
        assert len(parents) >= 2, f"TC2: expected ≥2 parent relationships, got {len(parents)}"
        assert len(hs) == 1, "TC2: AERO_JP health score missing"
        assert hs[0]["health_score"] < 60, "TC2: AERO_JP health score should be < 60"

    @pytest.mark.asyncio
    async def test_minimum_account_pairs_identified(self, tc2_state):
        result = _solver_result(tc2_state)
        assert result is not None, "TC2: PythonExecutor produced no result"
        seq = result.get("consolidation_sequence", result.get("accounts", []))
        assert len(seq) >= 2, f"TC2: expected ≥2 account pairs in sequence, got {len(seq)}"

    @pytest.mark.asyncio
    async def test_arr_leakage_positive(self, tc2_state):
        result = _solver_result(tc2_state)
        assert result is not None, "TC2: PythonExecutor produced no result"
        assert "total_arr_leakage_annualized" in result or "arr_leakage" in result, (
            "TC2: solver result missing total_arr_leakage_annualized"
        )
        leakage = float(result.get("total_arr_leakage_annualized", result.get("arr_leakage")))
        assert leakage > 0, f"TC2: total_arr_leakage_annualized={leakage} is not positive"

    @pytest.mark.asyncio
    async def test_aerojapan_deferred(self, tc2_state):
        result = _solver_result(tc2_state)
        assert result is not None, "TC2: PythonExecutor produced no result"
        seq = result.get("consolidation_sequence", result.get("accounts", []))
        aero_jp_entries = [
            a for a in seq
            if "japan" in str(a.get("account", "")).lower()
            or "AERO_JP" in str(a.get("entity_id", ""))
        ]
        assert len(aero_jp_entries) >= 1, "TC2: AeroJapan not found in consolidation sequence"
        aero_jp = aero_jp_entries[0]
        note_or_status = str(aero_jp.get("note", aero_jp.get("status", ""))).lower()
        assert "defer" in note_or_status or "block" in note_or_status, (
            f"TC2: AeroJapan should be deferred/blocked (health < 60), got: {aero_jp}"
        )

    @pytest.mark.asyncio
    async def test_business_rule_cited(self, tc2_state):
        rules = _cited_business_rules(tc2_state)
        assert len(rules) >= 1, f"TC2: no BusinessRule cited (got: {_citations(tc2_state)})"


# ---------------------------------------------------------------------------
# TC3 — Covenant Defense (LP solver)
# ---------------------------------------------------------------------------
class TestTC3CovenantDefense:
    question = _Q_TC3

    @pytest.mark.asyncio
    async def test_seed_data_present(self, pg_pool):
        async with pg_pool.acquire() as conn:
            ebitda = await conn.fetchrow(
                "SELECT ebitda FROM ebitda_components WHERE quarter = 'Q4'"
            )
            vendor = await conn.fetchrow(
                "SELECT rate_change_pct FROM vendor_costs WHERE vendor_id = 'PRIMARY_LOGISTICS'"
            )
        assert ebitda is not None, "TC3: ebitda_components Q4 row missing"
        assert vendor is not None, "TC3: PRIMARY_LOGISTICS vendor row missing"
        assert float(vendor["rate_change_pct"]) == pytest.approx(0.12, abs=0.001), (
            f"TC3: PRIMARY_LOGISTICS rate_change_pct expected 0.12, got {vendor['rate_change_pct']}"
        )

    @pytest.mark.asyncio
    async def test_post_lever_ratio_within_covenant(self, tc3_state):
        result = _solver_result(tc3_state)
        assert result is not None, "TC3: PythonExecutor produced no result"
        assert "post_lever_ratio" in result or "ratio_after_levers" in result, (
            "TC3: solver result missing post_lever_ratio"
        )
        ratio = float(result.get("post_lever_ratio", result.get("ratio_after_levers")))
        assert ratio <= 3.3, f"TC3: post_lever_ratio={ratio:.3f} exceeds 3.3 target"

    @pytest.mark.asyncio
    async def test_covenant_not_breached_after_levers(self, tc3_state):
        result = _solver_result(tc3_state)
        assert result is not None, "TC3: PythonExecutor produced no result"
        breached = result.get("covenant_breached", True)
        assert not breached, f"TC3: covenant_breached={breached} — levers must prevent breach"

    @pytest.mark.asyncio
    async def test_dpo_lever_activated(self, tc3_state):
        result = _solver_result(tc3_state)
        assert result is not None, "TC3: PythonExecutor produced no result"
        levers = result.get("levers_activated", result.get("levers", []))
        lever_names = [str(l.get("lever", l.get("name", ""))).lower() for l in levers]
        assert any("dpo" in n or "payable" in n for n in lever_names), (
            f"TC3: DPO lever not found in activated levers: {lever_names}"
        )

    @pytest.mark.asyncio
    async def test_at_least_two_business_rules_cited(self, tc3_state):
        rules = _cited_business_rules(tc3_state)
        assert len(rules) >= 2, (
            f"TC3: expected ≥2 BusinessRule citations, got {len(rules)}: {rules}"
        )

    @pytest.mark.asyncio
    async def test_freight_shock_from_vendor_node(self, tc3_state):
        ctx = _cypher_ctx(tc3_state)
        assert ctx is not None, "TC3: cypher_context missing — Vendor node not fetched"
        concepts = _attr(ctx, "concepts", [])
        rules = _attr(ctx, "business_rules", [])
        freight_terms = ("vendor", "logistics", "freight", "surcharge")
        freight_in_ctx = any(
            any(t in str(c).lower() for t in freight_terms) for c in concepts
        )
        freight_in_rules = any(
            any(t in str(r).lower() for t in freight_terms) for r in rules
        )
        assert freight_in_ctx or freight_in_rules, "TC3: Vendor/freight context not fetched from Neo4j"


# ---------------------------------------------------------------------------
# TC4 — Capital Reallocation Cross-Over (DCF)
# ---------------------------------------------------------------------------
class TestTC4CapitalReallocation:
    question = _Q_TC4

    @pytest.mark.asyncio
    async def test_seed_data_present(self, pg_pool):
        async with pg_pool.acquire() as conn:
            alpha_rows = await conn.fetchval(
                "SELECT COUNT(*) FROM project_cashflows WHERE project_id = 'alpha'"
            )
            beta_rows = await conn.fetchval(
                "SELECT COUNT(*) FROM project_cashflows WHERE project_id = 'beta'"
            )
        assert alpha_rows == 24, f"TC4: expected 24 alpha rows, got {alpha_rows}"
        assert beta_rows == 24, f"TC4: expected 24 beta rows, got {beta_rows}"

    @pytest.mark.asyncio
    async def test_npv_crossover_month_in_range(self, tc4_state):
        result = _solver_result(tc4_state)
        assert result is not None, "TC4: PythonExecutor produced no result"
        assert "npv_crossover_month" in result or "crossover_month" in result, (
            "TC4: solver result missing npv_crossover_month"
        )
        month = int(result.get("npv_crossover_month", result.get("crossover_month")))
        assert 10 <= month <= 18, f"TC4: npv_crossover_month={month} not in [10, 18]"

    @pytest.mark.asyncio
    async def test_sla_penalty_triggered(self, tc4_state):
        result = _solver_result(tc4_state)
        assert result is not None, "TC4: PythonExecutor produced no result"
        triggered = result.get("sla_penalty_triggered", result.get("penalty_triggered", None))
        assert triggered is True, (
            f"TC4: sla_penalty_triggered expected True, got {triggered}"
        )

    @pytest.mark.asyncio
    async def test_wacc_from_cost_of_capital_node(self, tc4_state):
        ctx = _cypher_ctx(tc4_state)
        assert ctx is not None, "TC4: cypher_context missing — CostOfCapital not fetched"
        concepts = _attr(ctx, "concepts", [])
        rules = _attr(ctx, "business_rules", [])
        wacc_terms = ("wacc", "cost of capital", "0.115")
        wacc_in_ctx = any(
            any(t in str(c).lower() for t in wacc_terms) for c in concepts
        )
        wacc_in_rules = any("capital" in str(r).lower() for r in rules)
        assert wacc_in_ctx or wacc_in_rules, (
            "TC4: WACC (CostOfCapital node) not present in cypher_context — must not be hardcoded"
        )

    @pytest.mark.asyncio
    async def test_at_least_two_business_rules_cited(self, tc4_state):
        rules = _cited_business_rules(tc4_state)
        assert len(rules) >= 2, (
            f"TC4: expected ≥2 BusinessRule citations, got {len(rules)}: {rules}"
        )


# ---------------------------------------------------------------------------
# TC5 — Inflation Macro-Shock Mitigation (delta engine)
# ---------------------------------------------------------------------------
class TestTC5InflationShock:
    question = _Q_TC5

    @pytest.mark.asyncio
    async def test_seed_data_present(self, pg_pool):
        async with pg_pool.acquire() as conn:
            uk_labor = await conn.fetchrow(
                "SELECT headcount FROM labor_costs WHERE location = 'UK' AND quarter = 'Q4'"
            )
            open_reqs = await conn.fetchval(
                "SELECT COUNT(*) FROM job_requisitions WHERE location = 'UK' AND status = 'Open'"
            )
        assert uk_labor is not None, "TC5: UK labor_costs Q4 row missing"
        assert int(uk_labor["headcount"]) == 60, f"TC5: UK headcount expected 60, got {uk_labor['headcount']}"
        assert open_reqs == 15, f"TC5: expected 15 open UK requisitions, got {open_reqs}"

    @pytest.mark.asyncio
    async def test_quarterly_compression_in_range(self, tc5_state):
        result = _solver_result(tc5_state)
        assert result is not None, "TC5: PythonExecutor produced no result"
        assert "quarterly_compression_bps" in result or "compression_bps" in result, (
            "TC5: solver result missing quarterly_compression_bps"
        )
        bps = float(result.get("quarterly_compression_bps", result.get("compression_bps")))
        assert 55 <= bps <= 75, f"TC5: quarterly_compression_bps={bps} not in [55, 75]"

    @pytest.mark.asyncio
    async def test_geo_arbitrage_recovery_in_range(self, tc5_state):
        result = _solver_result(tc5_state)
        assert result is not None, "TC5: PythonExecutor produced no result"
        assert "geo_arbitrage_recovery_bps" in result or "recovery_bps" in result, (
            "TC5: solver result missing geo_arbitrage_recovery_bps"
        )
        recovery = float(result.get("geo_arbitrage_recovery_bps", result.get("recovery_bps")))
        assert 40 <= recovery <= 55, f"TC5: geo_arbitrage_recovery_bps={recovery} not in [40, 55]"

    @pytest.mark.asyncio
    async def test_ramp_penalty_from_neo4j_node(self, tc5_state):
        ctx = _cypher_ctx(tc5_state)
        assert ctx is not None, "TC5: cypher_context missing — RampPenalty node not fetched"
        concepts = _attr(ctx, "concepts", [])
        rules = _attr(ctx, "business_rules", [])
        ramp_terms = ("ramp", "penalty", "poland")
        ramp_in_ctx = any(any(t in str(c).lower() for t in ramp_terms) for c in concepts)
        ramp_in_rules = any(any(t in str(r).lower() for t in ramp_terms) for r in rules)
        assert ramp_in_ctx or ramp_in_rules, (
            "TC5: RampPenalty node context not found in cypher_context — must come from Neo4j"
        )

    @pytest.mark.asyncio
    async def test_uk_bonus_anomaly_cited(self, tc5_state):
        ctx = _cypher_ctx(tc5_state)
        assert ctx is not None, "TC5: cypher_context missing"
        anomalies = _attr(ctx, "known_anomalies", [])
        bonus_anomaly = any(
            "bonus" in str(a).lower() and ("uk" in str(a).lower() or "r&d" in str(a).lower())
            for a in anomalies
        )
        assert bonus_anomaly, "TC5: KnownAnomaly for UK R&D bonus cycle not in cypher_context"

    @pytest.mark.asyncio
    async def test_at_least_three_business_rules_cited(self, tc5_state):
        rules = _cited_business_rules(tc5_state)
        assert len(rules) >= 3, (
            f"TC5: expected ≥3 BusinessRule citations, got {len(rules)}: {rules}"
        )


# ---------------------------------------------------------------------------
# Cross-cutting: Redis cache prevents duplicate LLM calls
# ---------------------------------------------------------------------------
class TestCacheIntegration:
    question = _Q_TC1  # reuse TC1 question; cache behaviour is question-agnostic

    @pytest.mark.asyncio
    async def test_second_identical_query_is_cached(self, fresh_redis):
        state1 = await run_query(self.question, _TEST_USER_ID, _TEST_USER_ROLES)
        assert not state1.get("cached"), "First query should not be cached"

        state2 = await run_query(self.question, _TEST_USER_ID, _TEST_USER_ROLES)
        assert state2.get("cached"), "Second identical query should be served from cache"

    @pytest.mark.asyncio
    async def test_different_user_not_cached(self, fresh_redis):
        await run_query(self.question, "user-a", _TEST_USER_ROLES)
        state = await run_query(self.question, "user-b", _TEST_USER_ROLES)
        assert not state.get("cached"), "Different user_id must not share cache entry"
