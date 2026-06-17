from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Active data lake connector — selects which DataLakeConnector implementation to use
    DATA_LAKE_ENGINE: str = "postgres"

    # Neo4j (Enterprise Edition required — Community Edition caps connections below 200)
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "neo4j"
    NEO4J_MAX_POOL_SIZE: int = 200

    # Postgres demo connector (asyncpg)
    POSTGRES_DSN: str = "postgresql://postgres:postgres@localhost:5432/financial_kdaf"
    POSTGRES_MAX_POOL_SIZE: int = 50

    # Redshift production connector (asyncpg — PostgreSQL wire protocol on port 5439)
    # DSN must include sslmode=require for production clusters.
    REDSHIFT_DSN: str = ""
    REDSHIFT_MAX_POOL_SIZE: int = 200
    REDSHIFT_CONNECTION_TIMEOUT: float = 5.0

    # Snowflake production connector (sync driver, thread-pool dispatched)
    # pool_size should be ≤ warehouse MAX_CONCURRENCY_LEVEL (default 8 per cluster).
    SNOWFLAKE_ACCOUNT: str = ""       # e.g. abc12345.us-east-1
    SNOWFLAKE_USER: str = ""
    SNOWFLAKE_PASSWORD: str = ""
    SNOWFLAKE_DATABASE: str = ""
    SNOWFLAKE_SCHEMA: str = "PUBLIC"
    SNOWFLAKE_WAREHOUSE: str = ""
    SNOWFLAKE_ROLE: str = ""          # optional; uses user's default role if empty
    SNOWFLAKE_POOL_SIZE: int = 10

    # Redis
    REDIS_URL: str = "redis://localhost:6379"

    # JWT — HS256; change JWT_SECRET in production
    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_SECONDS: int = 86400  # 24 h

    # Users — semicolon-separated list of "username:password:role1,role2"
    # Example: KDAF_USERS=alice:secret:analyst;bob:secret2:knowledge_engineer
    KDAF_USERS: str = ""

    # Anthropic API key — required for all LLM calls
    ANTHROPIC_API_KEY: str = ""

    # LLM — default to latest capable model; override per deployment
    LLM_MODEL: str = "claude-sonnet-4-6"
    LLM_TEMPERATURE: float = 0.0

    # PythonExecutor subprocess timeout
    SOLVER_TIMEOUT_SECONDS: float = 30.0

    model_config = {"env_file": ".env", "case_sensitive": True}


@lru_cache
def get_settings() -> Settings:
    return Settings()
