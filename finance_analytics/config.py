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

    # Redis
    REDIS_URL: str = "redis://localhost:6379"

    # JWT — HS256; change JWT_SECRET in production
    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"

    # PythonExecutor subprocess timeout
    SOLVER_TIMEOUT_SECONDS: float = 30.0

    model_config = {"env_file": ".env", "case_sensitive": True}


@lru_cache
def get_settings() -> Settings:
    return Settings()
