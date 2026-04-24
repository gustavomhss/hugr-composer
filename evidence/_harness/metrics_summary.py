"""Emit evidence/metrics_summary.json — the dashboard consumed by EVIDENCE.md.

Reads every deterministic artefact + every external-eval run_manifest.json
and produces a single JSON object suitable for machine consumption.

Usage (from repo root):
    .venv/bin/python evidence/_harness/metrics_summary.py > evidence/metrics_summary.json

Intended to be called by reproduce.sh after the artefacts regenerate.
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DET = REPO_ROOT / "evidence" / "deterministic"
EXT = REPO_ROOT / "evidence" / "external-eval"


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=REPO_ROOT, text=True).strip()


def _read_text(p: pathlib.Path) -> str:
    return p.read_text() if p.exists() else ""


def _read_json(p: pathlib.Path) -> dict:
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _grep(regex: str, text: str) -> str | None:
    m = re.search(regex, text, re.MULTILINE)
    return m.group(0) if m else None


def _contract_check() -> dict:
    t = _read_text(DET / "contract_check.log")
    line = _grep(r"^\s*\d+/\d+ contract items satisfied.*$", t) or ""
    m = re.search(r"(\d+)/(\d+)", line)
    return {
        "summary_line": line.strip() or "MISSING",
        "passed": int(m.group(1)) if m else None,
        "total": int(m.group(2)) if m else None,
        "all_green": "ALL GREEN" in t,
    }


def _pytest() -> dict:
    t = _read_text(DET / "pytest_full_sweep.log")
    line = _grep(r"^\d+ passed.*in \d+\.\d+s.*$", t) or ""
    m = re.search(r"(\d+) passed(?:, (\d+) skipped)?(?:, (\d+) failed)?", line)
    return {
        "summary_line": line.strip() or "MISSING",
        "passed": int(m.group(1)) if m else None,
        "skipped": int(m.group(2)) if m and m.group(2) else 0,
        "failed": int(m.group(3)) if m and m.group(3) else 0,
    }


def _manifest_idempotence() -> dict:
    t = _read_text(DET / "manifest_idempotence.log")
    return {
        "idempotent": "idempotent: stable hash matches across two builds" in t,
        "stable_hash": (_grep(r"stable_hash=[0-9a-f]+", t) or "").replace("stable_hash=", "") or None,
    }


def _framework_free() -> dict:
    t = _read_text(DET / "framework_free_proof.log")
    reg = _grep(r"registered_primitives:\s*(\d+)", t) or ""
    vio = _grep(r"framework_imports_found:\s*(\d+)", t) or ""
    return {
        "registered_primitives": int(reg.split()[-1]) if reg else None,
        "framework_imports_found": int(vio.split()[-1]) if vio else None,
        "pass": "PASS" in t,
    }


def _loc_budget() -> dict:
    d = _read_json(DET / "loc_budget_stats.json")
    summary = d.get("summary", {})
    return {
        "examples_scanned": summary.get("examples_scanned"),
        "app_loc_per_handler_p95": summary.get("app_loc_per_handler", {}).get("p95"),
        "total_handlers": summary.get("total_handlers"),
    }


def _scan_summary(name: str, err_key: str) -> dict:
    d = _read_json(DET / name / "SUMMARY.json")
    rows = d.get("per_example", [])
    worst = max((r.get(err_key, 0) for r in rows), default=0)
    return {
        "examples": len(rows),
        "worst_high_or_error": worst,
        "clean": worst == 0,
    }


def _install_docker() -> dict:
    t = _read_text(DET / "install_docker_run.log")
    return {
        "status": "skipped-locally" if "SKIPPED-LOCALLY" in t else ("pass" if "ALL SMOKE TESTS PASSED" in t else "fail"),
    }


def _external_eval_status(subdir: str) -> dict:
    manifest = EXT / subdir / "run_manifest.json"
    if not manifest.exists():
        return {"status": "not-yet-run", "manifest_present": False}
    d = _read_json(manifest)
    return {
        "status": d.get("_status", "unknown"),
        "manifest_present": True,
        "model_id": (d.get("model") or {}).get("id", ""),
        "commit_pinned": d.get("commit", ""),
    }


def _per_surface_passed(name: str) -> dict:
    d = _read_json(DET / f"{name}.json")
    s = d.get("summary", {})
    # Different probes use different key conventions for "did all checks pass":
    #   passed (most), overall_passed (per_tool_pattern_audit)
    passed = s.get("passed")
    if passed is None:
        passed = s.get("overall_passed", False)
    return {
        "passed": passed,
        "total": s.get("total")
            or s.get("primitives_scanned")
            or s.get("examples_scanned")
            or s.get("total_modules")
            or s.get("per_spec_count")
            or d.get("primitives_scanned")
            or d.get("adapters_scanned")
            or d.get("modules_scanned")
            or d.get("tools_scanned")
            or d.get("examples_scanned"),
    }


def _emitted_glue() -> dict:
    d = _read_json(DET / "emitted_glue_loc.json")
    s = d.get("summary", {})
    pa = s.get("product_alignment", {})
    return {
        "probe_passed": s.get("passed"),
        "tools_invoked_successfully": s.get("tools_invoked_successfully"),
        "p95_loc_per_handler": s.get("loc_per_handler_p95"),
        "tools_with_venous_imports": s.get("tools_with_venous_imports"),
        "aligns_with_product_§6_1": pa.get("aligns_with_product_§6_1"),
        "aligns_with_product_§A2": pa.get("aligns_with_product_§A2"),
    }


def _generator_idempotence() -> dict:
    d = _read_json(DET / "generator_idempotence.json")
    s = d.get("summary", {})
    return {
        "profiles_idempotent": s.get("profiles_idempotent"),
        "total_profiles": s.get("total_profiles"),
        "passed": s.get("passed"),
    }


def _framework_free_runtime() -> dict:
    d = _read_json(DET / "framework_free_runtime.json")
    s = d.get("summary", {})
    return {
        "imported_clean": s.get("imported_clean"),
        "blocked_framework_imports": s.get("blocked_framework_imports"),
        "passed": s.get("passed"),
    }


def _suite_log_summary(name: str) -> dict:
    t = _read_text(DET / "test_suites" / f"{name}.log")
    if not t:
        return {"present": False}
    last = t.strip().splitlines()[-1] if t.strip() else ""
    return {"present": True, "summary_line": last[:160]}


def main() -> None:
    commit = _git("rev-parse", "HEAD")
    tree = _git("rev-parse", "HEAD^{tree}")
    out = {
        "_meta": {
            "commit": commit,
            "tree": tree,
            "generated": subprocess.check_output(["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"], text=True).strip(),
            "source": "evidence/_harness/metrics_summary.py",
        },
        "deterministic": {
            "contract_check": _contract_check(),
            "pytest_full_sweep": _pytest(),
            "manifest_idempotence": _manifest_idempotence(),
            "framework_free_proof": _framework_free(),
            "framework_free_runtime": _framework_free_runtime(),
            "loc_budget_stats": _loc_budget(),
            "emitted_glue_loc": _emitted_glue(),
            "generator_idempotence": _generator_idempotence(),
            "bandit_scan": _scan_summary("bandit_scan", "high"),
            "semgrep_scan": _scan_summary("semgrep_scan", "error"),
            "install_docker_run": _install_docker(),
            "per_surface_attestations": {
                "per_tool_pattern_audit": _per_surface_passed("per_tool_pattern_audit"),
                "per_primitive_attestation": _per_surface_passed("per_primitive_attestation"),
                "fastapi_adapter_matrix": _per_surface_passed("fastapi_adapter_matrix"),
                "module_integration_matrix": _per_surface_passed("module_integration_matrix"),
                "per_example_pytest_matrix": _per_surface_passed("per_example_pytest_matrix"),
                "benchmark_scores": _per_surface_passed("benchmark_scores"),
            },
            "test_suites": {
                "boot_test": _suite_log_summary("boot_test"),
                "property_tests": _suite_log_summary("property_tests"),
                "e2e_sqlite": _suite_log_summary("e2e_sqlite"),
                "stress_test": _suite_log_summary("stress_test"),
                "cross_composition": _suite_log_summary("cross_composition"),
            },
        },
        "external_eval": {
            "single_shot_benchmark": _external_eval_status("single_shot_benchmark"),
            "cross_model_fnf": _external_eval_status("cross_model_fnf"),
            "counterfactual": _external_eval_status("counterfactual"),
            "reviewer_signoffs": {
                "signoffs_present": len(list((EXT / "reviewer_signoffs").glob("*.md"))) - 1,  # minus README
                "target": "2-of-3 YES per LAUNCH.md §5.1",
            },
        },
    }
    print(json.dumps(out, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
