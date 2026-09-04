#!/usr/bin/env bash
# bin/local-ci.sh — Local mirror of .github/workflows/ci.yml.
# Use: bypass GitHub CI when the self-hosted runner is broken (TLS backoff).
# Mirror of ci.yml jobs, not a re-invented checklist.

set -euo pipefail

VENV="${VENV:-/Users/gustavoschneiter/.hugr-ci-venv}"
export VENV
export SECRET_KEY="ci-test-secret-key-must-be-32-chars-long!!!"
export MFA_FERNET_KEY="L7gvXDh2v6syV65J0-iwLQMTYbVavNXO2vuXgntcFBo="
export RATE_LIMITING_ENABLED="false"
export ENVIRONMENT="local"
export PYTHONPATH="."

# Postgres contract from ci.yml postgres-behavior job
export E2E_POSTGRES_URL="postgresql+asyncpg://skill:skill@localhost:5432/skill_e2e"
export POSTGRES_SERVER="localhost"
export POSTGRES_PORT="5432"
export POSTGRES_USER="skill"
export POSTGRES_PASSWORD="skill"
export POSTGRES_DB="skill_e2e"

# Soak latency overrides (ci.yml quality-scripts)
export HUGR_SOAK_P50_MS=800
export HUGR_SOAK_P95_MS=1500
export HUGR_SOAK_P99_MS=3000

# Detect Postgres
if pg_isready -h localhost -p 5432 >/dev/null 2>&1; then
  HAS_PG=1
else
  HAS_PG=0
fi

# Detect Docker
if docker info >/dev/null 2>&1; then
  HAS_DOCKER=1
else
  HAS_DOCKER=0
fi

echo "=== local-ci: PG=${HAS_PG} DOCKER=${HAS_DOCKER} VENV=${VENV} ==="
echo "=== branch: $(git rev-parse --abbrev-ref HEAD) commit: $(git rev-parse --short HEAD) ==="

if [ ! -x "${VENV}/bin/python" ]; then
  echo "FATAL: shared venv missing at ${VENV}" >&2
  exit 1
fi

# Resolve BASE for PR-diff jobs (lint). Mirrors ci.yml changes/lint steps.
BASE="${BASE:-}"
TARGET="${GITHUB_BASE_REF:-main}"
git fetch -q --no-tags origin "+refs/heads/${TARGET}:refs/remotes/origin/${TARGET}" 2>/dev/null || true
BASE=$(git merge-base "origin/${TARGET}" HEAD 2>/dev/null || true)
if [ -z "$BASE" ] && [ "$(git rev-parse --is-shallow-repository 2>/dev/null)" = "true" ]; then
  git fetch -q --no-tags --unshallow origin 2>/dev/null || true
  git fetch -q --no-tags origin "+refs/heads/${TARGET}:refs/remotes/origin/${TARGET}" 2>/dev/null || true
  BASE=$(git merge-base "origin/${TARGET}" HEAD 2>/dev/null || true)
fi

# Diff classifier (mirror ci.yml `changes`). Non-PR ⇒ heavy=true. Undetermined base ⇒ heavy=true.
HEAVY=1
if [ "${GITHUB_EVENT_NAME:-}" = "pull_request" ] && [ -n "$BASE" ]; then
  CHANGED=$(git diff --name-only --diff-filter=ACMR "$BASE" HEAD || true)
  HEAVY_HITS=$(echo "$CHANGED" | grep -vE '^(engine/|docs/|skill\.toml$)' | grep -vE '\.md$' || true)
  if [ -z "$HEAVY_HITS" ]; then
    HEAVY=0
  fi
fi
echo "=== heavy=${HEAVY} base=${BASE:-<undetermined>} ==="

PASS=()
FAIL=()
SKIP=()

run() {
  local name="$1"; shift
  echo
  echo "=== ${name} ==="
  if "$@"; then
    PASS+=("$name")
    echo "=== ${name}: PASS ==="
  else
    local rc=$?
    echo "=== ${name}: FAIL (rc=${rc}) ==="
    FAIL+=("$name")
    exit 1
  fi
}

