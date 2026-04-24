#!/usr/bin/env bash
# Run semgrep (OWASP Top-10 + python + security-audit rulesets) on each canonical example.
#
# PRODUCT security claim: emitted code passes semgrep OWASP ruleset with
# 0 HIGH / 0 CRITICAL across 20 examples.
#
# Usage (from repo root):
#   evidence/_harness/semgrep_scan.sh
#
# Outputs:
#   evidence/deterministic/semgrep_scan/<example>.json   per-example raw findings
#   evidence/deterministic/semgrep_scan/SUMMARY.json     aggregate counts
#
# Exit 0 iff no example reports ERROR-severity findings.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SG="${REPO_ROOT}/skills/SKILL-001-fastapi-production/.venv/bin/semgrep"
PY="${REPO_ROOT}/skills/SKILL-001-fastapi-production/.venv/bin/python"
OUT_DIR="${REPO_ROOT}/evidence/deterministic/semgrep_scan"

mkdir -p "${OUT_DIR}"

fail=0
declare -a rows=()

for ex_dir in "${REPO_ROOT}"/examples/[0-9][0-9]-*; do
    name="$(basename "$ex_dir")"
    out="${OUT_DIR}/${name}.json"
    "${SG}" --config=p/python --config=p/security-audit --config=p/owasp-top-ten \
        --no-git-ignore --quiet --json "${ex_dir}" > "${out}" 2>/dev/null || true

    counts=$("${PY}" -c "
import json, sys
d = json.load(open('${out}'))
buckets = {'ERROR': 0, 'WARNING': 0, 'INFO': 0}
for r in d.get('results', []):
    s = (r.get('extra') or {}).get('severity', 'UNKNOWN').upper()
    buckets[s] = buckets.get(s, 0) + 1
print(f\"{buckets.get('ERROR',0)} {buckets.get('WARNING',0)} {buckets.get('INFO',0)}\")
")
    err=$(echo "$counts" | awk '{print $1}')
    warn=$(echo "$counts" | awk '{print $2}')
    info=$(echo "$counts" | awk '{print $3}')

    rows+=("    {\"example\": \"${name}\", \"error\": ${err}, \"warning\": ${warn}, \"info\": ${info}}")
    if [[ "${err}" -gt 0 ]]; then
        fail=1
    fi
done

sha=$(cd "${REPO_ROOT}" && git rev-parse HEAD)
tree=$(cd "${REPO_ROOT}" && git rev-parse 'HEAD^{tree}')
iso=$(date -u +%Y-%m-%dT%H:%M:%SZ)

{
    echo "{"
    echo "  \"_meta\": {"
    echo "    \"command\": \"evidence/_harness/semgrep_scan.sh\","
    echo "    \"cwd\": \"repo root\","
    echo "    \"commit\": \"${sha}\","
    echo "    \"tree\": \"${tree}\","
    echo "    \"generated\": \"${iso}\","
    echo "    \"configs\": [\"p/python\", \"p/security-audit\", \"p/owasp-top-ten\"],"
    echo "    \"grading\": \"expect ERROR==0 across all 20 examples\""
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
    echo "PASS: 0 ERROR-severity findings across all examples"
    exit 0
else
    echo "FAIL: at least one example has ERROR findings"
    exit 1
fi
