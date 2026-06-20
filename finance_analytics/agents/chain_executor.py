"""Chain executor — three sequential LangGraph nodes (Text-to-Cypher → Text-to-SQL → PythonExecutor).

Per ADR-005: these run SEQUENTIALLY so KG context from Text-to-Cypher is available
in the Text-to-SQL prompt. Parallel execution would break TC1/TC3/TC5 where the
SQL agent must apply business rules fetched from the knowledge graph.

Node functions (all imported by supervisor.py for StateGraph wiring):
  text_to_cypher_node  — fetches BusinessRules/KnownAnomalies/Concepts from Neo4j
  text_to_sql_node     — generates + executes SQL using KG context
  python_executor_node — generates + runs solver code (only if requires_solver=True)
"""
from __future__ import annotations

import re

from langchain_core.messages import HumanMessage, SystemMessage

import finance_analytics.connectors as conn
from finance_analytics.execution.cypher import fetch_kg_context
from finance_analytics.execution.python_executor import execute_solver
from finance_analytics.execution.sql import execute_sql
from finance_analytics.llm import get_llm
from finance_analytics.schemas.agent_outputs import CypherContextOutput
from finance_analytics.schemas.agent_state import AgentState

# ── Text-to-Cypher ─────────────────────────────────────────────────────────────

async def text_to_cypher_node(state: AgentState) -> dict:
    """Fetch KG context (BusinessRules, KnownAnomalies, Concepts) for the domain terms.

    Stores result in AgentState.cypher_context so text_to_sql_node can inject
    it into the SQL generation prompt.

    Fast-path: if the Refiner found no domain terms, skip Neo4j entirely and
    return an empty context. Saves ~200ms cold-cache Neo4j round-trip for simple
    aggregation questions that have no matching business rules.
    """
    refiner_output = state["refiner_output"]
    if not refiner_output.domain_terms:
        return {"cypher_context": CypherContextOutput(
            business_rules=[], known_anomalies=[], concepts=[], cypher_used=""
        )}
    cypher_context = await fetch_kg_context(
        domain_terms=refiner_output.domain_terms,
        user_roles=state.get("user_roles", []),
        neo4j_driver=conn.get_neo4j().driver,
        redis_client=conn.get_redis(),
    )
    return {"cypher_context": cypher_context}


# ── Text-to-SQL ────────────────────────────────────────────────────────────────

_SQL_SYSTEM = """\
You are a SQL generation specialist for financial analytics.

SQL dialect: {dialect}

{schema}

Dialect-specific syntax patterns for {dialect}:
{dialect_examples}

Business rules from the knowledge graph (MUST apply these rules to your query):
{business_rules}

Known anomalies (MUST account for these in your query or filters):
{known_anomalies}

Generate a single {dialect} SELECT query that answers the question.
- Apply all business rules listed above.
- Use table aliases for readability.
- Do NOT use CTEs unless the query requires multi-step aggregation.
- Return ONLY the SQL query, no explanation, no markdown fences.
"""

def _format_kg_items(items: list) -> str:
    if not items:
        return "None"
    lines = []
    for item in items:
        desc = item.get("description") or item.get("name") or str(item)
        rule_id = item.get("rule_id") or item.get("period") or ""
        lines.append(f"- [{rule_id}] {desc}" if rule_id else f"- {desc}")
    return "\n".join(lines)


def _extract_sql(text: str) -> str:
    """Strip markdown code fences if the model wrapped the SQL."""
    match = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return text.strip()


async def text_to_sql_node(state: AgentState) -> dict:
    """Generate SQL using KG context, then execute via the active DataLakeConnector."""
    refiner_output = state["refiner_output"]
    cypher_context = state["cypher_context"]
    data_lake = conn.get_data_lake()

    schema = await data_lake.schema_description()
    examples = data_lake.dialect_examples
    examples_str = (
        "\n".join(f"- {k}: `{v}`" for k, v in examples.items())
        if examples
        else "Standard SQL patterns apply."
    )
    system_content = _SQL_SYSTEM.format(
        dialect=data_lake.dialect,
        schema=schema,
        dialect_examples=examples_str,
        business_rules=_format_kg_items(cypher_context.business_rules),
        known_anomalies=_format_kg_items(cypher_context.known_anomalies),
    )

    llm = get_llm()
    response = await llm.ainvoke([
        SystemMessage(content=system_content),
        HumanMessage(content=f"Question: {refiner_output.refined_question}"),
    ])

    sql = _extract_sql(response.content)
    sql_result = await execute_sql(sql, data_lake)
    return {"sql_result": sql_result}


# ── PythonExecutor ─────────────────────────────────────────────────────────────

_SOLVER_SYSTEM = """\
You are a financial solver specialist. Write Python code to answer a CFO's question
using data already fetched from a knowledge graph and SQL query.

Available variables (pre-populated in your execution namespace):
  cypher_context: dict — business rules, known anomalies, financial parameters from Neo4j
                  Structure: {"business_rules": [...], "known_anomalies": [...], "concepts": [...]}
  sql_rows: list of dicts — rows returned by the SQL query

Available imports: numpy, scipy, pandas, math, statistics, json
All other imports are blocked.

RULES:
1. Read ALL numerical parameters from cypher_context or sql_rows — NEVER hardcode
   financial values (elasticity coefficients, WACC, rates, limits, headcounts, etc.)
2. Assign the final answer to a variable named `result`
3. result must be JSON-serializable (dict, list, float, int, or str — not numpy types)
   Use float(x) or int(x) to convert numpy scalars
4. Your code MUST reference `cypher_context` or `sql_rows`

Example structure:
    # Read parameters from KG context
    wacc = cypher_context["business_rules"][0]["wacc"]
    # Read data from SQL
    flows = [row["fcf"] for row in sql_rows]
    # Compute
    result = {"npv": sum(f / (1 + wacc/12)**i for i, f in enumerate(flows, 1))}
"""


def _extract_code(text: str) -> str:
    match = re.search(r"```(?:python)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return text.strip()


async def python_executor_node(state: AgentState) -> dict:
    """Generate and execute a Python solver using cypher_context and sql_rows."""
    refiner_output = state["refiner_output"]
    cypher_context = state["cypher_context"]
    sql_result = state["sql_result"]

    llm = get_llm()
    response = await llm.ainvoke([
        SystemMessage(content=_SOLVER_SYSTEM),
        HumanMessage(content=(
            f"Question: {refiner_output.refined_question}\n\n"
            f"SQL rows sample (first 5): {sql_result.rows[:5]}\n\n"
            f"KG context summary: {len(cypher_context.business_rules)} business rules, "
            f"{len(cypher_context.known_anomalies)} known anomalies"
        )),
    ])

    code = _extract_code(response.content)
    python_result = await execute_solver(
        code=code,
        cypher_context=cypher_context.model_dump(),
        sql_rows=sql_result.rows,
    )
    return {"python_result": python_result}
