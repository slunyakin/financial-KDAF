"""Validator agent — LangGraph node.

Computes confidence components and decides whether to retry.

Confidence components (stored in ValidatorOutput.confidence_components):
  graph_coverage (weight 0.4): ≥1 BusinessRule or KnownAnomaly found in KG
  sql_pass       (weight 0.4): SQL executed without error AND returned rows
  reflection_agree (weight 0.2): set by Reflection node; placeholder 0.0 here

ValidatorOutput.passed = True when intermediate score ≥ 0.5
(i.e. at least one of KG coverage or SQL pass succeeded — enough to proceed
to Reflection, which may still produce a low-confidence result).

On failure: increments retry_count and appends issues to context_notes so
the Refiner can improve the question on the next attempt.
"""
from __future__ import annotations

from finance_analytics.schemas.agent_outputs import ValidatorOutput
from finance_analytics.schemas.agent_state import AgentState

_PASS_THRESHOLD = 0.5  # intermediate score threshold (before reflection_agree)


async def validator_node(state: AgentState) -> dict:
    cypher_context = state.get("cypher_context")
    sql_result = state.get("sql_result")
    python_result = state.get("python_result")
    refiner_output = state.get("refiner_output")
    retry_count: int = state.get("retry_count", 0)

    issues: list[str] = []

    # graph_coverage: did we find any relevant business rules or anomalies?
    graph_coverage = 0.0
    if cypher_context:
        if cypher_context.business_rules or cypher_context.known_anomalies:
            graph_coverage = 1.0
        else:
            issues.append("No matching BusinessRule or KnownAnomaly found for domain terms")

    # sql_pass: did SQL execute and return rows?
    sql_pass = 0.0
    if sql_result:
        if sql_result.row_count > 0:
            sql_pass = 1.0
        else:
            issues.append("SQL query returned zero rows — check filters or table data")
    else:
        issues.append("SQL execution did not produce a result")

    # If solver was required, check it ran
    if refiner_output and refiner_output.requires_solver and python_result is None:
        issues.append("Solver was required (requires_solver=True) but produced no result")

    # Intermediate score before reflection
    intermediate = 0.4 * graph_coverage + 0.4 * sql_pass
    passed = intermediate >= _PASS_THRESHOLD and not (
        refiner_output and refiner_output.requires_solver and python_result is None
    )

    validator_output = ValidatorOutput(
        passed=passed,
        issues=issues,
        confidence_components={
            "graph_coverage": graph_coverage,
            "sql_pass": sql_pass,
            "reflection_agree": 0.0,  # filled in by reflection_node
        },
    )

    updates: dict = {
        "validator_output": validator_output,
        "retry_count": retry_count + 1,
    }
    if not passed and issues:
        existing_notes: list[str] = state.get("context_notes", [])
        updates["context_notes"] = existing_notes + issues

    return updates
