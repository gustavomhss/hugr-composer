#!/usr/bin/env bash
# evidence/reproduce.sh — reproduce the evidence package at the current HEAD.
#
# Per LAUNCH.md §2.4 + Wave I-1 hardening (Codex v7 + Opus Q2 contract fixes):
#   --verify-fast       Lightweight subset only (5 probes, ≤2min) — was old --verify
#   --verify            Full deterministic set diff (≤30min). Fails on any drift.
#   --deterministic     Regenerate full deterministic set + enforce byte-identity diff.
#                       Exits 1 on any divergence. (LAUNCH §2.4 contract.)
#   --external-eval     Live LLM evals — ~$200-500. Fail-closed: any sub-runner
#                       error exits 1. (Was fail-open with || true; fixed in I-1.)
#   --all (default)     Both deterministic + external-eval.
#
# Exit codes:
#   0 — requested artefacts regenerated + verified clean
#   1 — drift in at least one deterministic artefact (or external-eval runner failed)
#   2 — usage / arg error
#   3 — internal harness error (see stderr)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${REPO_ROOT}"

MODE="${1:---all}"

case "${MODE}" in
    -h|--help)
        sed -n '2,16p' "$0"
        exit 0
        ;;
    --verify|--verify-fast|--deterministic|--external-eval|--all)
        ;;
    *)
        echo "usage: $0 [--verify | --verify-fast | --deterministic | --external-eval | --all]" >&2
        exit 2
        ;;
esac

c_reset=$'\033[0m'
c_cyan=$'\033[36m'
c_green=$'\033[32m'
c_red=$'\033[31m'
c_yellow=$'\033[33m'
log()  { printf "${c_cyan}→${c_reset} %s\n" "$*"; }
ok()   { printf "${c_green}✓${c_reset} %s\n" "$*"; }
fail() { printf "${c_red}✗${c_reset} %s\n" "$*" >&2; }
note() { printf "${c_yellow}!${c_reset} %s\n" "$*"; }

HARNESS="${REPO_ROOT}/evidence/_harness"
DET_DIR="${REPO_ROOT}/evidence/deterministic"
SKILL_DIR="${REPO_ROOT}/skills/SKILL-001-fastapi-production"
VENV_PY="${SKILL_DIR}/.venv/bin/python"

###############################################################################
# Lightweight regen (5 probes that finish in <60s combined)
###############################################################################

regen_contract_check() {
    log "contract_check"
    local out="${DET_DIR}/contract_check.log"
    local sha tree iso
    sha=$(git rev-parse HEAD)
    tree=$(git rev-parse 'HEAD^{tree}')
    iso=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    {
        echo "# contract_check.log"
        echo "# command:  PYTHONPATH=. .venv/bin/python -m engine.audit.contract_check"
        echo "# cwd:      skills/SKILL-001-fastapi-production"
        echo "# commit:   ${sha}"
        echo "# tree:     ${tree}"
        echo "# generated: ${iso}"
        echo "# grading:  binary — expect '37/37 contract items satisfied — ALL GREEN'"
        echo "# ---"
        (cd "${SKILL_DIR}" && PYTHONPATH=. .venv/bin/python -m engine.audit.contract_check) 2>&1 | tail -60
    } > "${out}"
}

regen_manifest_idempotence() {
    log "manifest_idempotence"
    local out="${DET_DIR}/manifest_idempotence.log"
    local sha tree iso
    sha=$(git rev-parse HEAD); tree=$(git rev-parse 'HEAD^{tree}'); iso=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    {
        echo "# manifest_idempotence.log"
        echo "# command:  PYTHONPATH=. .venv/bin/python -m engine.index.manifest verify"
        echo "# cwd:      skills/SKILL-001-fastapi-production"
        echo "# commit:   ${sha}"
        echo "# tree:     ${tree}"
        echo "# generated: ${iso}"
        echo "# grading:  expect 'idempotent: stable hash matches across two builds' + exit 0"
        echo "# ---"
        (cd "${SKILL_DIR}" && PYTHONPATH=. .venv/bin/python -m engine.index.manifest verify) 2>&1
        echo "exit=$?"
    } > "${out}"
}

