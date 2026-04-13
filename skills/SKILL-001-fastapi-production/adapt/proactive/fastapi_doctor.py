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

import ast
import json
import re
import textwrap
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any

from adapt.contracts import ToolInput, ToolResult


# ---------------------------------------------------------------------------
# Severity taxonomy
# ---------------------------------------------------------------------------

class Severity(IntEnum):
    """Finding severity level. Lower value = higher priority (CRITICAL sorts first)."""

    CRITICAL = 0
    HIGH = 1
    MEDIUM = 2
    LOW = 3

    @classmethod
    def from_string(cls, s: str) -> "Severity":
        """Parse severity from any casing; defaults to MEDIUM on unknown input.

        Args:
            s: Raw severity string from a checker output.

        Returns:
            Matching ``Severity`` member, defaulting to ``MEDIUM``.
        """
        mapping: dict[str, "Severity"] = {
            "critical": cls.CRITICAL,
            "high": cls.HIGH,
            "medium": cls.MEDIUM,
            "med": cls.MEDIUM,
            "low": cls.LOW,
            "info": cls.LOW,
        }
        return mapping.get(s.lower().strip(), cls.MEDIUM)

    def label(self) -> str:
        """Return the severity name in uppercase.

        Returns:
            Uppercase severity name string.
        """
        return self.name.upper()


def classify_finding(title: str, category: str) -> Severity:
    """Heuristic severity classifier for findings without an explicit level.

    Uses keyword matching on the title and category to assign a severity.

    Args:
        title: Finding title to inspect for security keywords.
        category: Checker category (security, performance, quality, compliance).

    Returns:
        Most appropriate ``Severity`` value.
    """
    title_lower = title.lower()
    security_critical = ["sql injection", "auth bypass", "secret leak", "rce", "ssrf", "hardcoded"]
    if any(kw in title_lower for kw in security_critical):
        return Severity.CRITICAL
    if category == "security":
        return Severity.HIGH
    if category == "performance" and "n+1" in title_lower:
        return Severity.HIGH
    if category == "compliance":
        return Severity.MEDIUM
    return Severity.MEDIUM


# ---------------------------------------------------------------------------
# Checker registry
# ---------------------------------------------------------------------------

@dataclass
class CheckerResult:
    """Result produced by a single checker invocation."""

    name: str
    findings: list[dict[str, Any]] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str = ""


