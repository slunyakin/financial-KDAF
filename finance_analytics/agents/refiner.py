"""Refiner agent — LangGraph node.

Responsibilities:
  - Extract financial domain terms for KG lookup
  - Determine if a mathematical solver is required
  - Refine the question for downstream SQL/Cypher generation
  - On retry: incorporate validator issues from context_notes

max_retries policy (set here, not by LLM):
  - requires_solver=False → max_retries=2
  - requires_solver=True  → max_retries=1 (solver retries are expensive)
"""
from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from finance_analytics.llm import get_llm
from finance_analytics.schemas.agent_outputs import RefinerOutput
from finance_analytics.schemas.agent_state import AgentState

_SYSTEM = """\
You are a financial query analyst. Your job is to prepare a CFO question for an
analytics pipeline that combines a Neo4j knowledge graph with SQL queries.

Given a question (and optional retry context from previous failed attempts),
output three things:

1. refined_question — restate the question precisely. Resolve ambiguous terms
   (e.g. "last quarter" → specific period if inferable). Do not add assumptions
   not in the question.

2. domain_terms — 3 to 8 financial domain terms from the question that will be
   used to look up business rules, known anomalies, and concepts in the knowledge
   graph. Examples: "gross margin", "EBITDA", "net debt-to-EBITDA", "price elasticity",
   "DPO", "ARR", "WACC", "churn risk", "covenant".

3. requires_solver — true ONLY if the question requires a mathematical solver
   beyond SQL aggregation:
   - Linear program / optimization (maximize/minimize with constraints)
   - DCF / NPV calculation over multiple periods
   - Elasticity-constrained price optimization
   - Sequencing algorithm with health/renewal constraints
   - Delta / sensitivity calculation across multiple inputs
   Set false for questions answerable by SQL GROUP BY / SUM / AVG / JOIN alone.
"""

_RETRY_SECTION = """\

Previous attempt failed. Validator issues:
{issues}

Refine the question with these failures in mind. Be more specific about the
time period, filters, or metric definitions to avoid the same errors.
"""


class _LLMOutput(BaseModel):
    refined_question: str
    domain_terms: list[str] = Field(min_length=1, max_length=10)
    requires_solver: bool


async def refiner_node(state: AgentState) -> dict:
    question = state["question"]
    context_notes: list[str] = state.get("context_notes", [])

    human_text = f"Question: {question}"
    if context_notes:
        retry_context = _RETRY_SECTION.format(issues="\n".join(f"- {n}" for n in context_notes))
        human_text = retry_context.strip() + "\n\n" + human_text

    llm = get_llm().with_structured_output(_LLMOutput)
    result: _LLMOutput = await llm.ainvoke([
        SystemMessage(content=_SYSTEM),
        HumanMessage(content=human_text),
    ])

    max_retries = 1 if result.requires_solver else 2
    refiner_output = RefinerOutput(
        refined_question=result.refined_question,
        query_type="exploratory",
        domain_terms=result.domain_terms,
        requires_solver=result.requires_solver,
        max_retries=max_retries,
    )
    return {"refiner_output": refiner_output}
