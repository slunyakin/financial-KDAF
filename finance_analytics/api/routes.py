"""FastAPI route definitions.

v1 endpoints:
  POST /api/v1/query         — submit NL question; returns QueryResponse
  POST /api/v1/query/stream  — same, streamed as SSE (api_version: "2")
  GET  /api/v1/history       — list the authenticated user's past questions

Response envelope is versioned (api_version: "1") so streaming can be
added as api_version: "2" without breaking v1 callers (CEO plan decision D8).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import finance_analytics.connectors as conn
from finance_analytics.agents.supervisor import run_query, run_query_stream
from finance_analytics.api.auth import get_current_user
from finance_analytics.schemas.query_response import (
    QueryHistoryResponse,
    QueryResponse,
    QuestionHistoryItem,
)

router = APIRouter(prefix="/api/v1")


class QueryRequest(BaseModel):
    question: str


@router.post("/query", response_model=QueryResponse)
async def query_endpoint(
    request: QueryRequest,
    current_user: tuple[str, list[str]] = Depends(get_current_user),
) -> QueryResponse:
    """Submit a natural language question to the analytics agent chain.

    Auth: Bearer JWT with roles claim.
    Returns: QueryResponse with summary, citations, confidence_score.
    """
    user_id, user_roles = current_user
    final_state = await run_query(request.question, user_id, user_roles)

    reflection = final_state.get("reflection_output")
    answer_meta = final_state.get("answer") or {}

    confidence_score: float = answer_meta.get("confidence_score", 0.0)
    enrichment_task_id: str | None = answer_meta.get("enrichment_task_id")

    return QueryResponse(
        api_version="1",
        summary=reflection.reasoning if reflection else "No answer produced.",
        citations=reflection.citations if reflection else [],
        confidence_score=confidence_score,
        requires_solver=final_state.get("refiner_output", {}).requires_solver
        if final_state.get("refiner_output")
        else False,
        low_confidence=confidence_score < 0.7,
        enrichment_task_id=enrichment_task_id,
    )


@router.post("/query/stream")
async def query_stream_endpoint(
    request: QueryRequest,
    current_user: tuple[str, list[str]] = Depends(get_current_user),
) -> StreamingResponse:
    """Stream agent chain progress as Server-Sent Events (SSE).

    Each SSE line is: data: <json>\\n\\n

    Event shapes (all carry api_version: "2"):
      {"event": "node_done", "node": "<name>", "summary": "<one-liner>"}
      {"event": "result",    "summary": "...", "citations": [...], "confidence_score": 0.9, ...}
      {"event": "error",     "message": "..."}

    Nodes emitted in chain order: check_cache → refiner → text_to_cypher →
    text_to_sql → [python_executor] → validator → reflection → write_cache
    """
    user_id, user_roles = current_user

    async def _generate():
        async for event in run_query_stream(request.question, user_id, user_roles):
            yield f"data: {event.model_dump_json()}\n\n"

    return StreamingResponse(_generate(), media_type="text/event-stream")


_HISTORY_CYPHER = """\
MATCH (q:Question {user_id: $user_id})
RETURN q.question_text      AS question_text,
       q.summary             AS summary,
       q.confidence_score    AS confidence_score,
       q.low_confidence      AS low_confidence,
       q.enrichment_task_id  AS enrichment_task_id,
       q.created_at          AS created_at
ORDER BY q.created_at DESC
LIMIT $limit
"""

_HISTORY_COUNT_CYPHER = "MATCH (q:Question {user_id: $user_id}) RETURN count(q) AS total"


@router.get("/history", response_model=QueryHistoryResponse)
async def history_endpoint(
    current_user: tuple[str, list[str]] = Depends(get_current_user),
    limit: int = Query(default=20, ge=1, le=100),
) -> QueryHistoryResponse:
    """Return the authenticated user's past questions, newest first.

    Auth: Bearer JWT.
    Query params:
      limit — number of items to return (1–100, default 20)
    """
    user_id, _ = current_user
    neo4j = conn.get_neo4j()

    async with neo4j.driver.session() as session:
        result = await session.run(_HISTORY_CYPHER, user_id=user_id, limit=limit)
        records = await result.data()

        count_result = await session.run(_HISTORY_COUNT_CYPHER, user_id=user_id)
        count_record = await count_result.single()
        total: int = count_record["total"] if count_record else 0

    items = [
        QuestionHistoryItem(
            question_text=r["question_text"],
            summary=r["summary"] or "",
            confidence_score=r["confidence_score"] or 0.0,
            low_confidence=r["low_confidence"] or False,
            enrichment_task_id=r["enrichment_task_id"],
            created_at=r["created_at"],
        )
        for r in records
    ]
    return QueryHistoryResponse(items=items, total=total)