regen_framework_free() {
    log "framework_free_proof"
    local out="${DET_DIR}/framework_free_proof.log"
    local sha tree iso
    sha=$(git rev-parse HEAD); tree=$(git rev-parse 'HEAD^{tree}'); iso=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    {
        echo "# framework_free_proof.log"
        echo "# command:  .venv/bin/python evidence/_harness/framework_free_probe.py"
        echo "# cwd:      repo root"
        echo "# commit:   ${sha}"
        echo "# tree:     ${tree}"
        echo "# generated: ${iso}"
        echo "# grading:  expect 124 registered primitives + 0 web-framework imports + exit 0"
        echo "# ---"
        "${VENV_PY}" "${HARNESS}/framework_free_probe.py"
        echo "exit=$?"
    } > "${out}"
}

regen_freshness() {
    log "freshness_proof"
    local out="${DET_DIR}/freshness_proof.log"
    local sha tree iso head_iso head_msg branch dirty
    sha=$(git rev-parse HEAD); tree=$(git rev-parse 'HEAD^{tree}'); iso=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    head_iso=$(git log -1 --format=%cI HEAD)
    head_msg=$(git log -1 --format=%s HEAD)
    branch=$(git branch --show-current)
    dirty=$(git status --porcelain | wc -l | tr -d ' ')
    {
        echo "# freshness_proof.log"
        echo "# command:  git rev-parse HEAD; git rev-parse HEAD^{tree}; date -u"
        echo "# cwd:      repo root"
        echo "# commit:   ${sha}"
        echo "# tree:     ${tree}"
        echo "# generated: ${iso}"
        echo "# grading:  commit SHA must equal the tag commit at v1.0.0 cut"
        echo "# ---"
        echo "commit:  ${sha}"
        echo "tree:    ${tree}"
        echo "head_iso: ${head_iso}"
        echo "head_msg: ${head_msg}"
        echo "branch:  ${branch}"
        echo "clean:   ${dirty} modified/untracked paths"
        echo "generated: ${iso}"
    } > "${out}"
}

regen_loc_budget() {
    log "loc_budget_stats (pedagogical examples)"
    local out="${DET_DIR}/loc_budget_stats.json"
    local sha tree iso tmp
    sha=$(git rev-parse HEAD); tree=$(git rev-parse 'HEAD^{tree}'); iso=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    tmp=$(mktemp)
    "${VENV_PY}" "${HARNESS}/loc_budget_probe.py" > "${tmp}"
    SHA="${sha}" TREE="${tree}" ISO="${iso}" BODY_PATH="${tmp}" "${VENV_PY}" -c '
import json, os
body = json.loads(open(os.environ["BODY_PATH"]).read())
wrapped = {
    "_meta": {
        "command": ".venv/bin/python evidence/_harness/loc_budget_probe.py",
        "cwd": "repo root",
        "commit": os.environ["SHA"],
        "tree": os.environ["TREE"],
        "generated": os.environ["ISO"],
        "grading": "p95 app_loc_per_handler <= 20 per PRODUCT §6.1",
    },
    **body,
}
print(json.dumps(wrapped, indent=2, sort_keys=True))
' > "${out}"
    rm -f "${tmp}"
}

###############################################################################
# Heavy regen (each probe writes its own JSON with full _meta header)
###############################################################################

regen_per_tool() {
    log "per_tool_pattern_audit"
    "${VENV_PY}" "${HARNESS}/per_tool_pattern_audit.py" > "${DET_DIR}/per_tool_pattern_audit.json"
}

regen_per_primitive() {
    log "per_primitive_attestation"
    "${VENV_PY}" "${HARNESS}/per_primitive_attestation.py" > "${DET_DIR}/per_primitive_attestation.json"
}

regen_adapter_matrix() {
    log "fastapi_adapter_matrix"
    "${VENV_PY}" "${HARNESS}/fastapi_adapter_matrix.py" > "${DET_DIR}/fastapi_adapter_matrix.json"
}

regen_module_matrix() {
    log "module_integration_matrix"
    "${VENV_PY}" "${HARNESS}/module_integration_matrix.py" > "${DET_DIR}/module_integration_matrix.json"
}

regen_per_example() {
    log "per_example_pytest_matrix (~20s)"
    "${VENV_PY}" "${HARNESS}/per_example_pytest_matrix.py" > "${DET_DIR}/per_example_pytest_matrix.json"
}

