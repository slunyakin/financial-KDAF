from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class EnrichmentReportRequest(BaseModel):
    description: str = Field(min_length=1, max_length=2000)
    affected_question: str | None = Field(default=None, max_length=500)


class EnrichmentReportResponse(BaseModel):
    api_version: Literal["1"] = "1"
    task_id: str
    status: Literal["open"] = "open"


class EnrichmentTaskItem(BaseModel):
    task_id: str
    question_text: str
    confidence_score: float | None = None
    source: str
    status: Literal["open", "resolved"]
    submitted_by: str | None = None
    created_at: datetime | None = None


class EnrichmentTasksResponse(BaseModel):
    api_version: Literal["1"] = "1"
    items: list[EnrichmentTaskItem]
    total: int
