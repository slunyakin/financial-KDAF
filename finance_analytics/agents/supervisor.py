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
from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Any

from langgraph.graph import END, StateGraph

import finance_analytics.connectors as conn
from finance_analytics.agents.chain_executor import (
    python_executor_node,
    text_to_cypher_node,
    text_to_sql_node,
)
from finance_analytics.agents.refiner import refiner_node
from finance_analytics.agents.reflection import reflection_node
from finance_analytics.agents.validator import validator_node
from finance_analytics.schemas.agent_state import AgentState
from finance_analytics.schemas.stream_events import ErrorEvent, NodeDoneEvent, ResultEvent, StreamEvent
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


# ── Streaming ──────────────────────────────────────────────────────────────────

_STREAM_NODES = frozenset({
    "check_cache", "refiner", "text_to_cypher", "text_to_sql",
    "python_executor", "validator", "reflection", "write_cache",
})


def _node_event_summary(node_name: str, update: dict) -> str:
    """Return a human-readable one-liner for a completed graph node."""
    if node_name == "check_cache":
        return "cache hit" if update.get("cached") else "cache miss"

    if node_name == "refiner":
        ro = update.get("refiner_output")
        if ro:
            n = len(ro.domain_terms)
            solver = "solver required" if ro.requires_solver else "no solver"
            return f"{n} domain term(s) identified; {solver}"
        return "question refined"

    if node_name == "text_to_cypher":
        ctx = update.get("cypher_context")
        if ctx:
            return (
                f"{len(ctx.business_rules)} rule(s), "
                f"{len(ctx.known_anomalies)} anomaly/ies, "
                f"{len(ctx.concepts)} concept(s) from KG"
            )
        return "KG context fetched"

    if node_name == "text_to_sql":
        sql = update.get("sql_result")
        if sql:
            return f"{sql.row_count} row(s) in {sql.execution_ms}ms"
        return "SQL executed"

    if node_name == "python_executor":
        return "solver executed" if update.get("python_result") else "solver skipped"

    if node_name == "validator":
        vo = update.get("validator_output")
        if vo:
            if vo.passed:
                return "passed"
            issues_preview = "; ".join(vo.issues[:2])
            return f"failed: {issues_preview}"
        return "validated"

    if node_name == "reflection":
        ro = update.get("reflection_output")
        if ro:
            return f"confidence {ro.confidence_score:.0%}"
        return "reflected"

    if node_name == "write_cache":
        return "answer cached"

    return node_name


async def run_query_stream(
    question: str,
    user_id: str,
    user_roles: list[str],
) -> AsyncIterator[StreamEvent]:
    """Yield stream events as the agent chain progresses.

    Emits a NodeDoneEvent after each pipeline stage completes, then a single
    ResultEvent with the final answer. On unhandled error, emits ErrorEvent.

    Uses LangGraph astream(stream_mode="updates") which yields
    {node_name: state_update_dict} after each node completes.
    """
    initial: AgentState = {
        "question": question,
        "user_id": user_id,
        "user_roles": user_roles,
        "retry_count": 0,
        "context_notes": [],
        "cached": False,
    }
    graph = get_graph()
    state: dict = dict(initial)

    try:
        async for update in graph.astream(initial, stream_mode="updates"):
            for node_name, node_update in update.items():
                state.update(node_update)
                if node_name in _STREAM_NODES:
                    yield NodeDoneEvent(
                        node=node_name,
                        summary=_node_event_summary(node_name, node_update),
                    )

        reflection = state.get("reflection_output")
        answer_meta = state.get("answer") or {}
        confidence_score: float = (
            answer_meta.get("confidence_score", 0.0)
            if isinstance(answer_meta, dict)
            else 0.0
        )
        refiner_out = state.get("refiner_output")

        yield ResultEvent(
            summary=reflection.reasoning if reflection else "No answer produced.",
            citations=reflection.citations if reflection else [],
            confidence_score=confidence_score,
            requires_solver=refiner_out.requires_solver if refiner_out else False,
            low_confidence=confidence_score < 0.7,
            enrichment_task_id=(
                answer_meta.get("enrichment_task_id")
                if isinstance(answer_meta, dict)
                else None
            ),
            cached=state.get("cached", False),
        )

    except Exception as exc:  # noqa: BLE001
        yield ErrorEvent(message=str(exc))
