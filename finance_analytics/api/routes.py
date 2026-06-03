"""FastAPI route definitions.

v1 endpoints:
  POST /api/v1/query  — submit NL question; returns QueryResponse

Response envelope is versioned (api_version: "1") so streaming can be
added as api_version: "2" without breaking v1 callers (CEO plan decision D8).

The agent chain (LangGraph StateGraph) is not yet wired — raises NotImplementedError
until agents/ is implemented. The endpoint contract is defined here first so the
evaluation harness and integration tests can reference the correct schema.
"""
from __future__ import annotations

from typing import List, Tuple

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from finance_analytics.api.auth import get_current_user
from finance_analytics.schemas.query_response import QueryResponse

router = APIRouter(prefix="/api/v1")


class QueryRequest(BaseModel):
    question: str


@router.post("/query", response_model=QueryResponse)
async def query_endpoint(
    request: QueryRequest,
    current_user: Tuple[str, List[str]] = Depends(get_current_user),
) -> QueryResponse:
    """Submit a natural language question to the analytics agent chain.

    Auth: Bearer JWT with roles claim.
    Returns: QueryResponse with summary, citations, confidence_score.
    """
    user_id, user_roles = current_user  # noqa: F841 — consumed by chain (not yet wired)
    # TODO (T chain): initialise AgentState and run the LangGraph StateGraph
    raise NotImplementedError(
        "Agent chain not yet implemented — implement agents/ then wire here"
    )
