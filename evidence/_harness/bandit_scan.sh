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
    # Bandit exits non-zero (1) when issues are found AND when subprocess
    # itself fails (parser error, missing target). We capture the exit code
    # explicitly and distinguish:
    #   rc=0 → no issues
    #   rc=1 → issues found, log carries severity counts
    #   rc≥2 → bandit subprocess failure (no severity counts written)
    # Wave-I-1.P closes Opus v8 N8 LOW (was: || true silently masked rc≥2).
    set +e
    "${PY}" -m bandit -r "${ex_dir}" -f txt > "${log}" 2>&1
    rc=$?
    set -e
    if [[ "${rc}" -ge 2 ]]; then
        echo "FAIL: bandit subprocess error for ${name} (rc=${rc}); log tail:" >&2
        tail -10 "${log}" >&2
        exit 3
    fi
    # rc 0 or 1 are both "ran successfully"; assert log has the expected
    # severity-counts shape.
    if ! grep -qE "^\s*Total issues \(by severity\)" "${log}"; then
        echo "FAIL: bandit output for ${name} missing severity block (rc=${rc})" >&2
        exit 3
    fi

    high=$(grep -E "^\s*High:\s*[0-9]+" "${log}" | head -1 | awk '{print $2}')
    med=$(grep -E "^\s*Medium:\s*[0-9]+" "${log}" | head -1 | awk '{print $2}')
    low=$(grep -E "^\s*Low:\s*[0-9]+" "${log}" | head -1 | awk '{print $2}')
    # If the parsing fails despite the severity block being present, that's
    # a structural bug — fail loudly rather than silently default to 0.
    if [[ -z "${high}" || -z "${med}" || -z "${low}" ]]; then
        echo "FAIL: could not parse severity counts from ${log}" >&2
        exit 3
    fi

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
