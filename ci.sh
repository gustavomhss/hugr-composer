#!/usr/bin/env bash
# SKILL-001 Local CI — runs ALL test suites with the same rigor as GitHub Actions.
#
# Usage:
#   cd skills/SKILL-001-fastapi-production
#   ./ci.sh            # full suite (requires Docker for PostgreSQL)
#   ./ci.sh --no-pg    # skip PostgreSQL-dependent suites (faster, no Docker)
#
# Exit 0 = all green, Exit 1 = failures.

set -uo pipefail
# NOTE: NOT using set -e — run_suite handles failures via exit codes.

SKILL_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$SKILL_ROOT"

VENV="${SKILL_ROOT}/.venv"
PY="${VENV}/bin/python"
PYTHONPATH="$SKILL_ROOT"
export PYTHONPATH

export SECRET_KEY="ci-local-secret-key-must-be-at-least-32-chars!!"
export RATE_LIMITING_ENABLED=false
export ENVIRONMENT=local
export MFA_FERNET_KEY="L7gvXDh2v6syV65J0-iwLQMTYbVavNXO2vuXgntcFBo="

NO_PG=false
if [[ "${1:-}" == "--no-pg" ]]; then
    NO_PG=true
fi

# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------
R='\033[31m'
G='\033[32m'
Y='\033[33m'
C='\033[36m'
B='\033[1m'
N='\033[0m'

passed=0
failed=0
skipped=0
results=()

CI_LOG_DIR="${SKILL_ROOT}/.ci-logs"
mkdir -p "$CI_LOG_DIR"

run_suite() {
    local name="$1"
    shift
    local slug
    slug=$(echo "$name" | tr -c '[:alnum:]' '_' | tr -s '_' | sed 's/^_//;s/_$//')
    local log="${CI_LOG_DIR}/${slug}.log"
    printf "${C}▶${N} ${B}%-45s${N} " "$name"
    local t0
    t0=$(date +%s)
    if "$@" > "$log" 2>&1; then
        local elapsed=$(( $(date +%s) - t0 ))
        printf "${G}PASS${N}  (%ds)\n" "$elapsed"
        ((passed++))
        results+=("PASS  $name")
    else
        local elapsed=$(( $(date +%s) - t0 ))
        printf "${R}FAIL${N}  (%ds)\n" "$elapsed"
        # Forensic output: every FAILED line + last 30 lines (summary tail)
        echo "       ── full log: $log"
        grep -E "^FAILED|^ERROR" "$log" | sed 's/^/       /' || true
        echo "       ── tail ──"
        tail -30 "$log" | sed 's/^/       /'
        ((failed++))
        results+=("FAIL  $name")
    fi
}

skip_suite() {
    local name="$1"
    printf "${Y}▶${N} ${B}%-45s${N} ${Y}SKIP${N}  (--no-pg)\n" "$name"
    ((skipped++))
    results+=("SKIP  $name")
}

# ---------------------------------------------------------------------------
# PostgreSQL container management
# ---------------------------------------------------------------------------
PG_CONTAINER="skill001-ci-pg"

start_postgres() {
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${PG_CONTAINER}$"; then
        return 0
    fi
    docker rm -f "$PG_CONTAINER" 2>/dev/null || true
    docker run -d --name "$PG_CONTAINER" \
        -e POSTGRES_USER=skill \
        -e POSTGRES_PASSWORD=skill \
        -e POSTGRES_DB=skill_e2e \
        -p 54329:5432 \
        postgres:16-alpine > /dev/null 2>&1

    # Wait for ready
    local retries=0
    while ! docker exec "$PG_CONTAINER" pg_isready -U skill > /dev/null 2>&1; do
        retries=$((retries + 1))
        if [ $retries -gt 30 ]; then
            echo "PostgreSQL failed to start"
            return 1
        fi
        sleep 1
    done
}

stop_postgres() {
    docker stop "$PG_CONTAINER" > /dev/null 2>&1 || true
    docker rm "$PG_CONTAINER" > /dev/null 2>&1 || true
}

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------
echo ""
echo "=================================================================="
echo "  SKILL-001 Local CI — $(date '+%Y-%m-%d %H:%M:%S')"
echo "  Python: $($PY --version 2>&1)"
echo "  PostgreSQL: $(if $NO_PG; then echo 'SKIPPED'; else echo 'Docker'; fi)"
echo "=================================================================="
echo ""

