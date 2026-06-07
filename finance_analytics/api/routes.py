"""FastAPI route definitions.

v1 endpoints:
  POST /api/v1/query  — submit NL question; returns QueryResponse

Response envelope is versioned (api_version: "1") so streaming can be
added as api_version: "2" without breaking v1 callers (CEO plan decision D8).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from finance_analytics.agents.supervisor import run_query, run_query_stream
from finance_analytics.api.auth import get_current_user
from finance_analytics.schemas.query_response import QueryResponse

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
