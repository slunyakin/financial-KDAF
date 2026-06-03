from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class RefinerOutput(BaseModel):
    refined_question: str
    # Always "exploratory" at runtime — Supervisor uses cache-first, always-exploratory routing.
    # Kept for evaluation harness introspection and future analytics.
    query_type: Literal["exploratory"] = "exploratory"
    domain_terms: List[str]
    requires_solver: bool
    max_retries: int = Field(
        description="2 for SQL-only queries; 1 for solver-required queries"
    )


class CypherContextOutput(BaseModel):
    business_rules: List[Dict[str, Any]]
    known_anomalies: List[Dict[str, Any]]
    concepts: List[Dict[str, Any]]
    cypher_used: str


class SQLQueryOutput(BaseModel):
    sql: str
    rows: List[Dict[str, Any]]
    row_count: int
    execution_ms: int


class PythonExecutorOutput(BaseModel):
    code: str
    result: Any
    stdout: str
    execution_ms: int


class ValidatorOutput(BaseModel):
    passed: bool
    issues: List[str]
    # Keys: "graph_coverage", "sql_pass", "reflection_agree"
    confidence_components: Dict[str, float]


class Citation(BaseModel):
    source_table: Optional[str] = None
    column: Optional[str] = None
    business_rule_id: Optional[str] = None
    excerpt: str
    confidence: float


class ReflectionOutput(BaseModel):
    addresses_question: bool
    reasoning: str
    citations: List[Citation]
    # Composite score: 0.4×graph_coverage + 0.4×sql_pass + 0.2×reflection_agree
    # threshold=0.7; below threshold triggers EnrichmentTask write
    confidence_score: float
