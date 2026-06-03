from abc import ABC, abstractmethod

from finance_analytics.schemas.agent_outputs import SQLQueryOutput


class DataLakeConnector(ABC):
    """Abstract base for all data lake / warehouse connectors.

    Each implementation declares its SQL dialect string; execution/sql.py injects
    it into the Text-to-SQL agent's system prompt at request time. No Postgres-specific
    SQL may appear in the agent chain — dialect is always connector-owned.
    """

    dialect: str  # e.g. "postgresql", "snowflake", "bigquery", "duckdb"

    @abstractmethod
    async def execute(self, query: str, params: dict | None = None) -> SQLQueryOutput:
        """Execute a SELECT query and return typed results.

        Implementations must enforce the SELECT-only guard themselves OR rely on
        execution/sql.py::assert_select_only() being called before this method.
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """Release connection pool resources gracefully."""
        ...
