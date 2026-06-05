from abc import ABC, abstractmethod

from finance_analytics.schemas.agent_outputs import SQLQueryOutput


class DataLakeConnector(ABC):
    """Abstract base for all data lake / warehouse connectors.

    Each implementation declares its SQL dialect string and dialect_examples;
    execution/sql.py and chain_executor.py inject both into the Text-to-SQL
    agent's system prompt at request time. No Postgres-specific SQL may appear
    in the agent chain — dialect is always connector-owned.
    """

    dialect: str  # e.g. "postgresql", "redshift", "snowflake", "bigquery", "duckdb"

    # Connector-owned examples of dialect-specific patterns (date functions, aggregations,
    # window functions, type casting). Injected into the Text-to-SQL system prompt alongside
    # the schema description to ground SQL generation in engine-specific syntax.
    dialect_examples: dict[str, str] = {}

    @abstractmethod
    async def execute(self, query: str, params: dict | None = None) -> SQLQueryOutput:
        """Execute a SELECT query and return typed results.

        Implementations must enforce the SELECT-only guard themselves OR rely on
        execution/sql.py::assert_select_only() being called before this method.
        """
        ...

    @abstractmethod
    async def schema_description(self) -> str:
        """Return a markdown description of available tables and columns.

        Used by the Text-to-SQL agent to ground SQL generation. Each connector
        produces this from INFORMATION_SCHEMA queries or a static fixture.
        The Postgres demo connector returns the golden dataset schema.
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """Release connection pool resources gracefully."""
        ...