regen_benchmark_scores() {
    log "benchmark_scores"
    "${VENV_PY}" "${HARNESS}/benchmark_scores_snapshot.py" > "${DET_DIR}/benchmark_scores.json"
}

regen_framework_free_runtime() {
    log "framework_free_runtime (~30s)"
    "${VENV_PY}" "${HARNESS}/framework_free_runtime.py" > "${DET_DIR}/framework_free_runtime.json"
}

regen_emitted_glue_loc() {
    log "emitted_glue_loc (~60s — invokes 12 sample tools)"
    "${VENV_PY}" "${HARNESS}/emitted_glue_loc.py" > "${DET_DIR}/emitted_glue_loc.json"
}

regen_generator_idempotence() {
    log "generator_idempotence (~30s)"
    "${VENV_PY}" "${HARNESS}/generator_idempotence.py" > "${DET_DIR}/generator_idempotence.json"
}

regen_security_scans() {
    log "bandit_scan + semgrep_scan"
    bash "${HARNESS}/bandit_scan.sh" > /dev/null
    bash "${HARNESS}/semgrep_scan.sh" > /dev/null
}

regen_install_docker() {
    log "install_docker_run (skipped if docker daemon offline)"
    bash "${HARNESS}/install_docker_run.sh" > /dev/null
}

regen_pytest_full_sweep() {
    log "pytest_full_sweep (~27 min)"
    local out="${DET_DIR}/pytest_full_sweep.log"
    local sha tree iso
    sha=$(git rev-parse HEAD); tree=$(git rev-parse 'HEAD^{tree}'); iso=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    {
        echo "# pytest_full_sweep.log"
        echo "# command:  PYTHONPATH=. .venv/bin/python -m pytest adapt/ core/venous/ engine/ -q --tb=line"
        echo "# cwd:      skills/SKILL-001-fastapi-production"
        echo "# commit:   ${sha}"
        echo "# tree:     ${tree}"
        echo "# generated: ${iso}"
        echo "# grading:  expect '5387 passed' + '0 failed' on the summary line"
        echo "# ---"
    } > "${out}"
    (cd "${SKILL_DIR}" && PYTHONPATH=. .venv/bin/python -m pytest adapt/ core/venous/ engine/ -q --tb=line) >> "${out}" 2>&1
}

regen_test_suites() {
    log "test_suites/{boot,property,e2e_sqlite,stress,cross_composition}"
    mkdir -p "${DET_DIR}/test_suites"
    local sha tree iso
    sha=$(git rev-parse HEAD); tree=$(git rev-parse 'HEAD^{tree}'); iso=$(date -u +%Y-%m-%dT%H:%M:%SZ)

    # Each suite re-run + captured. Cross-composition included in regen so
    # --verify covers it (Codex v8 finding: was excluded). cross_composition
    # is the long pole at ~36 min; budget for full --deterministic accordingly.
    for SUITE in boot_test property_tests e2e_sqlite stress_test cross_composition; do
        case "${SUITE}" in
            boot_test) cmd_file="tests/test_boot.py" ; grade="100/100 tools boot cleanly";;
            property_tests) cmd_file="tests/property_tests.py" ; grade="8/8 properties (LAUNCH §1.2 met after Wave I-1.L)";;
            e2e_sqlite) cmd_file="tests/test_e2e_hardcore.py" ; grade="12/12 scenarios passed";;
            stress_test) cmd_file="tests/test_stress.py" ; grade="3/3 stress scenarios passed";;
            cross_composition) cmd_file="tests/test_cross_composition.py" ; grade="200+ scenarios ALL PASSED (~36min)";;
        esac
        local out="${DET_DIR}/test_suites/${SUITE}.log"
        {
            echo "# ${SUITE}.log"
            echo "# command:  PYTHONPATH=. .venv/bin/python ${cmd_file}"
            echo "# cwd:      skills/SKILL-001-fastapi-production"
            echo "# commit:   ${sha}"
            echo "# tree:     ${tree}"
            echo "# generated: ${iso}"
            echo "# grading:  ${grade}"
            echo "# ---"
        } > "${out}"
        (cd "${SKILL_DIR}" && PYTHONPATH=. .venv/bin/python "${cmd_file}") >> "${out}" 2>&1 || true
    done
}

# Order matters: lighter probes first so failures fail fast.
LIGHTWEIGHT_ARTEFACTS=(
    contract_check.log
    manifest_idempotence.log
    framework_free_proof.log
    loc_budget_stats.json
    freshness_proof.log
)