skip() {
  local name="$1"; shift
  echo
  echo "=== ${name} ==="
  echo "SKIP: $*"
  SKIP+=("$name")
}

# --- setup (idempotent) ---------------------------------------------------
run "setup (shared venv)" bash -c '
  set -eo pipefail
  REQ_HASH=$(cat requirements-mcp.txt requirements-apps.txt | shasum | awk "{print \$1}")
  TEST_EXTRAS="pytest pytest-xdist pytest-json-report ruff"
  REQ_HASH="${REQ_HASH} $(echo "$TEST_EXTRAS" | shasum | awk "{print \$1}")"
  STAMP="${VENV}/.req_hash"
  if [ ! -x "${VENV}/bin/python" ] || [ "$(cat "$STAMP" 2>/dev/null)" != "$REQ_HASH" ]; then
    echo "Building shared venv at ${VENV}"
    /usr/local/bin/python3.12 -m venv "${VENV}" || python3.12 -m venv "${VENV}"
    "${VENV}/bin/pip" install --quiet --upgrade pip
    "${VENV}/bin/pip" install --quiet -r requirements-mcp.txt
    "${VENV}/bin/pip" install --quiet -r requirements-apps.txt
    "${VENV}/bin/pip" install --quiet $TEST_EXTRAS
    echo "$REQ_HASH" > "$STAMP"
  else
    echo "Shared venv up to date (req hash $REQ_HASH)"
  fi
'

