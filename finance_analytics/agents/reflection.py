"""Reflection agent — LangGraph node.

Responsibilities:
  1. Verify the answer actually addresses the original question (LLM structured call)
  2. Extract citations (source tables + business rule IDs)
  3. Compute final confidence_score = 0.4×graph_coverage + 0.4×sql_pass + 0.2×agree
  4. If confidence_score < 0.7 OR retry exhaustion: write EnrichmentTask to Neo4j

EnrichmentTask is written on:
  - Low confidence (< 0.7): system couldn't produce a high-quality answer
  - Retry exhaustion (validator never passed): system gave up with confidence=0.0

In both cases the answer is returned to the user with a low_confidence flag.
The EnrichmentTask is picked up by a knowledge engineer who enriches the graph
so future questions on the same topic improve.
"""
from __future__ import annotations

import json

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

import finance_analytics.connectors as conn
from finance_analytics.llm import get_llm
from finance_analytics.schemas.agent_outputs import Citation, ReflectionOutput
from finance_analytics.schemas.agent_state import AgentState

_CONFIDENCE_THRESHOLD = 0.7

_SYSTEM = """\
You are a financial answer verifier. Given a CFO question and the data used to
answer it, verify the answer quality and extract structured citations.

Output:
  addresses_question: true if the data provided is sufficient to directly answer
    the question; false if the answer is incomplete, uses wrong metrics, or the
    data doesn't support the conclusion.
  reasoning: 1-2 sentences explaining your verdict
  citations: list of citations, each with:
    - source_table: SQL table name (if the data came from SQL)
    - business_rule_id: rule_id from the KG (if a business rule was applied)
    - excerpt: 1 sentence describing what this source contributed
    - confidence: 0.0-1.0 for this individual citation
"""


class _LLMOutput(BaseModel):
    addresses_question: bool
    reasoning: str
    citations: list[Citation]


async def _write_enrichment_task(
    question_text: str,
    confidence_score: float,
    missing_context: list[str],
) -> str | None:
    """Write an EnrichmentTask node to Neo4j. Returns the node element ID."""
    cypher = (
        "CREATE (t:EnrichmentTask {"
        "  question_text: $question_text,"
        "  confidence_score: $confidence_score,"
        "  missing_context: $missing_context,"
        "  status: 'open',"
        "  created_at: datetime()"
        "}) "
        "RETURN elementId(t) AS task_id"
    )
    try:
        async with conn.get_neo4j().driver.session() as session:
            result = await session.run(
                cypher,
                question_text=question_text,
                confidence_score=confidence_score,
                missing_context=missing_context,
            )
            record = await result.single()
            return record["task_id"] if record else None
    except Exception:
        return None  # enrichment task write failure must not break the user-facing answer


async def reflection_node(state: AgentState) -> dict:
    question = state["question"]
    cypher_context = state.get("cypher_context")
    sql_result = state.get("sql_result")
    python_result = state.get("python_result")
    validator_output = state.get("validator_output")

    # Retry exhaustion path: return low-confidence answer immediately
    refiner_output = state.get("refiner_output")
    retry_count: int = state.get("retry_count", 0)
    max_retries = refiner_output.max_retries if refiner_output else 2

    if validator_output and not validator_output.passed and retry_count > max_retries:
        task_id = await _write_enrichment_task(
            question_text=question,
            confidence_score=0.0,
            missing_context=state.get("context_notes", []),
        )
        reflection = ReflectionOutput(
            addresses_question=False,
            reasoning="Max retries exhausted without a passing validation result.",
            citations=[],
            confidence_score=0.0,
        )
        return {
            "reflection_output": reflection,
            "answer": {"enrichment_task_id": task_id, "confidence_score": 0.0},
        }

    # Normal reflection: call LLM for addresses_question + citations
    sql_summary = (
        f"{sql_result.row_count} rows from SQL"
        if sql_result
        else "No SQL result"
    )
    solver_summary = (
        f"Solver result: {json.dumps(python_result.result, default=str)[:500]}"
        if python_result
        else "No solver result"
    )
    kg_summary = (
        f"{len(cypher_context.business_rules)} business rules, "
        f"{len(cypher_context.known_anomalies)} anomalies applied"
        if cypher_context
        else "No KG context"
    )

    human_text = (
        f"Question: {question}\n\n"
        f"KG context used: {kg_summary}\n"
        f"SQL data: {sql_summary}\n"
        f"{solver_summary}"
    )

    llm = get_llm().with_structured_output(_LLMOutput)
    llm_result: _LLMOutput = await llm.ainvoke([
        SystemMessage(content=_SYSTEM),
        HumanMessage(content=human_text),
    ])

    # Compute final confidence score
    components = validator_output.confidence_components if validator_output else {}
    graph_coverage = components.get("graph_coverage", 0.0)
    sql_pass = components.get("sql_pass", 0.0)
    reflection_agree = 1.0 if llm_result.addresses_question else 0.0
    confidence_score = round(
        0.4 * graph_coverage + 0.4 * sql_pass + 0.2 * reflection_agree, 3
    )

    reflection = ReflectionOutput(
        addresses_question=llm_result.addresses_question,
        reasoning=llm_result.reasoning,
        citations=llm_result.citations,
        confidence_score=confidence_score,
    )

    # Write EnrichmentTask if below threshold
    enrichment_task_id: str | None = None
    if confidence_score < _CONFIDENCE_THRESHOLD:
        enrichment_task_id = await _write_enrichment_task(
            question_text=question,
            confidence_score=confidence_score,
            missing_context=state.get("context_notes", []),
        )

    return {
        "reflection_output": reflection,
        "answer": {
            "confidence_score": confidence_score,
            "enrichment_task_id": enrichment_task_id,
        },
    }