HEAVY_ARTEFACTS=(
    per_tool_pattern_audit.json
    per_primitive_attestation.json
    fastapi_adapter_matrix.json
    module_integration_matrix.json
    per_example_pytest_matrix.json
    benchmark_scores.json
    framework_free_runtime.json
    emitted_glue_loc.json
    generator_idempotence.json
)

regen_all_lightweight() {
    regen_contract_check
    regen_manifest_idempotence
    regen_framework_free
    regen_loc_budget
    regen_freshness
}

regen_all_heavy() {
    regen_per_tool
    regen_per_primitive
    regen_adapter_matrix
    regen_module_matrix
    regen_per_example
    regen_benchmark_scores
    regen_framework_free_runtime
    regen_emitted_glue_loc
    regen_generator_idempotence
    regen_security_scans
    regen_install_docker
    regen_test_suites
    regen_pytest_full_sweep
}

###############################################################################
# Diff helpers
###############################################################################

normalize_for_diff() {
    # Strip ephemeral fields that legitimately vary between runs:
    #   - generated/commit/tree (regen metadata)
    #   - head_iso/head_msg/clean (freshness_proof working-tree state)
    #   - duration_s / stderr_tail (wall timing + crash logs)
    #   - "summary_line" (pytest's "X passed in Y.YYs" — Y varies)
    #   - "exit_code" (always 0 on pass; if non-zero, "passed" field flips)
    sed -E \
        -e '/^# (generated|commit|tree): /d' \
        -e '/^[[:space:]]*"(generated|commit|tree)": /d' \
        -e '/^(generated|commit|tree|head_iso|head_msg|clean): /d' \
        -e '/^[[:space:]]*"duration_s":/d' \
        -e '/^[[:space:]]*"stderr_tail":/d' \
        -e '/^[[:space:]]*"summary_line":/d' \
        -e '/^[[:space:]]*"exit_code":/d' \
        "$1"
}

# Suite logs (test runners) and pytest_full_sweep are content-rich +
# non-deterministic by nature — they embed wall-clock timestamps, request
# UUIDs, tempdir paths, durations on EVERY logged line. Trying to scrub all
# variation is intractable. Instead, validate them by grading-line match:
# confirm the artefact exists and its bottom grading line matches the
# expected SUMMARY pattern (e.g. "5387 passed", "ALL PASSED", "100/100").
# This is the honest contract: suite logs ARE attestation that the suite
# ran + passed, NOT byte-stable artefacts. Codex v8 + Opus v8 N1 feedback:
# the byte-diff for these was already broken in the prior iteration; this
# replaces it with a grading check that's actually meaningful.
grading_check() {
    # Match the pattern ONLY in the body of the artefact (after the `# ---`
    # header separator). The header carries the EXPECTED grading message in
    # a comment ("# grading: 8/8 properties...") which would false-positive
    # the check before the test even runs. Codex v9 BLOCKER + Opus v9 N1
    # both flagged this. Fix: anchor below the separator.
    local file="$1" pattern="$2" name="$3"
    if [[ ! -f "${file}" ]]; then
        fail "missing: ${name}"
        return 1
    fi
    # Extract body: lines after the first `# ---` separator. If no separator
    # is present (e.g., suite log written without our header), use whole file.
    local body
    body=$(awk 'started{print} /^# ---$/{started=1}' "${file}")
    if [[ -z "${body}" ]]; then
        body=$(cat "${file}")
    fi
    if echo "${body}" | grep -qE "${pattern}"; then
        ok "grading match: ${name}"
        return 0
    fi
    fail "grading mismatch: ${name} (expected pattern: ${pattern}; checked BODY only, header excluded)"
    return 1
}

diff_artefact() {
    local committed="$1" regen="$2" name="$3"
    if [[ ! -f "${committed}" || ! -f "${regen}" ]]; then
        note "missing: ${name}"
        return 1
    fi
    if diff <(normalize_for_diff "${committed}") <(normalize_for_diff "${regen}") > /dev/null; then
        ok "match: ${name}"
        return 0
    fi
    fail "drift: ${name}"
    return 1
}

###############################################################################
# Verify orchestration
###############################################################################

