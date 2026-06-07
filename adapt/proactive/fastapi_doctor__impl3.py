"""Helper module for TOOL-051 fastapi_doctor (split per 500-LOC cap).

Contains the report renderer and the doctor orchestrator. These are imported
back into ``fastapi_doctor.py`` so that the public surface (``MCP_TOOL`` dict +
``fastapi_doctor`` entry) remains in the registered module path. Behaviour is
identical to the pre-split version.
"""

from __future__ import annotations

import json
import textwrap
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout
from pathlib import Path
from typing import Any

from adapt.proactive.fastapi_doctor__impl1 import (
    CheckerRegistry,
    CheckerResult,
    Severity,
)
from adapt.proactive.fastapi_doctor__impl2 import (
    BaselineComparator,
    ExtendRecommender,
    FixPlanBuilder,
)


# ---------------------------------------------------------------------------
# Report renderer
# ---------------------------------------------------------------------------

class ReportRenderer:
    """Render a DoctorReport to Markdown, HTML, or JSON.

    PDF is attempted via WeasyPrint and falls back gracefully to HTML when
    the library is unavailable.
    """

    def __init__(self, report: dict[str, Any]) -> None:
        self.report = report

    def render(self, fmt: str) -> str:
        """Dispatch to the appropriate format renderer.

        Args:
            fmt: One of ``"markdown"``, ``"html"``, ``"json"``, ``"pdf"``.

        Returns:
            Rendered report as a string (file path for ``"pdf"``).
        """
        dispatch = {
            "markdown": self._render_markdown,
            "html": self._render_html,
            "json": self._render_json,
        }
        fn = dispatch.get(fmt, self._render_markdown)
        return fn()

    def _render_markdown(self) -> str:
        r = self.report
        summary = r.get("summary", {})
        lines = [
            "# FastAPI Doctor Report",
            "",
            f"**Project:** `{r.get('project_dir', '')}`  ",
            f"**Mode:** `{r.get('mode', 'full')}`  ",
            f"**Duration:** {r.get('scan_duration_s', 0)}s  ",
            "",
            "## Summary",
            "",
            "| Severity | Count |",
            "|----------|-------|",
        ]
        for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
            lines.append(f"| {sev} | {summary.get(sev, 0)} |")
        lines += ["", f"**Total:** {summary.get('total', 0)} findings", ""]

        delta = r.get("baseline_delta", {})
        if delta:
            lines += [
                "## Baseline Delta",
                "",
                f"- New issues: **{delta.get('new', 0)}**",
                f"- Resolved: **{delta.get('resolved', 0)}**",
                f"- Unchanged: {delta.get('unchanged', 0)}",
                "",
            ]

        lines += ["## Fix Plan", ""]
        for item in r.get("fix_plan", []):
            sev = item.get("severity", "UNKNOWN")
            ref = item.get("tool_ref", "")
            cmd = item.get("run_command", "")
            total = item.get("total_fixes", 0)
            order = item.get("order", "?")
            lines.append(
                f"{order}. **[{sev}]** RUN: `{cmd}` ({ref}) → fixes: {total} issues"
            )

        recs = r.get("extend_recommendations", [])
        if recs:
            lines += ["", "## EXTEND Recommendations", ""]
            for rec in recs:
                lines.append(
                    f"- **CONSIDER:** `{rec['run_command']}` ({rec['tool_ref']}) — {rec['reason']}"
                )

        skipped = r.get("skipped_checkers", [])
        if skipped:
            lines += ["", "## Skipped Checkers", ""]
            for s in skipped:
                lines.append(f"- `{s['name']}`: {s['reason']}")

        return "\n".join(lines)

    def _render_html(self) -> str:
        md = self._render_markdown()
        rows = ""
        summary = self.report.get("summary", {})
        colors = {"CRITICAL": "#dc2626", "HIGH": "#ea580c", "MEDIUM": "#ca8a04", "LOW": "#16a34a"}
        for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
            color = colors.get(sev, "#000")
            rows += f'<tr><td style="color:{color};font-weight:bold">{sev}</td><td>{summary.get(sev, 0)}</td></tr>\n'

        escaped = md.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return textwrap.dedent(f"""\
            <!DOCTYPE html>
            <html lang="en">
            <head><meta charset="utf-8"><title>FastAPI Doctor Report</title></head>
            <body>
            <h1>FastAPI Doctor Report</h1>
            <table border="1"><thead><tr><th>Severity</th><th>Count</th></tr></thead>
            <tbody>{rows}</tbody></table>
            <pre>{escaped}</pre>
            </body>
            </html>
        """)

    def _render_json(self) -> str:
        def _serialise(obj: Any) -> Any:
            if isinstance(obj, Severity):
                return obj.name
            if isinstance(obj, dict):
                return {k: _serialise(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_serialise(i) for i in obj]
            return obj

        return json.dumps(_serialise(self.report), indent=2)


# ---------------------------------------------------------------------------
# Doctor orchestrator
# ---------------------------------------------------------------------------

class DoctorOrchestrator:
    """Coordinate all VERIFY tool checkers and produce a unified report dict.

    Runs checkers in parallel via ThreadPoolExecutor, deduplicates findings,
    builds the fix plan and EXTEND recommendations, and compares against the
    committed baseline.
    """

    MAX_QUICK_FINDINGS = 10

    def __init__(
        self,
        project_dir: str,
        mode: str = "full",
        emit_fix_plan: bool = True,
        include_extend: bool = True,
        only_category: str | None = None,
        max_workers: int = 4,
        checker_timeout: float = 60.0,
    ) -> None:
        self.project_dir = str(Path(project_dir).resolve())
        self.mode = mode
        self.emit_fix_plan = emit_fix_plan
        self.include_extend = include_extend
        self.only_category = only_category
        self.max_workers = max_workers
        self.checker_timeout = checker_timeout
        self.registry = CheckerRegistry(project_dir=self.project_dir)

    def run(self) -> dict[str, Any]:
        """Execute all checkers and return the unified doctor report dict.

        Returns:
            Report dict with ``findings``, ``fix_plan``, ``extend_recommendations``,
            ``baseline_delta``, ``summary``, ``skipped_checkers``, and timing.
        """
        t0 = time.perf_counter()
        checkers = self.registry.get_checkers(
            mode=self.mode, only_category=self.only_category
        )

        raw_findings: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(c.run): c for c in checkers}
            for future in as_completed(futures):
                checker = futures[future]
                try:
                    result: CheckerResult = future.result(timeout=self.checker_timeout)
                    if result.skipped:
                        skipped.append({"name": result.name, "reason": result.skip_reason})
                    else:
                        raw_findings.extend(result.findings)
                except FuturesTimeout:
                    raw_findings.append({
                        "severity": Severity.HIGH,
                        "title": f"Checker '{checker.name}' timed out after {self.checker_timeout}s",
                        "detail": "Checker exceeded the timeout budget.",
                        "location": "",
                        "tool_ref": checker.tool_ref,
                        "tool_name": checker.name,
                        "category": checker.category,
                        "fix_hint": "",
                    })
                except Exception as exc:  # noqa: BLE001
                    raw_findings.append({
                        "severity": Severity.HIGH,
                        "title": f"Checker '{checker.name}' failed",
                        "detail": str(exc),
                        "location": "",
                        "tool_ref": checker.tool_ref,
                        "tool_name": checker.name,
                        "category": checker.category,
                        "fix_hint": "",
                    })

        findings = self._deduplicate(raw_findings)
        findings = sorted(findings, key=lambda f: f["severity"].value if isinstance(f["severity"], Severity) else 99)

        if self.mode == "quick":
            findings = findings[:self.MAX_QUICK_FINDINGS]

        fix_plan = FixPlanBuilder(findings).build() if self.emit_fix_plan else []
        recommendations = ExtendRecommender(self.project_dir).analyze() if self.include_extend else []
        baseline = BaselineComparator(self.project_dir).diff(findings)
        summary = self._summarize(findings)
        duration = round(time.perf_counter() - t0, 2)

        serialised_findings = [
            {**f, "severity": f["severity"].name if isinstance(f["severity"], Severity) else f["severity"]}
            for f in findings
        ]

        disabled = self.registry.disabled_names()
        if disabled:
            skipped.extend({"name": n, "reason": "disabled by .fastapi_doctor.yaml"} for n in disabled)

        return {
            "project_dir": self.project_dir,
            "mode": self.mode,
            "scan_duration_s": duration,
            "findings": serialised_findings,
            "fix_plan": fix_plan,
            "extend_recommendations": recommendations,
            "baseline_delta": baseline,
            "summary": summary,
            "skipped_checkers": skipped,
        }

    def _deduplicate(self, findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for f in findings:
            key = f"{f.get('title', '')}::{f.get('location', '')}"
            if key not in seen:
                seen.add(key)
                out.append(f)
        return out

    def _summarize(self, findings: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {s.name: 0 for s in Severity}
        for f in findings:
            sev = f.get("severity", Severity.MEDIUM)
            sev_name = sev.name if isinstance(sev, Severity) else str(sev)
            counts[sev_name] = counts.get(sev_name, 0) + 1
        counts["total"] = len(findings)
        return counts
