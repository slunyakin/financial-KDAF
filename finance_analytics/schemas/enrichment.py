from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class EnrichmentReportRequest(BaseModel):
    description: str = Field(min_length=1)
    affected_question: str | None = None


class EnrichmentReportResponse(BaseModel):
    task_id: str
    status: str


class EnrichmentTaskItem(BaseModel):
    task_id: str
    question_text: str
    confidence_score: float | None = None
    source: str
    status: str
    submitted_by: str | None = None
    created_at: datetime


class EnrichmentTasksResponse(BaseModel):
    api_version: Literal["1"] = "1"
    items: list[EnrichmentTaskItem]
    total: int
