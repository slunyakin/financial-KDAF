#!/usr/bin/env bash
# Smoke test: verify all Docker Compose services are healthy and seeds are applied.
# Usage:
#   ./scripts/smoke_test.sh            # checks all services
#   ./scripts/smoke_test.sh --seed     # also applies Neo4j seed (Postgres auto-seeds via initdb.d)
set -euo pipefail

POSTGRES_DSN="${POSTGRES_DSN:-postgresql://postgres:postgres@localhost:5432/financial_kdaf}"
NEO4J_URI="${NEO4J_URI:-bolt://localhost:7687}"
NEO4J_USER="${NEO4J_USER:-neo4j}"
NEO4J_PASSWORD="${NEO4J_PASSWORD:-neo4jpassword}"
REDIS_URL="${REDIS_URL:-redis://localhost:6379}"
APP_URL="${APP_URL:-http://localhost:8000}"
SEED_NEO4J=false

for arg in "$@"; do
  [[ "$arg" == "--seed" ]] && SEED_NEO4J=true
done

PASS=0
FAIL=0

check() {
  local name="$1"; local cmd="$2"
  if eval "$cmd" &>/dev/null; then
    echo "  [PASS] $name"
    ((PASS+=1))
  else
    echo "  [FAIL] $name"
    ((FAIL+=1))
  fi
}

echo "=== financial-KDAF smoke test ==="
echo

echo "── Infrastructure ──"
check "Postgres reachable" "pg_isready -d '$POSTGRES_DSN' 2>/dev/null || psql '$POSTGRES_DSN' -c 'SELECT 1' -t"
check "Redis reachable"    "redis-cli -u '$REDIS_URL' ping | grep -q PONG"
_NEO4J_HOST="${NEO4J_URI#bolt://}"; _NEO4J_HOST="${_NEO4J_HOST%%:*}"
_NEO4J_PORT="${NEO4J_URI##*:}"
check "Neo4j Bolt reachable" "nc -z '$_NEO4J_HOST' '$_NEO4J_PORT' 2>/dev/null"

echo
echo "── Postgres seed (TC1-TC5) ──"
check "revenue rows"            "psql '$POSTGRES_DSN' -t -c 'SELECT COUNT(*) FROM revenue' | grep -qv '^$\\|^ 0$'"
check "cogs rows"               "psql '$POSTGRES_DSN' -t -c 'SELECT COUNT(*) FROM cogs' | grep -qv '^$\\|^ 0$'"
check "contracts rows"          "psql '$POSTGRES_DSN' -t -c 'SELECT COUNT(*) FROM contracts' | grep -qv '^$\\|^ 0$'"
check "health_scores rows"      "psql '$POSTGRES_DSN' -t -c 'SELECT COUNT(*) FROM health_scores' | grep -qv '^$\\|^ 0$'"
check "vendor_costs rows"       "psql '$POSTGRES_DSN' -t -c 'SELECT COUNT(*) FROM vendor_costs' | grep -qv '^$\\|^ 0$'"
check "project_cashflows rows"  "psql '$POSTGRES_DSN' -t -c 'SELECT COUNT(*) FROM project_cashflows' | grep -qv '^$\\|^ 0$'"
check "labor_costs rows"        "psql '$POSTGRES_DSN' -t -c 'SELECT COUNT(*) FROM labor_costs' | grep -qv '^$\\|^ 0$'"
check "job_requisitions rows"   "psql '$POSTGRES_DSN' -t -c 'SELECT COUNT(*) FROM job_requisitions' | grep -qv '^$\\|^ 0$'"

if $SEED_NEO4J; then
  echo
  echo "── Applying Neo4j seed ──"
  if command -v cypher-shell &>/dev/null; then
    cypher-shell -a "$NEO4J_URI" -u "$NEO4J_USER" -p "$NEO4J_PASSWORD" \
      --file scripts/neo4j_seed.cypher && echo "  [OK] neo4j_seed.cypher applied"
  else
    echo "  [SKIP] cypher-shell not found; apply scripts/neo4j_seed.cypher manually or via Neo4j Browser"
  fi
fi

echo
echo "── Neo4j KG nodes ──"
neo4j_count() {
  local label="$1"
  cypher-shell -a "$NEO4J_URI" -u "$NEO4J_USER" -p "$NEO4J_PASSWORD" \
    --format plain "MATCH (n:$label) RETURN count(n) AS c" 2>/dev/null | tail -1
}

if command -v cypher-shell &>/dev/null; then
  check "Segment nodes"        "[[ $(neo4j_count Segment) -ge 1 ]]"
  check "BusinessRule nodes"   "[[ $(neo4j_count BusinessRule) -ge 1 ]]"
  check "Covenant node"        "[[ $(neo4j_count Covenant) -ge 1 ]]"
  check "CostOfCapital node"   "[[ $(neo4j_count CostOfCapital) -ge 1 ]]"
  check "Project nodes"        "[[ $(neo4j_count Project) -ge 2 ]]"
  check "LaborContract nodes"  "[[ $(neo4j_count LaborContract) -ge 2 ]]"
  check "MacroFeed node"       "[[ $(neo4j_count MacroFeed) -ge 1 ]]"
  check "RampPenalty node"     "[[ $(neo4j_count RampPenalty) -ge 1 ]]"
else
  echo "  [SKIP] cypher-shell not found; skipping Neo4j node checks"
fi

echo
echo "── App health (only if running) ──"
if curl -sf "$APP_URL/health" &>/dev/null; then
  check "App /health returns ok" "curl -sf '$APP_URL/health' | grep -q '\"ok\"'"
else
  echo "  [SKIP] App not running (start with: docker compose --profile full up)"
fi

echo
if [[ $FAIL -eq 0 ]]; then
  echo "Result: ALL $PASS checks passed."
  exit 0
else
  echo "Result: $PASS passed, $FAIL FAILED."
  exit 1
fi
