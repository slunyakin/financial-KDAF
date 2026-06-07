from __future__ import annotations

from typing import Any

from typing_extensions import TypedDict

from finance_analytics.schemas.agent_outputs import (
    CypherContextOutput,
    PythonExecutorOutput,
    RefinerOutput,
    ReflectionOutput,
    SQLQueryOutput,
    ValidatorOutput,
)


class AgentState(TypedDict, total=False):
    # Input fields — set by the API layer before entering the graph
    question: str
    user_id: str
    user_roles: list[str]

    # Pipeline outputs — set by each agent node in sequence
    refiner_output: RefinerOutput | None
    cypher_context: CypherContextOutput | None
    sql_result: SQLQueryOutput | None
    python_result: PythonExecutorOutput | None
    validator_output: ValidatorOutput | None
    reflection_output: ReflectionOutput | None

    # Retry control
    retry_count: int
    context_notes: list[str]   # accumulated validator issue strings fed back to Refiner

    # Terminal output fields
    answer: Any | None
    cached: bool