# ---------------------------------------------------------------------------
# Suite 1: Unit tests
# ---------------------------------------------------------------------------
run_suite "Unit tests (adapt/)" \
    "$PY" -m pytest adapt/ -q --tb=line --no-header

# ---------------------------------------------------------------------------
# Suite 2: Boot individual
# ---------------------------------------------------------------------------
run_suite "Boot individual (100 tools)" \
    "$PY" tests/test_boot.py

# ---------------------------------------------------------------------------
# Suite 3: Property tests
# ---------------------------------------------------------------------------
run_suite "Property tests (123 × 8)" \
    "$PY" tests/property_tests.py

# ---------------------------------------------------------------------------
# Suite 4: SQLite E2E hardcore
# ---------------------------------------------------------------------------
run_suite "SQLite E2E (12 scenarios)" \
    "$PY" tests/test_e2e_hardcore.py

# ---------------------------------------------------------------------------
# Suite 5: Red team
# ---------------------------------------------------------------------------
run_suite "Red team (25 attacks)" \
    "$PY" audit/red_team.py

# ---------------------------------------------------------------------------
# Suite 6: Determinism
# ---------------------------------------------------------------------------
run_suite "Determinism (4 tests)" \
    "$PY" tests/test_determinism.py

# ---------------------------------------------------------------------------
# Suite 7: Benchmark regression (latest_score.json non-regressive)
# ---------------------------------------------------------------------------
run_suite "Benchmark regression (latest_score.json)" \
    "$PY" -c "
import json, pathlib
p = pathlib.Path('benchmarks/latest_score.json')
assert p.exists(), f'{p} missing — run the benchmark first'
data = json.loads(p.read_text())
overall = float(data['overall'])
assert overall >= 30.0, f'benchmark regressed: overall={overall} < 30 floor'
print(f'benchmark overall={overall:.2f} ({data.get(\"methodology\", \"?\")})')
"

# ---------------------------------------------------------------------------
# Suite 8: MCP discovery
# ---------------------------------------------------------------------------
run_suite "MCP discovery (175 tools)" \
    "$PY" -c "
from mcp_tools.server import mcp
from mcp_tools.discovery import discover_and_register
count = discover_and_register(mcp)
assert count >= 105, f'Expected >= 105 tools in catalog, got {count}'
print(f'{count} tools in catalog')
"

# ---------------------------------------------------------------------------
# PostgreSQL-dependent suites
# ---------------------------------------------------------------------------
if $NO_PG; then
    skip_suite "PostgreSQL E2E (8 scenarios)"
    skip_suite "Behavior scenarios (12 domains)"
else
    export POSTGRES_SERVER=localhost
    export POSTGRES_PORT=54329
    export POSTGRES_USER=skill
    export POSTGRES_PASSWORD=skill
    export POSTGRES_DB=skill_e2e
    export E2E_POSTGRES_URL="postgresql+asyncpg://skill:skill@localhost:54329/skill_e2e"

    start_postgres

    run_suite "PostgreSQL E2E (8 scenarios)" \
        "$PY" tests/test_e2e_postgres.py

    run_suite "Behavior scenarios (12 domains)" \
        "$PY" tests/test_behavior_scenarios.py

    stop_postgres
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "=================================================================="
total=$((passed + failed + skipped))
if [ $failed -eq 0 ]; then
    printf "  ${G}${B}ALL GREEN${N}: %d/%d passed" "$passed" "$total"
    if [ $skipped -gt 0 ]; then
        printf " (%d skipped)" "$skipped"
    fi
    echo ""
else
    printf "  ${R}${B}%d FAILED${N}: %d/%d passed" "$failed" "$passed" "$total"
    if [ $skipped -gt 0 ]; then
        printf " (%d skipped)" "$skipped"
    fi
    echo ""
    echo ""
    echo "  Failed suites:"
    for r in "${results[@]}"; do
        if [[ "$r" == FAIL* ]]; then
            echo "    - ${r#FAIL  }"
        fi
    done
fi
echo "=================================================================="
echo ""

[ $failed -eq 0 ]
