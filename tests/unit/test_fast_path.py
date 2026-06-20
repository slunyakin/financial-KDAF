"""Unit tests for the Text-to-Cypher fast-path (domain_terms guard).

No external dependencies — fetch_kg_context is mocked.
"""
from unittest.mock import AsyncMock, patch

import pytest

from finance_analytics.schemas.agent_outputs import CypherContextOutput, RefinerOutput
from finance_analytics.schemas.agent_state import AgentState


def _make_state(domain_terms: list[str]) -> AgentState:
    return AgentState(
        question="What was revenue last quarter?",
        refiner_output=RefinerOutput(
            refined_question="What was revenue last quarter?",
            domain_terms=domain_terms,
            requires_solver=False,
            max_retries=2,
        ),
        cypher_context=None,
        sql_result=None,
        python_result=None,
        reflection_output=None,
        retry_count=0,
        context_notes=[],
        user_id="dev-analyst",
        user_roles=["analyst"],
    )


@pytest.mark.asyncio
async def test_fast_path_skips_fetch_when_domain_terms_empty():
    """When domain_terms is empty, fetch_kg_context must never be called."""
    from finance_analytics.agents.chain_executor import text_to_cypher_node

    with patch(
        "finance_analytics.agents.chain_executor.fetch_kg_context",
        new_callable=AsyncMock,
    ) as mock_fetch:
        state = _make_state(domain_terms=[])
        result = await text_to_cypher_node(state)

    mock_fetch.assert_not_called()
    assert isinstance(result["cypher_context"], CypherContextOutput)
    assert result["cypher_context"].business_rules == []
    assert result["cypher_context"].known_anomalies == []
    assert result["cypher_context"].concepts == []


@pytest.mark.asyncio
async def test_normal_path_calls_fetch_when_domain_terms_present():
    """When domain_terms is non-empty, fetch_kg_context must be called."""
    from finance_analytics.agents.chain_executor import text_to_cypher_node

    fake_context = CypherContextOutput(
        business_rules=[{"wacc": 0.08}],
        known_anomalies=[],
        concepts=[],
        cypher_used="MATCH (r:BusinessRule) RETURN r",
    )

    with patch(
        "finance_analytics.agents.chain_executor.fetch_kg_context",
        new_callable=AsyncMock,
        return_value=fake_context,
    ) as mock_fetch, patch(
        "finance_analytics.agents.chain_executor.conn"
    ) as mock_conn:
        mock_conn.get_neo4j.return_value.driver = object()
        mock_conn.get_redis.return_value = object()

        state = _make_state(domain_terms=["WACC", "cost_of_capital"])
        result = await text_to_cypher_node(state)

    mock_fetch.assert_called_once()
    assert result["cypher_context"] is fake_context


@pytest.mark.asyncio
async def test_fast_path_returns_valid_cypher_context_output():
    """fast-path result must be a CypherContextOutput, not None or a dict."""
    from finance_analytics.agents.chain_executor import text_to_cypher_node

    with patch("finance_analytics.agents.chain_executor.fetch_kg_context"):
        state = _make_state(domain_terms=[])
        result = await text_to_cypher_node(state)

    ctx = result["cypher_context"]
    assert isinstance(ctx, CypherContextOutput)
    # Verify it serialises cleanly (used downstream by python_executor_node)
    dumped = ctx.model_dump()
    assert "business_rules" in dumped
    assert "known_anomalies" in dumped
    assert "concepts" in dumped