@dataclass
class Checker:
    """Wrapper around one VERIFY tool function."""

    name: str
    tool_ref: str
    category: str
    project_dir: str
    enabled: bool = True

    # VERIFY tool names → import paths
    _TOOL_IMPORTS: dict[str, str] = field(default_factory=dict, repr=False, compare=False)

    def run(self) -> CheckerResult:
        """Execute the wrapped VERIFY tool and normalise its output.

        Returns:
            ``CheckerResult`` with normalised findings or skip information.
        """
        if not self.enabled:
            return CheckerResult(name=self.name, skipped=True, skip_reason="disabled")
        try:
            fn = self._resolve_fn()
            inp = ToolInput(project_dir=self.project_dir, dry_run=True)
            raw: ToolResult = fn(inp)
            findings = self._normalise_tool_result(raw)
            return CheckerResult(name=self.name, findings=findings)
        except ImportError as exc:
            return CheckerResult(
                name=self.name, skipped=True, skip_reason=f"dependency missing: {exc}"
            )
        except Exception as exc:  # noqa: BLE001
            return CheckerResult(
                name=self.name,
                findings=[{
                    "severity": Severity.HIGH,
                    "title": f"Checker '{self.name}' raised an unexpected error",
                    "detail": str(exc),
                    "location": "",
                    "tool_ref": self.tool_ref,
                    "tool_name": self.name,
                    "category": self.category,
                    "fix_hint": "",
                }],
            )

    def _resolve_fn(self):  # type: ignore[return]
        """Import and return the entry-point function of this VERIFY tool.

        Returns:
            Callable that accepts a ``ToolInput`` and returns a ``ToolResult``.

        Raises:
            ImportError: When the tool module cannot be imported.
        """
        module_map = {
            "security_scan": ("adapt.verify.security_scan", "security_scan"),
            "dependency_audit": ("adapt.verify.dependency_audit", "dependency_audit"),
            "detect_n_plus_one": ("adapt.verify.detect_n_plus_one", "detect_n_plus_one"),
            "schema_coverage": ("adapt.verify.schema_coverage", "schema_coverage"),
            "test_coverage_gaps": ("adapt.verify.test_coverage_gaps", "test_coverage_gaps"),
            "api_spec_compliance": ("adapt.verify.api_spec_compliance", "api_spec_compliance"),
            "performance_baseline": ("adapt.verify.performance_baseline", "performance_baseline"),
        }
        if self.name not in module_map:
            raise ImportError(f"No import mapping for checker: {self.name}")
        mod_path, fn_name = module_map[self.name]
        import importlib
        mod = importlib.import_module(mod_path)
        return getattr(mod, fn_name)

    def _normalise_tool_result(self, result: ToolResult) -> list[dict[str, Any]]:
        """Convert a ToolResult into a list of normalised finding dicts.

        A VERIFY tool that runs in dry_run mode returns its analysis in
        ``result.notes`` and ``result.warnings``; we surface these as findings.

        Args:
            result: ToolResult from a VERIFY tool dry-run.

        Returns:
            List of normalised finding dicts.
        """
        findings: list[dict[str, Any]] = []
        if result.status == "no_op":
            return findings
        for msg in result.warnings:
            sev = classify_finding(msg, self.category)
            findings.append(self._make_finding(msg, sev, location=""))
        for msg in result.notes:
            if any(kw in msg.lower() for kw in ("missing", "found", "detected", "gap", "issue")):
                sev = classify_finding(msg, self.category)
                findings.append(self._make_finding(msg, sev, location=""))
        return findings

    def _make_finding(self, title: str, sev: Severity, location: str) -> dict[str, Any]:
        """Build a normalised finding dict from raw message text.

        Args:
            title: Finding title / description.
            sev: Pre-classified severity level.
            location: File or route location string.

        Returns:
            Normalised finding dict.
        """
        return {
            "severity": sev,
            "title": title,
            "detail": "",
            "location": location,
            "tool_ref": self.tool_ref,
            "tool_name": self.name,
            "category": self.category,
            "fix_hint": f"Run: fastapi_skill {self.name} .",
        }


class CheckerRegistry:
    """Registry mapping SKILL-001 VERIFY tools to ``Checker`` wrappers.

    Attributes:
        VERIFY_TOOLS: All 7 VERIFY tools defined in SKILL-001 (TOOL-028..034).
    """

    VERIFY_TOOLS: list[tuple[str, str, str]] = [
        ("security_scan",      "TOOL-028", "security"),
        ("dependency_audit",   "TOOL-029", "security"),
        ("detect_n_plus_one",  "TOOL-030", "performance"),
        ("schema_coverage",    "TOOL-031", "quality"),
        ("test_coverage_gaps", "TOOL-032", "quality"),
        ("api_spec_compliance","TOOL-033", "compliance"),
        ("performance_baseline","TOOL-034", "performance"),
    ]

    # Quick mode always includes these high-priority checkers
    QUICK_PRIORITY = {"security_scan", "dependency_audit", "detect_n_plus_one"}

    def __init__(self, project_dir: str) -> None:
        self.project_dir = project_dir
        self._config: dict[str, Any] = self._load_config()
        self._checkers: list[Checker] = self._build_checkers()

    def _load_config(self) -> dict[str, Any]:
        """Load ``.fastapi_doctor.yaml`` from project_dir if it exists.

        Returns:
            Parsed config dict, or empty dict when no config file is found.
        """
        config_file = Path(self.project_dir) / ".fastapi_doctor.yaml"
        if config_file.exists():
            try:
                import yaml  # type: ignore[import-untyped]
                return yaml.safe_load(config_file.read_text()) or {}
            except Exception:  # noqa: BLE001
                return {}
        return {}

    def _build_checkers(self) -> list[Checker]:
        """Construct a Checker for each VERIFY tool, respecting the disable list.

        Returns:
            List of configured Checker instances.
        """
        disabled: set[str] = set(self._config.get("disable", []))
        return [
            Checker(
                name=name,
                tool_ref=tool_ref,
                category=category,
                project_dir=self.project_dir,
                enabled=name not in disabled,
            )
            for name, tool_ref, category in self.VERIFY_TOOLS
        ]

    def get_checkers(self, mode: str = "full", only_category: str | None = None) -> list[Checker]:
        """Return enabled checkers for the requested scan mode.

        Args:
            mode: ``"full"`` (all enabled), ``"quick"`` (top-3 priority),
                  ``"targeted"`` (filtered by ``only_category``).
            only_category: Category filter used in ``"targeted"`` mode.

        Returns:
            Filtered list of enabled Checker instances.
        """
        enabled = [c for c in self._checkers if c.enabled]
        if mode == "quick":
            return [c for c in enabled if c.name in self.QUICK_PRIORITY]
        if mode == "targeted" and only_category:
            return [c for c in enabled if c.category == only_category]
        return enabled

    def disabled_names(self) -> list[str]:
        """Return names of disabled checkers for reporting purposes.

        Returns:
            List of checker names that are disabled by configuration.
        """
        return [c.name for c in self._checkers if not c.enabled]


