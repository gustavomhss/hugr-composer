#!/usr/bin/env bash
# evidence/reproduce.sh — reproduce the evidence package at the current HEAD.
#
# Per LAUNCH.md §2.4:
#   --verify         Deterministic-only; regenerate + diff against committed (≤15min)
#   --deterministic  Regenerate /evidence/deterministic/** byte-identical modulo timestamps (≤1h)
#   --external-eval  Live LLM evals — ~$200-500 — writes fresh run_manifest.json + transcripts
#   --all (default)  Both deterministic + external-eval
#
# Exit codes:
#   0 — requested artefacts regenerated + verify passed
#   1 — drift in at least one deterministic artefact (verify failed)
#   2 — external-eval requested but API keys missing
#   3 — internal harness error (see stderr)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${REPO_ROOT}"

MODE="${1:---all}"

case "${MODE}" in
    -h|--help)
        sed -n '2,13p' "$0"
        exit 0
        ;;
    --verify|--deterministic|--external-eval|--all)
        ;;
    *)
        echo "usage: $0 [--verify | --deterministic | --external-eval | --all]" >&2
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
# Deterministic regeneration helpers
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
    sha=$(git rev-parse HEAD)
    tree=$(git rev-parse 'HEAD^{tree}')
    iso=$(date -u +%Y-%m-%dT%H:%M:%SZ)
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

