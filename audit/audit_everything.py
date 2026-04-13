"""Master audit — runs all layers, produces timestamped Markdown report.

Layers:
    L1: Correctness  — parse, tests, orchestrator smoke
    L2: Brutal       — coverage ratio, long fns, stubs, file size
    Security         — secrets, .env, .gitignore
    Quality          — inventory, docstrings, duplicates
    E2E              — generate project, run adapt tools, validate

Usage::

    PYTHONPATH=. python3 audit/audit_everything.py           # full audit
    PYTHONPATH=. python3 audit/audit_everything.py --e2e-only
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

SKILL_ROOT = Path(__file__).parent.parent
REPORTS_DIR = SKILL_ROOT / "audit" / "reports"

# ---------------------------------------------------------------------------
# Import sibling audit modules
# ---------------------------------------------------------------------------

sys.path.insert(0, str(SKILL_ROOT))

from audit.audit_l1 import audit_l1_correctness          # noqa: E402
from audit.audit_l2 import audit_l2_brutal                # noqa: E402
from audit.audit_security import audit_security           # noqa: E402
from audit.audit_quality import audit_quality             # noqa: E402


# ---------------------------------------------------------------------------
# E2E audit
# ---------------------------------------------------------------------------

def audit_e2e() -> dict:
    """E2E: generate project, run 5 adapt tools, validate all .py files.

    Returns:
        Result dict with ``passed`` bool and per-step details.
    """
    steps: list[dict] = []

    # Step 1: generate project
    try:
        from generators.orchestrator import generate_project  # type: ignore
    except ImportError as exc:
        return {
            "passed": False,
            "steps": [{"name": "import_orchestrator", "ok": False, "error": str(exc)}],
        }

    with tempfile.TemporaryDirectory(prefix="_skill001_e2e_") as tmpdir:
        out = Path(tmpdir) / "e2e_project"
        try:
            t0 = time.monotonic()
            result = generate_project(
                str(out),
                name="e2e",
                models={"Item": {"name": "str", "price": "float"}},
                with_auth=True,
            )
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            steps.append({
                "name": "generate_project",
                "ok": True,
                "files_created": result.get("total_files", len(result.get("files_created", []))),
                "elapsed_ms": elapsed_ms,
            })
        except Exception as exc:
            steps.append({"name": "generate_project", "ok": False, "error": str(exc)})
            return {"passed": False, "steps": steps}

        # Step 2: run 5 adapt tools on the generated project
        tools_to_run = [
            ("adapt.verify.dependency_audit", "dependency_audit"),
            ("adapt.verify.security_scan", "security_scan"),
            ("adapt.operate.dead_code_finder", "dead_code_finder"),
            ("adapt.proactive.fastapi_doctor", "fastapi_doctor"),
            ("adapt.verify.schema_coverage", "schema_coverage"),
        ]

        from adapt.contracts import ToolInput  # type: ignore

        tool_input = ToolInput(project_dir=str(out), dry_run=True)
        for module_path, fn_name in tools_to_run:
            try:
                mod = __import__(module_path, fromlist=[fn_name])
                fn = getattr(mod, fn_name)
                t0 = time.monotonic()
                tool_result = fn(tool_input)
                elapsed_ms = int((time.monotonic() - t0) * 1000)
                ok = tool_result.status in ("success", "no_op")
                steps.append({
                    "name": fn_name,
                    "ok": ok,
                    "status": tool_result.status,
                    "elapsed_ms": elapsed_ms,
                })
            except Exception as exc:
                steps.append({"name": fn_name, "ok": False, "error": str(exc)})

        # Step 3: validate all .py files in generated project parse correctly
        import ast

        parse_errors: list[str] = []
        checked = 0
        for py_file in sorted(out.rglob("*.py")):
            checked += 1
            try:
                ast.parse(py_file.read_text(encoding="utf-8"))
            except SyntaxError as exc:
                parse_errors.append(f"{py_file.relative_to(out)}: {exc}")

        steps.append({
            "name": "validate_generated_py",
            "ok": len(parse_errors) == 0,
            "checked": checked,
            "parse_errors": parse_errors[:10],
        })

    all_ok = all(s["ok"] for s in steps)
    return {"passed": all_ok, "steps": steps}


# ---------------------------------------------------------------------------
# Git SHA helper
# ---------------------------------------------------------------------------

def _git_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(SKILL_ROOT),
            timeout=5,
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Markdown report builder
# ---------------------------------------------------------------------------

def _bool_icon(value: bool) -> str:
    return "✅" if value else "❌"


def _build_report(
    timestamp: str,
    git_sha: str,
    l1: dict,
    l2: dict,
    security: dict,
    quality: dict,
    e2e: dict | None,
    elapsed_s: float,
) -> str:
    lines: list[str] = []
    a = lines.append

    a(f"# SKILL-001 Audit Report")
    a(f"")
    a(f"**Timestamp:** {timestamp}")
    a(f"**Git SHA:** `{git_sha}`")
    a(f"**Elapsed:** {elapsed_s:.1f}s")
    a(f"")

    # Summary table
    a("## Summary")
    a("")
    a("| Layer | Result | Details |")
    a("|-------|--------|---------|")

    l1_ok = l1["passed"]
    a(f"| L1 Correctness | {_bool_icon(l1_ok)} {'PASS' if l1_ok else 'FAIL'} | "
      f"{l1['tests_passed']}/{l1['tests_run']} tests, "
      f"{len(l1.get('parse_errors', []))} parse errors |")

    l2_ok = l2["passed"]
    stubs_count = len(l2["stubs"]["findings"])
    long_fns = len(l2["long_functions"]["violations"])
    a(f"| L2 Brutal | {_bool_icon(l2_ok)} {'PASS' if l2_ok else 'FAIL'} | "
      f"coverage {l2['coverage_ratio']['ratio']}, "
      f"{long_fns} long fns, {stubs_count} stubs |")

    sec_ok = security["passed"]
    secret_count = len(security["hardcoded_secrets"]["findings"])
    a(f"| Security | {_bool_icon(sec_ok)} {'PASS' if sec_ok else 'FAIL'} | "
      f"{secret_count} secrets found |")

    qual_ok = quality["passed"]
    missing_docs = len(quality["docstrings"]["missing_docstrings"])
    dup_groups = len(quality["duplicates"]["duplicate_groups"])
    a(f"| Quality | {_bool_icon(qual_ok)} {'PASS' if qual_ok else 'FAIL'} | "
      f"{missing_docs} missing docstrings, {dup_groups} duplicate groups |")

    if e2e is not None:
        e2e_ok = e2e["passed"]
        steps_ok = sum(1 for s in e2e["steps"] if s["ok"])
        steps_total = len(e2e["steps"])
        a(f"| E2E | {_bool_icon(e2e_ok)} {'PASS' if e2e_ok else 'FAIL'} | "
          f"{steps_ok}/{steps_total} steps OK |")

    a("")

    # Counts section
    a("## Counts")
    a("")
    inv = quality["inventory"]
    a(f"- **Files:** {inv['file_count']}")
    a(f"- **LOC (adapt/):** {inv['total_loc']}")
    a(f"- **Functions:** {inv['total_functions']}")
    a(f"- **Tests run:** {l1['tests_run']}")
    a(f"- **Tests passed:** {l1['tests_passed']}")
    a(f"- **Coverage ratio:** {l2['coverage_ratio']['ratio']} "
      f"(test LOC / src LOC, threshold 0.30)")
    a("")

    # L1 details
    a("## L1 — Correctness")
    a("")
    if l1.get("parse_errors"):
        a("### Parse Errors")
        for e in l1["parse_errors"]:
            a(f"- `{e}`")
        a("")
    tr = l1.get("tests", {})
    if tr.get("failed_details"):
        a("### Failed Tests")
        for d in tr["failed_details"]:
            a(f"```\n{d[:400]}\n```")
        a("")
    smoke = l1.get("orchestrator_smoke", {})
    if smoke and not smoke.get("ok"):
        a("### Orchestrator Smoke Failure")
        a(f"- Error: `{smoke.get('error')}`")
        for m in smoke.get("missing_expected", []):
            a(f"- Missing: `{m}`")
        a("")

    # L2 details
    a("## L2 — Brutal")
    a("")
    if l2["long_functions"]["violations"]:
        a("### Long Functions (>50 LOC)")
        for v in l2["long_functions"]["violations"][:20]:
            a(f"- `{v}`")
        a("")
    if l2["stubs"]["findings"]:
        a("### Stubs / TODOs")
        for f in l2["stubs"]["findings"][:20]:
            a(f"- `{f}`")
        a("")
    if l2["file_sizes"]["violations"]:
        a("### Oversized Files")
        for v in l2["file_sizes"]["violations"]:
            a(f"- `{v}`")
        a("")

    # Security details
    a("## Security")
    a("")
    if security["hardcoded_secrets"]["findings"]:
        a("### Hardcoded Secrets")
        for f in security["hardcoded_secrets"]["findings"]:
            a(f"- `{f}`")
        a("")
    if not security["env_files"]["ok"]:
        a("### .env Files Found")
        for f in security["env_files"]["env_files_found"]:
            a(f"- `{f}`")
        a("")
    if not security["gitignore"]["ok"]:
        a("### .gitignore Missing .env Coverage")
        a(f"- Path: `{security['gitignore'].get('gitignore_path', 'not found')}`")
        a("")

    # Quality details
    a("## Quality")
    a("")
    if quality["docstrings"]["missing_docstrings"]:
        a("### Missing Docstrings (public functions)")
        for m in quality["docstrings"]["missing_docstrings"][:30]:
            a(f"- `{m}`")
        a("")
    if quality["duplicates"]["duplicate_groups"]:
        a("### Duplicate File Groups")
        for g in quality["duplicates"]["duplicate_groups"]:
            a(f"- {g}")
        a("")

    # E2E details
    if e2e is not None:
        a("## E2E")
        a("")
        a("| Step | Result | Notes |")
        a("|------|--------|-------|")
        for s in e2e["steps"]:
            icon = _bool_icon(s["ok"])
            notes = s.get("error", s.get("status", ""))
            if "elapsed_ms" in s:
                notes = f"{notes} ({s['elapsed_ms']}ms)" if notes else f"{s['elapsed_ms']}ms"
            a(f"| {s['name']} | {icon} | {notes} |")
        a("")

    # Verdict
    all_passed = l1_ok and l2_ok and sec_ok and qual_ok and (e2e is None or e2e["passed"])
    a("---")
    a("")
    if all_passed:
        a("## Final Verdict: ALL GREEN ✅")
    else:
        a("## Final Verdict: ISSUES FOUND ❌")
        a("")
        failed_layers = []
        if not l1_ok:
            failed_layers.append("L1 Correctness")
        if not l2_ok:
            failed_layers.append("L2 Brutal")
        if not sec_ok:
            failed_layers.append("Security")
        if not qual_ok:
            failed_layers.append("Quality")
        if e2e is not None and not e2e["passed"]:
            failed_layers.append("E2E")
        a(f"Failed layers: {', '.join(failed_layers)}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """Run all audits, write AUDIT_YYYY-MM-DD_HHMMSS.md, exit 0/1."""
    if argv is None:
        argv = sys.argv[1:]

    e2e_only = "--e2e-only" in argv
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    now = datetime.now(tz=timezone.utc)
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S UTC")
    date_tag = now.strftime("%Y-%m-%d_%H%M%S")
    git_sha = _git_sha()

    t_start = time.monotonic()

    if e2e_only:
        print("E2E audit only …")
        e2e = audit_e2e()
        # Produce minimal report
        elapsed_s = time.monotonic() - t_start
        report_path = REPORTS_DIR / f"AUDIT_{date_tag}_e2e.md"
        report_path.write_text(
            f"# SKILL-001 E2E Audit\n\n"
            f"**Timestamp:** {timestamp}\n**SHA:** `{git_sha}`\n\n"
            + ("ALL STEPS PASSED\n" if e2e["passed"] else "SOME STEPS FAILED\n")
            + "\n".join(
                f"- {'OK' if s['ok'] else 'FAIL'}: {s['name']} {s.get('error','')}"
                for s in e2e["steps"]
            ),
            encoding="utf-8",
        )
        print(f"Report: {report_path}")
        return 0 if e2e["passed"] else 1

    print("Running L1 …")
    l1 = audit_l1_correctness()

    print("Running L2 …")
    l2 = audit_l2_brutal()

    print("Running Security …")
    security = audit_security()

    print("Running Quality …")
    quality = audit_quality()

    print("Running E2E …")
    e2e = audit_e2e()

    elapsed_s = time.monotonic() - t_start

    report_md = _build_report(timestamp, git_sha, l1, l2, security, quality, e2e, elapsed_s)

    report_path = REPORTS_DIR / f"AUDIT_{date_tag}.md"
    report_path.write_text(report_md, encoding="utf-8")

    # Print summary to stdout
    print()
    print("=" * 60)
    print(f"SKILL-001 Full Audit — {timestamp}")
    print(f"Git SHA: {git_sha}")
    print(f"Elapsed: {elapsed_s:.1f}s")
    print("-" * 60)
    print(f"L1 Correctness:  {'PASS' if l1['passed'] else 'FAIL'}  "
          f"({l1['tests_passed']}/{l1['tests_run']} tests)")
    print(f"L2 Brutal:       {'PASS' if l2['passed'] else 'FAIL'}")
    print(f"Security:        {'PASS' if security['passed'] else 'FAIL'}")
    print(f"Quality:         {'PASS' if quality['passed'] else 'FAIL'}")
    print(f"E2E:             {'PASS' if e2e['passed'] else 'FAIL'}")
    all_passed = (
        l1["passed"]
        and l2["passed"]
        and security["passed"]
        and quality["passed"]
        and e2e["passed"]
    )
    print("-" * 60)
    print(f"VERDICT: {'ALL GREEN' if all_passed else 'ISSUES FOUND'}")
    print(f"Report:  {report_path}")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
