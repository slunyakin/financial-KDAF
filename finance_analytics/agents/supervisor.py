"""Supervisor — LangGraph StateGraph definition.

Wires all agent nodes into the sequential chain described in ADR-003 and ADR-005.
Compiled once at startup via build_graph(); shared as a module-level singleton.

Chain:
  check_cache → [END on hit]
              → refiner
              → text_to_cypher
              → text_to_sql
              → python_executor  [only if requires_solver=True]
              → validator
              → reflection       [on pass OR retry exhaustion]
              → refiner          [on failure, retry_count < max_retries]
              → write_cache
              → END

Cache key format:
  user:{user_id}:{sha256(normalized_question + "|" + sorted_roles)}
"""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from langgraph.graph import END, StateGraph

import finance_analytics.connectors as conn
from finance_analytics.agents.chain_executor import (
    python_executor_node,
    text_to_cypher_node,
    text_to_sql_node,
)
from finance_analytics.agents.reflection import reflection_node
from finance_analytics.agents.refiner import refiner_node
from finance_analytics.agents.validator import validator_node
from finance_analytics.schemas.agent_state import AgentState
from finance_analytics.tools.cache_key import build_cache_key

_QUERY_CACHE_TTL = 300  # 5 minutes


# ── Cache nodes ────────────────────────────────────────────────────────────────

async def check_cache_node(state: AgentState) -> dict:
    """Check Redis for a cached answer. Sets state.cached=True on hit."""
    redis = conn.get_redis()
    key = build_cache_key(state["user_id"], state["question"], state.get("user_roles", []))
    cached = await redis.get(key)
    if cached:
        return {"answer": json.loads(cached), "cached": True}
    return {"cached": False}


async def write_cache_node(state: AgentState) -> dict:
    """Write the final answer to Redis. No-op if already cached or no answer."""
    if state.get("cached") or not state.get("answer"):
        return {}
    redis = conn.get_redis()
    key = build_cache_key(state["user_id"], state["question"], state.get("user_roles", []))
    await redis.setex(key, _QUERY_CACHE_TTL, json.dumps(state["answer"], default=str))
    return {}


# ── Routing functions ──────────────────────────────────────────────────────────

def _route_after_cache(state: AgentState) -> str:
    return END if state.get("cached") else "refiner"


def _route_after_sql(state: AgentState) -> str:
    refiner_output = state.get("refiner_output")
    if refiner_output and refiner_output.requires_solver:
        return "python_executor"
    return "validator"


def _route_after_validator(state: AgentState) -> str:
    validator_output = state.get("validator_output")
    if validator_output and validator_output.passed:
        return "reflection"

    retry_count: int = state.get("retry_count", 0)
    refiner_output = state.get("refiner_output")
    max_retries = refiner_output.max_retries if refiner_output else 2

    if retry_count <= max_retries:
        return "refiner"
    return "reflection"  # exhausted — reflection returns confidence=0.0


# ── Graph compilation ──────────────────────────────────────────────────────────

def _build_graph() -> Any:
    workflow: StateGraph = StateGraph(AgentState)

    workflow.add_node("check_cache", check_cache_node)
    workflow.add_node("refiner", refiner_node)
    workflow.add_node("text_to_cypher", text_to_cypher_node)
    workflow.add_node("text_to_sql", text_to_sql_node)
    workflow.add_node("python_executor", python_executor_node)
    workflow.add_node("validator", validator_node)
    workflow.add_node("reflection", reflection_node)
    workflow.add_node("write_cache", write_cache_node)

    workflow.set_entry_point("check_cache")

    workflow.add_conditional_edges("check_cache", _route_after_cache)

    workflow.add_edge("refiner", "text_to_cypher")
    workflow.add_edge("text_to_cypher", "text_to_sql")

    workflow.add_conditional_edges("text_to_sql", _route_after_sql)

    workflow.add_edge("python_executor", "validator")

    workflow.add_conditional_edges("validator", _route_after_validator)

    workflow.add_edge("reflection", "write_cache")
    workflow.add_edge("write_cache", END)

    return workflow.compile()


@lru_cache(maxsize=1)
def get_graph() -> Any:
    """Return the compiled LangGraph (singleton — built once at first call)."""
    return _build_graph()


async def run_query(
    question: str,
    user_id: str,
    user_roles: list[str],
) -> AgentState:
    """Entry point for the API layer. Returns the final AgentState."""
    initial: AgentState = {
        "question": question,
        "user_id": user_id,
        "user_roles": user_roles,
        "retry_count": 0,
        "context_notes": [],
        "cached": False,
    }
    return await get_graph().ainvoke(initial)
