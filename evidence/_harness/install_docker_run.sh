#!/usr/bin/env bash
# Local re-run of the `install-docker.yml` CI workflow — fresh python:3.12-slim,
# install.sh to completion, plus the three smoke tests (MCP discovery,
# contract_check, benchmark score readable).
#
# PRODUCT §1 claim: fresh install path works end-to-end.
#
# Usage (from repo root):
#   evidence/_harness/install_docker_run.sh
#
# Outputs:
#   evidence/deterministic/install_docker_run.log
#
# Requires a running Docker daemon. When docker is unavailable, the script
# writes a "SKIPPED-LOCALLY" log explaining that the canonical evidence
# for this artefact is the `install-docker.yml` nightly CI green run
# (tag-gate window: 2 consecutive nightly greens per ROADMAP §5.7).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${REPO_ROOT}/evidence/deterministic/install_docker_run.log"

sha=$(cd "${REPO_ROOT}" && git rev-parse HEAD)
tree=$(cd "${REPO_ROOT}" && git rev-parse 'HEAD^{tree}')
iso=$(date -u +%Y-%m-%dT%H:%M:%SZ)

header() {
    cat <<EOF
# install_docker_run.log
# command:  evidence/_harness/install_docker_run.sh
# cwd:      repo root
# commit:   ${sha}
# tree:     ${tree}
# generated: ${iso}
# grading:  expect install.sh exit 0 + MCP discover ≥100 + contract_check exit 0 + benchmark overall ≥30
# ---
EOF
}

if ! docker info >/dev/null 2>&1; then
    {
        header
        echo "SKIPPED-LOCALLY: docker daemon not reachable at this host."
        echo ""
        echo "Canonical evidence source: .github/workflows/install-docker.yml"
        echo "  - runs on: python:3.12-slim container on GitHub Actions"
        echo "  - schedule: nightly 04:23 UTC"
        echo "  - trigger:  push/PR affecting install.sh / requirements / VERSION"
        echo "  - tag-gate: 2 consecutive nightly greens in the 48h pre-tag window"
        echo "             (ROADMAP §5.7 / LAUNCH.md §1.2)"
        echo ""
        echo "Steps the workflow runs (replicated by this harness when docker is available):"
        echo "  1. apt-get install -y git ca-certificates"
        echo "  2. bash install.sh  (clones into /opt/hugr-skills + creates venv)"
        echo "  3. python -c 'discover_and_register(mcp); assert n >= 100'"
        echo "  4. .venv/bin/python -m engine.audit.contract_check --quiet"
        echo "  5. assert benchmarks/latest_score.json.overall >= 30"
    } > "${OUT}"
    echo "install_docker_run: skipped locally (docker down). Log written: ${OUT}"
    exit 0
fi

{
    header
    echo "[1/4] pulling python:3.12-slim …"
} > "${OUT}"

docker pull python:3.12-slim >> "${OUT}" 2>&1 || {
    echo "FAIL: docker pull" >> "${OUT}"; exit 1;
}

echo "[2/4] running install.sh + smoke tests in hermetic container …" >> "${OUT}"

docker run --rm \
    -v "${REPO_ROOT}:/workspace:ro" \
    -w /opt \
    python:3.12-slim bash -c '
set -euo pipefail
apt-get update -qq
apt-get install -y --no-install-recommends git ca-certificates > /dev/null
mkdir -p /opt/hugr-skills
cp -a /workspace/. /opt/hugr-skills/
cd /opt/hugr-skills
bash install.sh
echo "--- smoke 1: MCP discovery ---"
PYTHONPATH=/opt/hugr-skills/skills/SKILL-001-fastapi-production \
    /opt/hugr-skills/skills/SKILL-001-fastapi-production/.venv/bin/python -c "
from mcp_tools.server import mcp
from mcp_tools.discovery import discover_and_register
n = discover_and_register(mcp)
assert n >= 100, f\"expected >=100 MCP tools, got {n}\"
print(f\"MCP discovery OK: {n} tools registered\")
"
echo "--- smoke 2: contract_check ---"
cd /opt/hugr-skills/skills/SKILL-001-fastapi-production
PYTHONPATH=. .venv/bin/python -m engine.audit.contract_check --quiet
echo "--- smoke 3: benchmark score ---"
.venv/bin/python - <<PY
import json, pathlib
p = pathlib.Path("benchmarks/latest_score.json")
data = json.loads(p.read_text())
overall = float(data["overall"])
assert overall >= 30.0, f"benchmark regressed: overall={overall} < 30"
print(f"benchmark overall={overall:.2f}")
PY
echo "--- ALL SMOKE TESTS PASSED ---"
' >> "${OUT}" 2>&1

rc=$?
{
    echo "[3/4] container exit=${rc}"
    echo "[4/4] done"
    if [[ "${rc}" -eq 0 ]]; then
        echo "PASS: install.sh + 3 smoke tests green on fresh python:3.12-slim"
    else
        echo "FAIL: container exited non-zero"
    fi
} >> "${OUT}"
exit "${rc}"