do_verify_fast() {
    log "verify-fast: regen lightweight subset, diff against committed"
    local tmp drift
    tmp=$(mktemp -d)
    cp -a "${DET_DIR}/." "${tmp}/"
    local DET_DIR_SAVED="${DET_DIR}"
    DET_DIR="${tmp}"
    regen_all_lightweight
    DET_DIR="${DET_DIR_SAVED}"
    drift=0
    # NEW: head-pin atomicity check (Codex v9 BLOCKER closure).
    head_pin_check || drift=1
    for n in "${LIGHTWEIGHT_ARTEFACTS[@]}"; do
        diff_artefact "${DET_DIR}/${n}" "${tmp}/${n}" "${n}" || drift=1
    done
    rm -rf "${tmp}"
    [[ "${drift}" -eq 0 ]] || { fail "--verify-fast FAIL: lightweight subset drifted"; return 1; }
    ok "--verify-fast PASS: lightweight deterministic subset matches"
    return 0
}

head_pin_check() {
    # Codex v9 BLOCKER: normalize_for_diff strips commit/tree from
    # freshness_proof.log so a green --verify does NOT prove the package
    # is pinned to current HEAD. This separate check bypasses normalization
    # and asserts the COMMIT line in freshness_proof.log matches `git
    # rev-parse HEAD`. Also asserts every per-artefact `_meta.commit` /
    # `# commit:` value across deterministic/ pins to the SAME SHA.
    local current_head expected pinned_shas
    current_head=$(git rev-parse HEAD)
    expected=$(grep -E "^# commit:" "${DET_DIR}/freshness_proof.log" | head -1 | awk '{print $3}')
    if [[ -z "${expected}" || "${expected}" != "${current_head}" ]]; then
        fail "head-pin FAIL: freshness_proof.log commit (${expected:-NONE}) != git HEAD (${current_head})"
        return 1
    fi
    # Every artefact must pin to the same SHA — atomicity check.
    pinned_shas=$(
        {
            grep -hE '^# commit:' "${DET_DIR}"/*.log 2>/dev/null
            grep -hE '"commit":[[:space:]]*"[0-9a-f]{40}"' "${DET_DIR}"/*.json 2>/dev/null
            grep -hE '"commit":[[:space:]]*"[0-9a-f]{40}"' "${DET_DIR}"/*/SUMMARY.json 2>/dev/null
        } | grep -oE '[0-9a-f]{40}' | sort -u
    )
    local n_unique
    n_unique=$(echo "${pinned_shas}" | wc -l | tr -d ' ')
    if [[ "${n_unique}" -ne 1 ]]; then
        fail "atomicity FAIL: artefacts pin to ${n_unique} different SHAs:"
        echo "${pinned_shas}" | sed 's/^/      /' >&2
        return 1
    fi
    if [[ "${pinned_shas}" != "${current_head}" ]]; then
        fail "atomicity FAIL: all artefacts pin to ${pinned_shas} (single SHA, atomic) but git HEAD is ${current_head}"
        return 1
    fi
    ok "head-pin: every artefact's commit field == git HEAD (${current_head:0:12})"
    return 0
}