# --- lint ----------------------------------------------------------------
if [ -n "$BASE" ]; then
  run "lint (ruff check + format, scoped)" bash -c "
    set -eo pipefail
    CHANGED=\$(git diff --name-only --diff-filter=ACMR '${BASE}' HEAD || true)
    PYF=\$(echo \"\$CHANGED\" | grep '\.py\$' | grep -vE '\.venv|/emitted/|core/venous/_staging/|core/venous/_extracted/|\.protocol\.py\$' || true)
    if [ -n \"\$PYF\" ]; then
      echo \"\$PYF\" | while IFS= read -r f; do
        \"${VENV}/bin/python\" -m ruff check \"\$f\"
        \"${VENV}/bin/python\" -m ruff format --check \"\$f\"
      done
    else
      echo \"no .py files changed in PR diff; skipping ruff\"
    fi
  "
else
  skip "lint (ruff check + format, scoped)" "undetermined diff base"
fi

run "lint (no committed venv/site-packages/emitted/db)" "${VENV}/bin/python" scripts/checks/no_committed_venv.py
run "lint (md under docs/ only)" "${VENV}/bin/python" scripts/checks/md_location.py

# --- heavy tool/app suites (gated by HEAVY) ------------------------------
if [ "${HEAVY}" = "1" ]; then
  ln -sfn "${VENV}" "$(pwd)/.venv"

  run "unit (pytest adapt/)" "${VENV}/bin/python" -m pytest adapt/ -q --tb=short -n 4 --dist loadfile
  run "boot (100 tools)" "${VENV}/bin/python" tests/test_boot.py
  run "boot chains" "${VENV}/bin/python" -m pytest tests/test_boot_chains.py -n 3 -q --tb=short

  run "integration (sqlite e2e)" bash -c '
    set -eo pipefail
    "${VENV}/bin/python" tests/test_e2e_hardcore.py
    "${VENV}/bin/python" tests/test_emitted_project_audit.py
  '

  run "quality (generated-output suites)" "${VENV}/bin/python" -m pytest \
    tests/test_spec_compliance.py \
    tests/test_generated_quality.py \
    tests/test_security_generated.py \
    tests/test_bandit_deps.py \
    tests/test_full_integration.py \
    tests/test_http_smoke.py \
    tests/test_lint_generated.py \
    tests/test_alembic_chain_root.py \
    tests/test_fk_regression.py \
    tests/test_concurrent.py \
    tests/test_stress.py \
    tests/test_performance_baseline.py \
    -q --tb=short -n 4 --dist loadfile

  run "quality (script-runners)" bash -c '
    set -eo pipefail
    "${VENV}/bin/python" tests/test_consistency.py
    "${VENV}/bin/python" tests/test_determinism.py
    HUGR_SOAK_P50_MS='"${HUGR_SOAK_P50_MS}"' HUGR_SOAK_P95_MS='"${HUGR_SOAK_P95_MS}"' HUGR_SOAK_P99_MS='"${HUGR_SOAK_P99_MS}"' \
      "${VENV}/bin/python" tests/test_soak.py
    "${VENV}/bin/python" tests/test_edge_cases.py
  '
else
  skip "unit (pytest adapt/)" "heavy=false"
  skip "boot (100 tools)" "heavy=false"
  skip "boot chains" "heavy=false"
  skip "integration (sqlite e2e)" "heavy=false"
  skip "quality (generated-output suites)" "heavy=false"
  skip "quality (script-runners)" "heavy=false"
fi

# --- always-on gates ------------------------------------------------------
run "regression + property + contract" bash -c '
  set -eo pipefail
  "${VENV}/bin/python" tests/test_p0_regression_gates.py
  "${VENV}/bin/python" tests/property_tests.py
  "${VENV}/bin/python" -m engine.audit.contract_check
'

run "auth + mcp gate" bash -c '
  set -eo pipefail
  "${VENV}/bin/python" tests/test_auth_gate.py
  "${VENV}/bin/python" -c "
import asyncio, json, pathlib
from mcp_tools.server import mcp
from mcp_tools.discovery import discover_and_register, activate_bundle
discover_and_register(mcp)
default = len(asyncio.run(mcp.list_tools()))
print(f\"MCP discovery default surface: {default} tools\")
assert default <= 30, f\"tier-1 surface must stay lean (<=30), got {default}\"
cat = json.loads(pathlib.Path(\"engine/index/catalog.json\").read_text())
for s in cat.get(\"skills\", []):
    for b in s.get(\"bundles\", []):
        activate_bundle(b[\"name\"])
full = len(asyncio.run(mcp.list_tools()))
print(f\"MCP discovery full surface (all bundles active): {full} tools\")
assert full >= 170, f\"expected >=170 after activating all bundles, got {full}\"
"
'

run "engine tests (engine/tests/)" "${VENV}/bin/python" -m pytest engine/tests/ -q --tb=short -n 4 --dist loadfile

# --- nightly-extras (schedule-only, skip on PR) ---------------------------
if [ "${GITHUB_EVENT_NAME:-}" = "schedule" ]; then
  run "nightly extras (cross-composition)" "${VENV}/bin/python" -m pytest tests/test_cross_composition.py -q --tb=short -n 4 --dist loadfile
else
  skip "nightly extras (cross-composition)" "not on schedule"
fi

# --- postgres-behavior ----------------------------------------------------
if [ "${HAS_PG}" = "1" ] && [ "${HEAVY}" = "1" ]; then
  run "postgres + behavior" bash -c '
    set -eo pipefail
    "${VENV}/bin/python" tests/test_e2e_postgres.py
    "${VENV}/bin/python" tests/test_behavior_scenarios.py
    "${VENV}/bin/python" tests/test_realworld_ecommerce.py
  '
elif [ "${HAS_PG}" = "0" ]; then
  skip "postgres + behavior" "postgres not available"
else
  skip "postgres + behavior" "heavy=false"
fi

echo
echo "=== local-ci summary ==="
echo "PASS: ${PASS[*]:-(none)}"
echo "FAIL: ${FAIL[*]:-(none)}"
echo "SKIP: ${SKIP[*]:-(none)}"
if [ "${#FAIL[@]}" -gt 0 ]; then
  exit 1
fi