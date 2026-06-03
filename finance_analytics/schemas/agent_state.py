from __future__ import annotations

from typing import Any, List, Optional
from typing_extensions import TypedDict

from finance_analytics.schemas.agent_outputs import (
    CypherContextOutput,
    PythonExecutorOutput,
    ReflectionOutput,
    RefinerOutput,
    SQLQueryOutput,
    ValidatorOutput,
)


class AgentState(TypedDict, total=False):
    # Input fields — set by the API layer before entering the graph
    question: str
    user_id: str
    user_roles: List[str]

    # Pipeline outputs — set by each agent node in sequence
    refiner_output: Optional[RefinerOutput]
    cypher_context: Optional[CypherContextOutput]
    sql_result: Optional[SQLQueryOutput]
    python_result: Optional[PythonExecutorOutput]
    validator_output: Optional[ValidatorOutput]
    reflection_output: Optional[ReflectionOutput]

    # Retry control
    retry_count: int
    context_notes: List[str]   # accumulated validator issue strings fed back to Refiner

    # Terminal output fields
    answer: Optional[Any]
    cached: bool
