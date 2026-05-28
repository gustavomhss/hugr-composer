#!/usr/bin/env bash
# Tiered local verification — match the test surface to the change's blast radius.
#
# The kit's value is that tools COMPOSE, so a "surgical" change to one tool can
# break another when they run together. That is why the must-run pre-merge set
# is the COMPOSITION gates (boot_chains + e2e + behavior + regression gates), not
# the full unit suite. The full unit suite is only required when a cross-cutting
# file (orchestrator / contracts / templates / type-map) changes.
#
# Usage:
#   scripts/verify.sh            # auto: pick tier from `git diff` vs main
#   scripts/verify.sh tier0      # only the touched tools' unit tests   (~30s)
#   scripts/verify.sh tier1      # composition gates                    (~5min)
#   scripts/verify.sh tier2      # full unit suite + composition gates  (~6min)
#
# Env: a local Postgres on :5432 (user/pass/db = skill/skill/skill_e2e) is used
# for e2e/behavior; override via POSTGRES_* / E2E_POSTGRES_URL.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 2

PY=.venv/bin/python
export PYTHONPATH=.
export SECRET_KEY="${SECRET_KEY:-ci-test-secret-key-must-be-32-chars-long!!!}"
export RATE_LIMITING_ENABLED=false
export ENVIRONMENT=local
export POSTGRES_SERVER="${POSTGRES_SERVER:-localhost}"
export POSTGRES_PORT="${POSTGRES_PORT:-5432}"
export POSTGRES_USER="${POSTGRES_USER:-skill}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-skill}"
export POSTGRES_DB="${POSTGRES_DB:-skill_e2e}"
export E2E_POSTGRES_URL="${E2E_POSTGRES_URL:-postgresql+asyncpg://skill:skill@localhost:5432/skill_e2e}"

fail=0
run() { echo "── $1"; shift; "$@" || { echo "  ✗ FAILED"; fail=1; }; }

# --- Decide tier ----------------------------------------------------------
mode="${1:-auto}"
if [ "$mode" = "auto" ]; then
  base=$(git merge-base HEAD main 2>/dev/null || echo HEAD)
  changed=$( { git diff --name-only "$base"; git diff --name-only; git diff --name-only --cached; } | sort -u )
  # Cross-cutting files → many tools depend on them → full suite.
  if echo "$changed" | grep -qE "skills/SKILL-001-fastapi-production/(generators/|adapt/contracts/|engine/)"; then
    mode=tier2
  else
    mode=tier1
  fi
  echo "auto-selected: $mode (changed: $(echo "$changed" | grep -c . ) file(s))"
fi

# --- Tier 0: touched tools' unit tests (parallel) -------------------------
if [ "$mode" = "tier0" ]; then
  base=$(git merge-base HEAD main 2>/dev/null || echo HEAD)
  tools=$( { git diff --name-only "$base"; git diff --name-only; } \
    | grep -oE "adapt/extend/[^/]+/" | sort -u | sed 's#^skills/SKILL-001-fastapi-production/##' )
  [ -z "$tools" ] && tools="adapt/extend/"
  run "tier0 unit tests ($tools)" $PY -m pytest $tools -q -p no:cacheprovider -n auto
  exit $fail
fi

# --- Tier 2 adds the full unit suite on top of the composition gates ------
if [ "$mode" = "tier2" ]; then
  run "full unit suite (adapt/ -n auto)" $PY -m pytest adapt/ -q -p no:cacheprovider -n auto
fi

# --- Tier 1 (and tier2): composition gates — the real must-run ------------
run "property tests"        $PY tests/property_tests.py
run "contract_check"        $PY -m engine.audit.contract_check
run "boot_chains"           $PY tests/test_boot_chains.py
run "P0 regression gates"   $PY tests/test_p0_regression_gates.py
run "e2e_hardcore"          $PY tests/test_e2e_hardcore.py
run "behavior_scenarios"    $PY tests/test_behavior_scenarios.py

echo
[ "$fail" = 0 ] && echo "✅ verify ($mode): ALL GREEN" || echo "❌ verify ($mode): FAILURES above"
exit $fail
