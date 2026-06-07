"""TOOL-051: fastapi_doctor — holistic FastAPI health-check and audit engine.

Orchestrates every VERIFY tool (TOOL-028..034), classifies findings by severity
(CRITICAL / HIGH / MEDIUM / LOW), generates an ordered fix plan where every item
references a specific SKILL-001 tool, recommends EXTEND tools the project lacks,
and compares against a committed baseline for CI-friendly delta gating.

Modes:
    ``full``     — run all 7 VERIFY tool wrappers (default)
    ``quick``    — run top-3 priority checkers, return at most 10 findings
    ``targeted`` — run only checkers matching ``category`` filter

Report formats:
    ``markdown``, ``html``, ``json``

Idempotency: the doctor never writes to the target project; it is fully read-only.

Example::

    from adapt.contracts import ToolInput
    from adapt.proactive.fastapi_doctor import fastapi_doctor

    result = fastapi_doctor(ToolInput(project_dir="/path/to/project"))
    print(result.status)   # "success"
    print(result.notes)    # markdown report
"""

from __future__ import annotations

import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult

# Implementation split across helper modules to honour the 500-LOC cap.
# Re-exported here so the public surface (and prior import paths) is unchanged.
from adapt.proactive.fastapi_doctor__impl1 import (  # noqa: F401
    Checker,
    CheckerRegistry,
    CheckerResult,
    Severity,
    classify_finding,
)
from adapt.proactive.fastapi_doctor__impl2 import (  # noqa: F401
    BaselineComparator,
    ExtendRecommender,
    FixPlanBuilder,
)
from adapt.proactive.fastapi_doctor__impl3 import (  # noqa: F401
    DoctorOrchestrator,
    ReportRenderer,
)

__all__ = [
    "BaselineComparator",
    "Checker",
    "CheckerRegistry",
    "CheckerResult",
    "DoctorOrchestrator",
    "ExtendRecommender",
    "FixPlanBuilder",
    "MCP_TOOL",
    "ReportRenderer",
    "Severity",
    "classify_finding",
    "fastapi_doctor",
]


MCP_TOOL = {
    "name": "fastapi_resiliency_analyze_doctor",
    "description": "Holistic FastAPI health-check and audit engine.",
    "tags": ["proactive"],
    "entry": "fastapi_doctor",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def fastapi_doctor(inp: ToolInput) -> ToolResult:
    """Run a holistic FastAPI health check over an existing project.

    Orchestrates all 7 VERIFY tools (TOOL-028..034), classifies findings by
    severity, generates a prioritised fix plan referencing specific SKILL-001
    tools, recommends EXTEND tools the project lacks, and compares against a
    committed baseline for CI delta gating.

    This tool is PROACTIVE and fully read-only: it never modifies the target
    project's files.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path). ``dry_run``
            is accepted but has no effect since the doctor is always read-only.

    Returns:
        ``ToolResult`` with:
        - ``status``: always ``"success"`` unless project_dir is invalid.
        - ``notes``: Markdown-formatted full report.
        - ``warnings``: New CRITICAL findings since last baseline.
        - ``next_steps``: Top fix-plan commands in copy-paste format.
        - ``execution_time_ms``: Wall-clock time in milliseconds.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)

    if not project.exists():
        return ToolResult(
            status="error",
            error=f"project_dir does not exist: {inp.project_dir}",
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] fastapi_doctor is read-only; no baseline file would be written.",
                "[dry_run] Re-run without dry_run=True to produce the full report.",
            ],
            next_steps=["Re-run without dry_run=True to run all VERIFY tool checks."],
            execution_time_ms=_elapsed_ms(start),
        )

    mode = getattr(inp, "mode", "full") or "full"
    report_format = getattr(inp, "report_format", "markdown") or "markdown"
    emit_fix_plan = getattr(inp, "emit_fix_plan", True)
    include_extend = getattr(inp, "include_extend", True)
    only_category = getattr(inp, "only_category", None)

    orchestrator = DoctorOrchestrator(
        project_dir=inp.project_dir,
        mode=mode,
        emit_fix_plan=emit_fix_plan,
        include_extend=include_extend,
        only_category=only_category,
    )
    report = orchestrator.run()

    renderer = ReportRenderer(report)
    rendered = renderer.render(report_format)

    summary = report.get("summary", {})
    delta = report.get("baseline_delta", {})
    new_critical = delta.get("new", 0)

    warnings: list[str] = []
    if new_critical > 0:
        warnings.append(
            f"{new_critical} new CRITICAL finding(s) since last baseline — run fix plan item 1 immediately."
        )
    for f in report.get("findings", []):
        if f.get("severity") == "CRITICAL":
            warnings.append(f"[CRITICAL] {f['title']}")

    next_steps: list[str] = [item["run_command"] for item in report.get("fix_plan", [])[:5]]
    if not next_steps:
        next_steps = ["No fix plan items — project looks healthy."]

    notes: list[str] = [rendered]
    notes.append(
        f"Scan complete: {summary.get('total', 0)} findings "
        f"(CRITICAL={summary.get('CRITICAL', 0)}, HIGH={summary.get('HIGH', 0)}, "
        f"MEDIUM={summary.get('MEDIUM', 0)}, LOW={summary.get('LOW', 0)})"
    )
    if report.get("skipped_checkers"):
        skipped_names = [s["name"] for s in report["skipped_checkers"]]
        notes.append(f"Skipped checkers: {', '.join(skipped_names)}")

    return ToolResult(
        status="success",
        notes=notes,
        warnings=warnings,
        next_steps=next_steps,
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start* (from ``time.monotonic()``).

    Args:
        start: Start time from ``time.monotonic()``.

    Returns:
        Elapsed time in milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)
