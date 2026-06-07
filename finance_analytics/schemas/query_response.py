from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from finance_analytics.schemas.agent_outputs import Citation


class QueryResponse(BaseModel):
    api_version: Literal["1"] = "1"
    summary: str
    citations: list[Citation]
    confidence_score: float = Field(ge=0.0, le=1.0)
    requires_solver: bool
    low_confidence: bool = Field(
        description="True when confidence_score < 0.7; EnrichmentTask has been written"
    )
    enrichment_task_id: str | None = Field(
        default=None,
        description="Neo4j EnrichmentTask node ID written on low-confidence answers",
    )


class QuestionHistoryItem(BaseModel):
    question_text: str
    summary: str
    confidence_score: float = Field(ge=0.0, le=1.0)
    low_confidence: bool
    enrichment_task_id: str | None = None
    created_at: datetime


class QueryHistoryResponse(BaseModel):
    api_version: Literal["1"] = "1"
    items: list[QuestionHistoryItem]
    total: int
