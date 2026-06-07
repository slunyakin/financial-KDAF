from __future__ import annotations

from typing import Literal, Union

from pydantic import BaseModel, Field

from finance_analytics.schemas.agent_outputs import Citation


class NodeDoneEvent(BaseModel):
    event: Literal["node_done"] = "node_done"
    api_version: Literal["2"] = "2"
    node: str
    summary: str


class ResultEvent(BaseModel):
    event: Literal["result"] = "result"
    api_version: Literal["2"] = "2"
    summary: str
    citations: list[Citation]
    confidence_score: float = Field(ge=0.0, le=1.0)
    requires_solver: bool
    low_confidence: bool
    enrichment_task_id: str | None = None
    cached: bool = False


class ErrorEvent(BaseModel):
    event: Literal["error"] = "error"
    api_version: Literal["2"] = "2"
    message: str


StreamEvent = Union[NodeDoneEvent, ResultEvent, ErrorEvent]