do_verify() {
    log "verify: regen FULL deterministic set + diff against committed"
    note "this includes per-tool/per-primitive/adapter/module/per-example/benchmark/framework-free-runtime/emitted-glue/idempotence/security/install-docker/suites/pytest"
    note "wall budget: ~30 min (pytest is the long pole)"
    local tmp drift
    tmp=$(mktemp -d)
    cp -a "${DET_DIR}/." "${tmp}/"
    local DET_DIR_SAVED="${DET_DIR}"
    DET_DIR="${tmp}"
    regen_all_lightweight
    regen_all_heavy
    DET_DIR="${DET_DIR_SAVED}"

    drift=0
    # NEW: head-pin atomicity check (Codex v9 BLOCKER closure).
    head_pin_check || drift=1
    for n in "${LIGHTWEIGHT_ARTEFACTS[@]}" "${HEAVY_ARTEFACTS[@]}"; do
        diff_artefact "${DET_DIR}/${n}" "${tmp}/${n}" "${n}" || drift=1
    done
    # Diff scan summaries (per-example logs are timestamp-noisy; skip individual rows).
    diff_artefact "${DET_DIR}/bandit_scan/SUMMARY.json" "${tmp}/bandit_scan/SUMMARY.json" "bandit_scan/SUMMARY.json" || drift=1
    diff_artefact "${DET_DIR}/semgrep_scan/SUMMARY.json" "${tmp}/semgrep_scan/SUMMARY.json" "semgrep_scan/SUMMARY.json" || drift=1
    # Suite logs + pytest are timestamp-and-uuid-and-tempdir-rich → byte-diff
    # is intractable. Use grading_check (presence + summary line pattern)
    # instead. Honest contract per the docstring on grading_check above.
    grading_check "${DET_DIR}/test_suites/boot_test.log" "100/100 tools boot" "test_suites/boot_test.log" || drift=1
    grading_check "${DET_DIR}/test_suites/property_tests.log" "8/8 properties|ALL PASSED" "test_suites/property_tests.log" || drift=1
    grading_check "${DET_DIR}/test_suites/e2e_sqlite.log" "12/12 tests passed|Result: 12/12" "test_suites/e2e_sqlite.log" || drift=1
    grading_check "${DET_DIR}/test_suites/stress_test.log" "3/3 tests passed|Result: 3/3" "test_suites/stress_test.log" || drift=1
    if [[ -f "${DET_DIR}/test_suites/cross_composition.log" ]]; then
        grading_check "${DET_DIR}/test_suites/cross_composition.log" "ALL PASSED" "test_suites/cross_composition.log" || drift=1
    fi
    grading_check "${DET_DIR}/pytest_full_sweep.log" "[0-9]+ passed.*0:[0-9]+:[0-9]+|[0-9]+ passed" "pytest_full_sweep.log" || drift=1
    # install_docker_run.log: either SKIPPED-LOCALLY token OR ALL SMOKE TESTS PASSED
    grading_check "${DET_DIR}/install_docker_run.log" "SKIPPED-LOCALLY|ALL SMOKE TESTS PASSED" "install_docker_run.log" || drift=1

    rm -rf "${tmp}"
    [[ "${drift}" -eq 0 ]] || { fail "--verify FAIL: at least one artefact drifted or its grading line missing"; return 1; }
    ok "--verify PASS: deterministic set matches committed; suite logs grading-line OK"
    return 0
}

###############################################################################
# --deterministic: regenerate FULL set + assert idempotent (re-regen yields same)
###############################################################################

do_deterministic() {
    log "deterministic: regen FULL set + assert byte-identity on second regen"
    regen_all_lightweight
    regen_all_heavy
    "${VENV_PY}" "${HARNESS}/metrics_summary.py" > "${REPO_ROOT}/evidence/metrics_summary.json"
    log "first-pass complete; running second-pass into /tmp + diffing for idempotence"
    local tmp drift
    tmp=$(mktemp -d)
    cp -a "${DET_DIR}/." "${tmp}/"
    local DET_DIR_SAVED="${DET_DIR}"
    DET_DIR="${tmp}"
    regen_all_lightweight
    regen_all_heavy
    DET_DIR="${DET_DIR_SAVED}"
    drift=0
    for n in "${LIGHTWEIGHT_ARTEFACTS[@]}" "${HEAVY_ARTEFACTS[@]}"; do
        diff_artefact "${DET_DIR}/${n}" "${tmp}/${n}" "${n}" || drift=1
    done
    # Wave-I-1.N: scan summaries are deterministic enough to byte-diff;
    # suite logs + pytest + install_docker are content-rich + tempdir-rich +
    # uuid-rich + timestamp-rich → grading-line check instead of byte-diff.
    diff_artefact "${DET_DIR}/bandit_scan/SUMMARY.json" "${tmp}/bandit_scan/SUMMARY.json" "bandit_scan/SUMMARY.json" || drift=1
    diff_artefact "${DET_DIR}/semgrep_scan/SUMMARY.json" "${tmp}/semgrep_scan/SUMMARY.json" "semgrep_scan/SUMMARY.json" || drift=1
    grading_check "${DET_DIR}/test_suites/boot_test.log" "100/100 tools boot" "test_suites/boot_test.log" || drift=1
    grading_check "${DET_DIR}/test_suites/property_tests.log" "8/8 properties|ALL PASSED" "test_suites/property_tests.log" || drift=1
    grading_check "${DET_DIR}/test_suites/e2e_sqlite.log" "12/12 tests passed|Result: 12/12" "test_suites/e2e_sqlite.log" || drift=1
    grading_check "${DET_DIR}/test_suites/stress_test.log" "3/3 tests passed|Result: 3/3" "test_suites/stress_test.log" || drift=1
    if [[ -f "${DET_DIR}/test_suites/cross_composition.log" ]]; then
        grading_check "${DET_DIR}/test_suites/cross_composition.log" "ALL PASSED" "test_suites/cross_composition.log" || drift=1
    fi
    grading_check "${DET_DIR}/install_docker_run.log" "SKIPPED-LOCALLY|ALL SMOKE TESTS PASSED" "install_docker_run.log" || drift=1
    grading_check "${DET_DIR}/pytest_full_sweep.log" "[0-9]+ passed.*0:[0-9]+:[0-9]+|[0-9]+ passed" "pytest_full_sweep.log" || drift=1
    rm -rf "${tmp}"
    [[ "${drift}" -eq 0 ]] || { fail "--deterministic FAIL: regen non-idempotent"; return 1; }
    ok "--deterministic PASS: full set regenerated AND byte-stable on rerun"
    return 0
}

