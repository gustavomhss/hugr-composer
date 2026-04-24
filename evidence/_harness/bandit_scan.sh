#!/usr/bin/env bash
# Run bandit on each canonical example, produce per-example logs + aggregate summary.
#
# PRODUCT security claim: emitted code passes bandit (OWASP ruleset) with
# 0 HIGH / 0 CRITICAL across 20 examples.
#
# Usage (from repo root):
#   evidence/_harness/bandit_scan.sh
#
# Outputs:
#   evidence/deterministic/bandit_scan/<example>.log   per-example raw bandit output
#   evidence/deterministic/bandit_scan/SUMMARY.json    aggregate counts
#
# Exit 0 iff every example has High==0 and Medium==0.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PY="${REPO_ROOT}/skills/SKILL-001-fastapi-production/.venv/bin/python"
OUT_DIR="${REPO_ROOT}/evidence/deterministic/bandit_scan"

mkdir -p "${OUT_DIR}"

fail=0
declare -a rows=()

for ex_dir in "${REPO_ROOT}"/examples/[0-9][0-9]-*; do
    name="$(basename "$ex_dir")"
    log="${OUT_DIR}/${name}.log"
    "${PY}" -m bandit -r "${ex_dir}" -f txt > "${log}" 2>&1 || true

    high=$(grep -E "^\s*High:\s*[0-9]+" "${log}" | head -1 | awk '{print $2}')
    med=$(grep -E "^\s*Medium:\s*[0-9]+" "${log}" | head -1 | awk '{print $2}')
    low=$(grep -E "^\s*Low:\s*[0-9]+" "${log}" | head -1 | awk '{print $2}')
    high="${high:-0}"
    med="${med:-0}"
    low="${low:-0}"

    rows+=("    {\"example\": \"${name}\", \"high\": ${high}, \"medium\": ${med}, \"low\": ${low}}")
    if [[ "${high}" -gt 0 || "${med}" -gt 0 ]]; then
        fail=1
    fi
done

sha=$(cd "${REPO_ROOT}" && git rev-parse HEAD)
tree=$(cd "${REPO_ROOT}" && git rev-parse 'HEAD^{tree}')
iso=$(date -u +%Y-%m-%dT%H:%M:%SZ)

{
    echo "{"
    echo "  \"_meta\": {"
    echo "    \"command\": \"evidence/_harness/bandit_scan.sh\","
    echo "    \"cwd\": \"repo root\","
    echo "    \"commit\": \"${sha}\","
    echo "    \"tree\": \"${tree}\","
    echo "    \"generated\": \"${iso}\","
    echo "    \"grading\": \"expect High==0 and Medium==0 across all 20 examples\""
    echo "  },"
    echo "  \"per_example\": ["
    IFS=$'\n'
    joined="$(printf '%s,\n' "${rows[@]}" | sed '$ s/,$//')"
    echo "${joined}"
    echo "  ]"
    echo "}"
} > "${OUT_DIR}/SUMMARY.json"

echo "wrote: ${OUT_DIR}/SUMMARY.json"
if [[ "${fail}" -eq 0 ]]; then
    echo "PASS: 0 High / 0 Medium across all examples"
    exit 0
else
    echo "FAIL: at least one example has High or Medium issues"
    exit 1
fi
