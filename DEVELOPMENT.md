# Local Development Setup

## Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Python | 3.11+ | `python3 --version` |
| Docker Desktop | any recent | must be running |
| Anthropic API key | — | `sk-ant-...` |

---

## 1. Clone and create virtual environment

```bash
git clone <repo-url>
cd financial-KDAF

python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

For Snowflake support (optional):
```bash
pip install -e ".[dev,snowflake]"
```

---

## 2. Configure environment

```bash
cp .env.example .env
```

Open `.env` and set the required value:

```dotenv
ANTHROPIC_API_KEY=sk-ant-...    # required — get from console.anthropic.com
```

Everything else works as-is for local dev. The demo data lake is Postgres (`DATA_LAKE_ENGINE=postgres`).

---

## 3. Start infrastructure

```bash
docker compose up -d
```

Starts three services:

| Service | Port | Credentials |
|---------|------|-------------|
| Neo4j (Bolt) | 7687 | neo4j / neo4jpassword |
| Neo4j Browser | 7474 | same |
| Postgres | 5432 | postgres / postgres, db: financial_kdaf |
| Redis | 6379 | no auth |

Wait for all services to be healthy (~30s for Neo4j on first start):

```bash
docker compose ps
```

> The `app` service in `docker-compose.yml` is in the `full` profile and intentionally excluded from the default `up`. Run the app directly (step 5).

---

## 4. Seed the knowledge graph

Postgres auto-seeds on first container start via `scripts/postgres_seed.sql`. Neo4j requires a one-time manual seed:

```bash
docker exec -i $(docker compose ps -q neo4j) \
  cypher-shell -u neo4j -p neo4jpassword \
  < scripts/neo4j_seed.cypher
```

To repopulate Table/Column nodes in Neo4j from the Postgres schema:

```bash
# Preview what would be written (no DB writes)
python -m finance_analytics.tools.ingest_schema --dry-run

# Apply
python -m finance_analytics.tools.ingest_schema
```

---

## 5. Run the application

```bash
source .venv/bin/activate
uvicorn finance_analytics.main:app --reload --port 8000
```

Verify it's up:

```bash
curl http://localhost:8000/health
```

The API is available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

---

## 6. Run tests

```bash
# Unit tests — no infrastructure required, ~0.3s
pytest tests/unit/ -q

# Integration tests — requires docker compose up + seeded Neo4j
pytest tests/integration/ -v
```

---

## 7. Lint and type-check

```bash
ruff check finance_analytics/ tests/   # linter
ruff check --fix finance_analytics/ tests/   # auto-fix safe issues
mypy finance_analytics/                # type checker
```

---

## Switching data lake engines

Edit `DATA_LAKE_ENGINE` in `.env` and uncomment the matching block:

```dotenv
# Redshift
DATA_LAKE_ENGINE=redshift
REDSHIFT_DSN=postgresql://user:password@cluster.region.redshift.amazonaws.com:5439/dbname?sslmode=require

# Snowflake (also requires: pip install -e ".[snowflake]")
DATA_LAKE_ENGINE=snowflake
SNOWFLAKE_ACCOUNT=abc12345.us-east-1
SNOWFLAKE_USER=svc_kdaf
SNOWFLAKE_PASSWORD=...
SNOWFLAKE_DATABASE=PROD_DW
SNOWFLAKE_WAREHOUSE=KDAF_WH
```

---

## Stopping / resetting

```bash
# Stop services, keep data volumes
docker compose down

# Stop and wipe all data (full reset)
docker compose down -v
```

After a full reset, repeat step 4 (seed Neo4j).

---

## Troubleshooting

**Neo4j takes too long to start** — first pull of `neo4j:5.18-enterprise` can take a few minutes. Watch with `docker compose logs -f neo4j`.

**`ModuleNotFoundError: No module named 'finance_analytics'`** — activate the venv (`source .venv/bin/activate`) and install in editable mode (`pip install -e ".[dev]"`).

**Port already in use** — check what's occupying the port: `lsof -i :7687` (or 5432 / 6379 / 8000). Stop the conflicting process or change the port mapping in `docker-compose.yml`.

**`ANTHROPIC_API_KEY` not set** — the app will start but all agent calls will fail with an auth error. Set it in `.env` before running `uvicorn`.
