"""FastAPI route definitions.

v1 endpoints:
  POST /api/v1/query                  — submit NL question; returns QueryResponse
  POST /api/v1/query/stream           — same, streamed as SSE (api_version: "2")
  GET  /api/v1/history                — list the authenticated user's past questions
  POST /api/v1/enrichment/report      — submit a knowledge gap report (EnrichmentTask)
  GET  /api/v1/enrichment/tasks       — list EnrichmentTask nodes (knowledge_engineer role)

Response envelope is versioned (api_version: "1") so streaming can be
added as api_version: "2" without breaking v1 callers (CEO plan decision D8).
"""
from __future__ import annotations

import hashlib
import time

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import finance_analytics.connectors as conn
from finance_analytics.agents.supervisor import run_query, run_query_stream
from finance_analytics.api.auth import get_current_user, require_role
from finance_analytics.schemas.enrichment import (
    EnrichmentReportRequest,
    EnrichmentReportResponse,
    EnrichmentTaskItem,
    EnrichmentTasksResponse,
)
from finance_analytics.schemas.query_response import (
    QueryHistoryResponse,
    QueryResponse,
    QuestionHistoryItem,
)

router = APIRouter(prefix="/api/v1")


def _coerce_neo4j_dt(value):
    """Convert neo4j.time.DateTime to Python datetime; pass through anything else."""
    return value.to_native() if hasattr(value, "to_native") else value


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
            created_at=_coerce_neo4j_dt(r["created_at"]),
        )
        for r in records
    ]
    return QueryHistoryResponse(items=items, total=total)


_ENRICHMENT_REPORT_TTL = 900  # 15-minute idempotency window

_ENRICHMENT_REPORT_CYPHER = """\
MERGE (t:EnrichmentTask {id: $task_id})
ON CREATE SET
  t.question_text     = $description,
  t.missing_context   = [],
  t.status            = 'open',
  t.source            = 'manual',
  t.submitted_by      = $user_id,
  t.affected_question = $affected_question,
  t.created_at        = datetime()
RETURN elementId(t) AS element_id
"""

_ENRICHMENT_TASKS_CYPHER = """\
MATCH (t:EnrichmentTask)
WHERE $status = 'all' OR t.status = $status
RETURN elementId(t)   AS task_id,
       t.question_text AS question_text,
       t.confidence_score AS confidence_score,
       t.source        AS source,
       t.status        AS status,
       t.submitted_by  AS submitted_by,
       t.created_at    AS created_at
ORDER BY t.created_at DESC
LIMIT $limit
"""

_ENRICHMENT_TASKS_COUNT_CYPHER = """\
MATCH (t:EnrichmentTask)
WHERE $status = 'all' OR t.status = $status
RETURN count(t) AS total
"""


@router.post("/enrichment/report", response_model=EnrichmentReportResponse)
async def enrichment_report_endpoint(
    request: EnrichmentReportRequest,
    current_user: tuple[str, list[str]] = Depends(get_current_user),
) -> EnrichmentReportResponse:
    """Submit a knowledge gap report as an EnrichmentTask node.

    Auth: any authenticated user.
    """
    user_id, _ = current_user
    task_id = hashlib.sha256(
        f"{user_id}|{request.description}|{int(time.time() // _ENRICHMENT_REPORT_TTL)}"
        .encode()
    ).hexdigest()
    neo4j = conn.get_neo4j()

    async with neo4j.driver.session() as session:
        result = await session.run(
            _ENRICHMENT_REPORT_CYPHER,
            task_id=task_id,
            description=request.description,
            user_id=user_id,
            affected_question=request.affected_question,
        )
        record = await result.single()

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create EnrichmentTask node",
        )
    return EnrichmentReportResponse(task_id=task_id)


@router.get("/enrichment/tasks", response_model=EnrichmentTasksResponse)
async def enrichment_tasks_endpoint(
    current_user: tuple[str, list[str]] = Depends(require_role("knowledge_engineer")),
    status: str = Query(default="open", pattern="^(open|resolved|all)$"),
    limit: int = Query(default=50, ge=1, le=200),
) -> EnrichmentTasksResponse:
    """List EnrichmentTask nodes. Requires knowledge_engineer role.

    Query params:
      status — open | resolved | all (default: open)
      limit  — 1–200 (default 50)
    """
    neo4j = conn.get_neo4j()

    async with neo4j.driver.session() as session:
        result = await session.run(
            _ENRICHMENT_TASKS_CYPHER, status=status, limit=limit
        )
        records = await result.data()

        count_result = await session.run(_ENRICHMENT_TASKS_COUNT_CYPHER, status=status)
        count_record = await count_result.single()
        total: int = count_record["total"] if count_record else 0

    items = [
        EnrichmentTaskItem(
            task_id=r["task_id"],
            question_text=r["question_text"] or "",
            confidence_score=r["confidence_score"],
            source=r["source"] or "unknown",
            status=r["status"] or "open",
            submitted_by=r["submitted_by"],
            created_at=_coerce_neo4j_dt(r["created_at"]),
        )
        for r in records
    ]
    return EnrichmentTasksResponse(items=items, total=total)


_ENRICHMENT_TASK_BY_ID_CYPHER = """\
MATCH (t:EnrichmentTask {id: $task_id})
RETURN elementId(t) AS task_id,
       t.question_text  AS question_text,
       t.confidence_score AS confidence_score,
       t.source         AS source,
       t.status         AS status,
       t.submitted_by   AS submitted_by,
       t.created_at     AS created_at
"""


@router.get("/enrichment/tasks/{task_id}", response_model=EnrichmentTaskItem)
async def get_enrichment_task_endpoint(
    task_id: str,
    current_user: tuple[str, list[str]] = Depends(require_role("knowledge_engineer")),
) -> EnrichmentTaskItem:
    """Fetch a single EnrichmentTask by ID. Requires knowledge_engineer role."""
    neo4j = conn.get_neo4j()
    async with neo4j.driver.session() as session:
        result = await session.run(_ENRICHMENT_TASK_BY_ID_CYPHER, task_id=task_id)
        record = await result.single()

    if record is None:
        raise HTTPException(status_code=404, detail="Task not found")

    return EnrichmentTaskItem(
        task_id=record["task_id"],
        question_text=record["question_text"] or "",
        confidence_score=record["confidence_score"],
        source=record["source"] or "unknown",
        status=record["status"] or "open",
        submitted_by=record["submitted_by"],
        created_at=_coerce_neo4j_dt(record["created_at"]),
    )