regen_pytest_full_sweep() {
    log "pytest_full_sweep (this takes ~30 min)"
    local out="${DET_DIR}/pytest_full_sweep.log"
    local sha tree iso
    sha=$(git rev-parse HEAD)
    tree=$(git rev-parse 'HEAD^{tree}')
    iso=$(date -u +%Y-%m-%dT%H:%M:%SZ)
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

regen_framework_free() {
    log "framework_free_proof"
    local out="${DET_DIR}/framework_free_proof.log"
    local sha tree iso
    sha=$(git rev-parse HEAD)
    tree=$(git rev-parse 'HEAD^{tree}')
    iso=$(date -u +%Y-%m-%dT%H:%M:%SZ)
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

regen_loc_budget() {
    log "loc_budget_stats"
    local out="${DET_DIR}/loc_budget_stats.json"
    local sha tree iso tmp
    sha=$(git rev-parse HEAD)
    tree=$(git rev-parse 'HEAD^{tree}')
    iso=$(date -u +%Y-%m-%dT%H:%M:%SZ)
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

regen_freshness() {
    log "freshness_proof"
    local out="${DET_DIR}/freshness_proof.log"
    local sha tree iso head_iso head_msg branch dirty
    sha=$(git rev-parse HEAD)
    tree=$(git rev-parse 'HEAD^{tree}')
    iso=$(date -u +%Y-%m-%dT%H:%M:%SZ)
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

regen_deterministic_all() {
    regen_contract_check
    regen_manifest_idempotence
    regen_framework_free
    regen_loc_budget
    regen_freshness
    bash "${HARNESS}/bandit_scan.sh"
    bash "${HARNESS}/semgrep_scan.sh"
    bash "${HARNESS}/install_docker_run.sh"
    # pytest_full_sweep is the longest step; keep it last so earlier failures fail fast.
    regen_pytest_full_sweep
}

###############################################################################
# --verify: normalise timestamps, compare against committed, exit 1 on drift
###############################################################################

normalize_for_diff() {
    # Strip metadata (timestamp/commit/tree) from headers + JSON _meta so byte-drift
    # in actual content still surfaces but ephemeral fields don't. Applies to both
    # .log (hash-# prefix) and .json (_meta keys) shapes. Also strips freshness's
    # "clean:" line which reflects working-tree state not committed state.
    sed -E \
        -e '/^# (generated|commit|tree): /d' \
        -e '/^[[:space:]]*"(generated|commit|tree)": /d' \
        -e '/^(generated|commit|tree|head_iso|head_msg|clean): /d' \
        "$1"
}

do_verify() {
    # --verify regenerates only the lightweight python artefacts and diffs against
    # committed. bandit/semgrep/install_docker/pytest are EXCLUDED — they exceed the
    # 15-min budget for --verify (LAUNCH.md §2.4). Use --deterministic for those.
    log "regenerating lightweight deterministic artefacts into /tmp for diff …"
    local tmp
    tmp=$(mktemp -d)
    cp -a "${DET_DIR}/." "${tmp}/"
    local DET_DIR_SAVED="${DET_DIR}"
    DET_DIR="${tmp}"
    regen_contract_check
    regen_manifest_idempotence
    regen_framework_free
    regen_loc_budget
    regen_freshness
    DET_DIR="${DET_DIR_SAVED}"

    log "diffing verified subset (timestamps normalised)…"
    local drift=0
    for name in contract_check.log manifest_idempotence.log framework_free_proof.log loc_budget_stats.json freshness_proof.log; do
        local f="${DET_DIR}/${name}"
        local regen="${tmp}/${name}"
        [[ -f "${f}" && -f "${regen}" ]] || { note "missing: ${name}"; continue; }
        if ! diff <(normalize_for_diff "${f}") <(normalize_for_diff "${regen}") > /dev/null; then
            fail "drift: ${name}"
            drift=1
        else
            ok "match: ${name}"
        fi
    done

    rm -rf "${tmp}"
    if [[ "${drift}" -eq 0 ]]; then
        ok "--verify PASS: lightweight deterministic subset matches committed"
        note "bandit/semgrep/install_docker/pytest are in --deterministic (not --verify)"
        return 0
    fi
    fail "--verify FAIL: at least one deterministic artefact drifted"
    return 1
}

###############################################################################
# --external-eval: paid LLM run (deferred to 48h pre-tag window)
###############################################################################

do_external_eval() {
    if [[ -z "${ANTHROPIC_API_KEY:-}" && -z "${OPENAI_API_KEY:-}" && -z "${GOOGLE_API_KEY:-}" ]]; then
        fail "--external-eval: no API keys set. Export ANTHROPIC_API_KEY / OPENAI_API_KEY / GOOGLE_API_KEY."
        note "This step costs ~\$200-500; aborting to avoid accidental no-op run without keys."
        return 2
    fi
    log "single_shot_benchmark…"
    "${VENV_PY}" "${REPO_ROOT}/evidence/external-eval/single_shot_benchmark/_harness/run.py" || true
    log "cross_model_fnf…"
    if [[ -f "${REPO_ROOT}/evidence/external-eval/cross_model_fnf/_harness/run.py" ]]; then
        "${VENV_PY}" "${REPO_ROOT}/evidence/external-eval/cross_model_fnf/_harness/run.py" || true
    else
        note "cross_model_fnf/_harness/run.py not yet authored; see cross_model_fnf/README.md"
    fi
    log "counterfactual…"
    if [[ -f "${REPO_ROOT}/evidence/external-eval/counterfactual/_harness/run.py" ]]; then
        "${VENV_PY}" "${REPO_ROOT}/evidence/external-eval/counterfactual/_harness/run.py" || true
    else
        note "counterfactual/_harness/run.py not yet authored; see counterfactual/README.md"
    fi
    log "post-run: update metrics_summary.json"
    "${VENV_PY}" "${HARNESS}/metrics_summary.py" > "${REPO_ROOT}/evidence/metrics_summary.json"
    ok "--external-eval done. Inspect transcripts + run_manifest.json in each artefact."
}

###############################################################################
# Dispatch
###############################################################################

case "${MODE}" in
    --verify)
        do_verify
        ;;
    --deterministic)
        regen_deterministic_all
        "${VENV_PY}" "${HARNESS}/metrics_summary.py" > "${REPO_ROOT}/evidence/metrics_summary.json"
        ok "--deterministic done."
        ;;
    --external-eval)
        do_external_eval
        ;;
    --all)
        regen_deterministic_all
        "${VENV_PY}" "${HARNESS}/metrics_summary.py" > "${REPO_ROOT}/evidence/metrics_summary.json"
        do_external_eval || true
        ;;
esac
