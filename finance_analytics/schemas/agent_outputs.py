from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class RefinerOutput(BaseModel):
    refined_question: str
    # Always "exploratory" at runtime — Supervisor uses cache-first, always-exploratory routing.
    # Kept for evaluation harness introspection and future analytics.
    query_type: Literal["exploratory"] = "exploratory"
    domain_terms: list[str]
    requires_solver: bool
    max_retries: int = Field(
        description="2 for SQL-only queries; 1 for solver-required queries"
    )


class CypherContextOutput(BaseModel):
    business_rules: list[dict[str, Any]]
    known_anomalies: list[dict[str, Any]]
    concepts: list[dict[str, Any]]
    cypher_used: str


class SQLQueryOutput(BaseModel):
    sql: str
    rows: list[dict[str, Any]]
    row_count: int
    execution_ms: int


class PythonExecutorOutput(BaseModel):
    code: str
    result: Any
    stdout: str
    execution_ms: int


class ValidatorOutput(BaseModel):
    passed: bool
    issues: list[str]
    # Keys: "graph_coverage", "sql_pass", "reflection_agree"
    confidence_components: dict[str, float]


class Citation(BaseModel):
    source_table: str | None = None
    column: str | None = None
    business_rule_id: str | None = None
    excerpt: str
    confidence: float


class ReflectionOutput(BaseModel):
    addresses_question: bool
    reasoning: str
    citations: list[Citation]
    # Composite score: 0.4×graph_coverage + 0.4×sql_pass + 0.2×reflection_agree
    # threshold=0.7; below threshold triggers EnrichmentTask write
    confidence_score: float