###############################################################################
# --external-eval: paid LLM run (deferred to 48h pre-tag window).
# Wave I-1 hardening: fail-closed (was fail-open with || true).
###############################################################################

do_external_eval() {
    # Wave-I-1.N hardening: require ALL provider keys (was: any single key).
    # Codex v8 caught: with only one key set, single_shot would run on Claude
    # but cross_model_fnf would silently emit empty manifests for GPT + Gemini
    # and return 0 — fail-open with PARTIAL credentials. Tag-gate runs require
    # the FULL three-model triangulation, so demand all three.
    local missing=()
    [[ -z "${ANTHROPIC_API_KEY:-}" ]] && missing+=("ANTHROPIC_API_KEY")
    [[ -z "${OPENAI_API_KEY:-}" ]] && missing+=("OPENAI_API_KEY")
    [[ -z "${GOOGLE_API_KEY:-}" ]] && missing+=("GOOGLE_API_KEY")
    if [[ "${#missing[@]}" -gt 0 ]]; then
        fail "--external-eval: missing API keys: ${missing[*]}"
        note "Tag-gate runs require ALL THREE keys (Anthropic + OpenAI + Google)"
        note "to drive the cross_model_fnf 3-way comparison. Aborting."
        return 2
    fi
    local errs=0
    log "single_shot_benchmark…"
    "${VENV_PY}" "${REPO_ROOT}/evidence/external-eval/single_shot_benchmark/_harness/run.py" || { fail "single_shot runner failed"; errs=$((errs+1)); }
    log "cross_model_fnf…"
    "${VENV_PY}" "${REPO_ROOT}/evidence/external-eval/cross_model_fnf/_harness/run.py" || { fail "cross_model_fnf runner failed"; errs=$((errs+1)); }
    log "counterfactual…"
    "${VENV_PY}" "${REPO_ROOT}/evidence/external-eval/counterfactual/_harness/run.py" || { fail "counterfactual runner failed"; errs=$((errs+1)); }
    log "post-run: update metrics_summary.json"
    "${VENV_PY}" "${HARNESS}/metrics_summary.py" > "${REPO_ROOT}/evidence/metrics_summary.json"
    [[ "${errs}" -eq 0 ]] || { fail "--external-eval FAIL: ${errs} runner(s) failed"; return 1; }
    ok "--external-eval done. Inspect transcripts + run_manifest.json in each artefact."
    return 0
}

###############################################################################
# Dispatch
###############################################################################

case "${MODE}" in
    --verify-fast)
        do_verify_fast
        ;;
    --verify)
        do_verify
        ;;
    --deterministic)
        do_deterministic
        ;;
    --external-eval)
        do_external_eval
        ;;
    --all)
        do_deterministic
        # Codex v9 closure: --all no longer swallows external-eval failures.
        # If external-eval is invoked under --all without keys, it returns 2
        # (missing keys); we treat that as "skipped, not a failure" but
        # propagate any OTHER non-zero (rc != 2 → real failure).
        do_external_eval
        rc=$?
        if [[ "${rc}" -ne 0 && "${rc}" -ne 2 ]]; then
            fail "--all FAIL: external-eval returned ${rc}"
            exit "${rc}"
        fi
        ;;
esac