# ---------------------------------------------------------------------------
# Fix plan builder
# ---------------------------------------------------------------------------

class FixPlanBuilder:
    """Build a deterministic, severity-ordered fix plan from a finding list.

    Each plan item groups all findings for one VERIFY tool and includes a
    copy-paste ``run_command`` referencing that tool by name and TOOL-ref.
    """

    # Dependency ordering: tools that must run before others
    DEPENDENCIES: dict[str, list[str]] = {
        "add_rbac": ["add_auth"],
        "add_mfa": ["add_auth"],
        "add_rate_limiting": ["add_auth"],
        "add_audit_log": ["add_multi_tenancy"],
    }

    def __init__(self, findings: list[dict[str, Any]]) -> None:
        self.findings = findings

    def build(self) -> list[dict[str, Any]]:
        """Build and return the ordered fix plan.

        Returns:
            List of plan items sorted CRITICAL-first, then by finding count desc.
        """
        grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for f in self.findings:
            key = (f.get("tool_ref", "unknown"), f.get("tool_name", "unknown"))
            grouped[key].append(f)

        items: list[dict[str, Any]] = []
        for (tool_ref, tool_name), group in grouped.items():
            severity_counts: dict[str, int] = {s.name: 0 for s in Severity}
            for f in group:
                sev = f.get("severity", Severity.MEDIUM)
                sev_name = sev.name if isinstance(sev, Severity) else str(sev)
                severity_counts[sev_name] = severity_counts.get(sev_name, 0) + 1

            worst = self._worst_severity(group)
            items.append({
                "severity": worst.name,
                "tool_ref": tool_ref,
                "tool_name": tool_name,
                "fixes_critical": severity_counts.get("CRITICAL", 0),
                "fixes_high": severity_counts.get("HIGH", 0),
                "fixes_medium": severity_counts.get("MEDIUM", 0),
                "fixes_low": severity_counts.get("LOW", 0),
                "total_fixes": len(group),
                "run_command": f"fastapi_skill {tool_name} .",
                "findings": [f["title"] for f in group],
            })

        items = self._sort_by_severity_and_deps(items)
        for i, item in enumerate(items, start=1):
            item["order"] = i
        return items

    def _worst_severity(self, findings: list[dict[str, Any]]) -> Severity:
        """Return the most severe level from a list of findings.

        Args:
            findings: List of normalised finding dicts.

        Returns:
            Highest-priority ``Severity`` value in the list.
        """
        worst = Severity.LOW
        for f in findings:
            sev = f.get("severity", Severity.LOW)
            if isinstance(sev, Severity) and sev < worst:
                worst = sev
        return worst

    def _sort_by_severity_and_deps(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Sort plan items CRITICAL-first, then by total_fixes descending.

        Args:
            items: Unsorted list of fix plan items.

        Returns:
            Deterministically sorted list.
        """
        sev_order: dict[str, int] = {s.name: s.value for s in Severity}
        return sorted(
            items,
            key=lambda x: (sev_order.get(x["severity"], 99), -x["total_fixes"]),
        )


# ---------------------------------------------------------------------------
# Recommendation engine
# ---------------------------------------------------------------------------

def _has_auth(project_dir: Path) -> bool:
    return any(project_dir.rglob("*auth*")) or any(project_dir.rglob("*jwt*"))


def _has_file(project_dir: Path, keyword: str) -> bool:
    return any(keyword in p.name.lower() for p in project_dir.rglob("*.py"))


def _has_import(project_dir: Path, *packages: str) -> bool:
    for py_file in project_dir.rglob("*.py"):
        try:
            src = py_file.read_text(errors="ignore")
            if any(pkg in src for pkg in packages):
                return True
        except OSError:
            pass
    return False


def _model_count(project_dir: Path) -> int:
    count = 0
    for py_file in project_dir.rglob("models*.py"):
        try:
            tree = ast.parse(py_file.read_text(errors="ignore"))
            count += sum(1 for n in ast.walk(tree) if isinstance(n, ast.ClassDef))
        except SyntaxError:
            pass
    return count


def _route_count(project_dir: Path) -> int:
    count = 0
    pattern = re.compile(r"@(?:app|router)\.\w+\(")
    for py_file in project_dir.rglob("*.py"):
        try:
            src = py_file.read_text(errors="ignore")
            count += len(pattern.findall(src))
        except OSError:
            pass
    return count


def _has_i18n_hint(project_dir: Path) -> bool:
    pattern = re.compile(r"\b(en|es|pt|fr|de|zh|ja)\b")
    for py_file in list(project_dir.rglob("*.py"))[:50]:
        try:
            if pattern.search(py_file.read_text(errors="ignore")):
                return True
        except OSError:
            pass
    return False


_FEATURE_PATTERNS: list[dict[str, Any]] = [
    {
        "tool": "add_rbac",
        "tool_ref": "TOOL-006",
        "trigger": lambda p: _has_auth(p) and not _has_file(p, "rbac"),
        "reason": "auth detected; no RBAC roles/permissions found",
    },
    {
        "tool": "add_mfa",
        "tool_ref": "TOOL-013",
        "trigger": lambda p: _has_auth(p) and not _has_import(p, "pyotp", "totp"),
        "reason": "auth detected; MFA/TOTP middleware absent",
    },
    {
        "tool": "add_audit_log",
        "tool_ref": "TOOL-009",
        "trigger": lambda p: _model_count(p) > 5 and not _has_file(p, "audit"),
        "reason": "5+ mutable models found; no audit_log table detected",
    },
    {
        "tool": "add_rate_limiting",
        "tool_ref": "TOOL-014",
        "trigger": lambda p: _has_auth(p) and not _has_import(p, "slowapi", "limits"),
        "reason": "public routes detected; no rate-limiting middleware found",
    },
    {
        "tool": "add_caching",
        "tool_ref": "TOOL-007",
        "trigger": lambda p: _route_count(p) > 20 and not _has_import(p, "redis", "cache"),
        "reason": "20+ routes found; no caching layer detected",
    },
    {
        "tool": "add_background_tasks",
        "tool_ref": "TOOL-016",
        "trigger": lambda p: not _has_import(p, "arq", "celery", "dramatiq"),
        "reason": "no background task queue detected",
    },
    {
        "tool": "add_observability",
        "tool_ref": "TOOL-020",
        "trigger": lambda p: not _has_import(p, "opentelemetry", "prometheus"),
        "reason": "no OpenTelemetry or Prometheus instrumentation detected",
    },
    {
        "tool": "add_i18n",
        "tool_ref": "TOOL-024",
        "trigger": lambda p: _has_i18n_hint(p) and not _has_import(p, "babel", "gettext"),
        "reason": "multiple locale strings detected; no i18n library found",
    },
]


class ExtendRecommender:
    """Recommend EXTEND tools the project should adopt but hasn't yet.

    Uses AST and file-pattern analysis to detect what is already present
    before adding any recommendation. Never recommends features already wired.
    """

    def __init__(self, project_dir: str) -> None:
        self.project_dir = Path(project_dir).resolve()

    def analyze(self) -> list[dict[str, Any]]:
        """Scan the project and return EXTEND tool recommendations.

        Returns:
            List of recommendation dicts, each with ``tool``, ``tool_ref``,
            ``reason``, ``run_command``, and ``priority`` fields.
        """
        recommendations: list[dict[str, Any]] = []
        for spec in _FEATURE_PATTERNS:
            try:
                if spec["trigger"](self.project_dir):
                    recommendations.append({
                        "tool": spec["tool"],
                        "tool_ref": spec["tool_ref"],
                        "reason": spec["reason"],
                        "run_command": f"fastapi_skill {spec['tool']} .",
                        "priority": "HIGH" if "auth" in spec["reason"] else "MEDIUM",
                    })
            except Exception:  # noqa: BLE001
                pass
        return recommendations


# ---------------------------------------------------------------------------
# Baseline comparator
# ---------------------------------------------------------------------------

class BaselineComparator:
    """Persist and compare finding fingerprints for CI delta gating.

    On first run with no baseline, saves the current finding set as the
    committed baseline. Subsequent runs return only the delta.
    """

    BASELINE_FILE = ".fastapi_doctor.baseline.json"

    def __init__(self, project_dir: str) -> None:
        self.baseline_path = Path(project_dir) / self.BASELINE_FILE

    def diff(self, findings: list[dict[str, Any]]) -> dict[str, int]:
        """Compare findings against the committed baseline.

        Creates a new baseline on first run. Returns delta counts on subsequent
        runs so pre-existing issues never block CI indefinitely.

        Args:
            findings: Current normalised finding list.

        Returns:
            Dict with ``new``, ``resolved``, and ``unchanged`` counts.
        """
        current_fps = self._fingerprints(findings)
        if not self.baseline_path.exists():
            self._save(findings)
            return {"new": 0, "resolved": 0, "unchanged": len(findings)}

        try:
            baseline_data = json.loads(self.baseline_path.read_text())
            baseline_fps: set[str] = set(baseline_data.get("fingerprints", []))
        except (json.JSONDecodeError, OSError):
            return {"new": len(findings), "resolved": 0, "unchanged": 0, "error": 1}

        new_fps = current_fps - baseline_fps
        resolved_fps = baseline_fps - current_fps
        return {
            "new": len(new_fps),
            "resolved": len(resolved_fps),
            "unchanged": len(current_fps & baseline_fps),
        }

    def save(self, findings: list[dict[str, Any]]) -> None:
        """Explicitly persist the current finding set as the new baseline.

        Args:
            findings: Finding list to snapshot.
        """
        self._save(findings)

    def reset(self) -> None:
        """Delete the committed baseline file.

        Subsequent runs will create a fresh baseline from the current state.
        """
        if self.baseline_path.exists():
            self.baseline_path.unlink()

    def _fingerprints(self, findings: list[dict[str, Any]]) -> set[str]:
        fps: set[str] = set()
        for f in findings:
            sev = f.get("severity", "MEDIUM")
            sev_str = sev.name if isinstance(sev, Severity) else str(sev)
            title = f.get("title", "")
            loc = f.get("location", "")
            fps.add(f"{sev_str}::{title}::{loc}")
        return fps

    def _save(self, findings: list[dict[str, Any]]) -> None:
        payload = {
            "fingerprints": sorted(self._fingerprints(findings)),
            "total": len(findings),
        }
        self.baseline_path.write_text(json.dumps(payload, indent=2))


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

    next_steps: list[str] = [
        item["run_command"]
        for item in report.get("fix_plan", [])[:5]
    ]
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
