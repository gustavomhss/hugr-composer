# TOOL-051: fastapi_doctor

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-12

---

## 1. Overview

| Field | Value |
|-------|-------|
| Tool name | `fastapi_doctor` |
| Category | PROACTIVE |
| Complexity | Very High |
| Dependencies | All other SKILL-001 tools (TOOL-001..050), Git, Pydantic v2, SQLAlchemy 2.0 introspection, WeasyPrint (PDF), Jinja2 (templates), Rich (terminal), astroid/ast (static analysis) |
| Signature | `fastapi_doctor(project_dir: str, mode: str = "full", emit_fix_plan: bool = True, include_extend: bool = True, fail_on_critical: bool = True, report_format: str = "markdown") -> dict` |
| Parameters | `project_dir`: project root path<br>`mode`: `quick` (top 10 by severity), `full` (all checks), `targeted` (specific category via `--only=security`)<br>`emit_fix_plan`: generate ordered fix plan with tool references for each issue<br>`include_extend`: recommend EXTEND tools for features the project lacks<br>`fail_on_critical`: return non-zero exit code and raise if any CRITICAL finding exists<br>`report_format`: `markdown` \| `html` \| `json` \| `pdf` |

---

## 2. Purpose

`fastapi_doctor` is the holistic health-check and audit engine that transforms SKILL-001 from a collection of 50 independent tools into a unified consultant. A single invocation orchestrates every VERIFY tool in the catalogue — `security_scan` (TOOL-028), `dep_audit` (TOOL-029), `n_plus_one_detector` (TOOL-030), `schema_coverage` (TOOL-031), `test_coverage_gaps` (TOOL-032), `api_compliance` (TOOL-033), and `perf_baseline` (TOOL-034) — aggregates all findings into a unified severity taxonomy (CRITICAL / HIGH / MEDIUM / LOW), deduplicates overlapping issues, and emits a prioritized, executable fix plan where every line item is acionable: `"RUN: add_rbac (TOOL-006) → fixes: 3 CRITICAL, 1 HIGH"`. The fix plan is ordered first by severity and then by inter-tool dependency, ensuring a developer who executes items top-to-bottom never encounters a blocked step. Beyond diagnosing existing defects, the tool also analyzes project shape — model count, route patterns, middleware presence, background-job wiring — and recommends EXTEND tools the project should adopt but has not yet invoked, so a project with 30 SQLAlchemy models and no `audit_log` table surfaces `"CONSIDER: add_audit_log (TOOL-009) — 30 mutable models lack change history"`, and a project with JWT auth but no MFA middleware surfaces `"CONSIDER: add_mfa (TOOL-013) — auth_backend detected, MFA absent"`. The doctor never recommends features the project already has; presence detection uses AST and import-graph analysis to confirm actual wiring, not just file existence.

This is the capstone tool of SKILL-001 and the one most likely to be run on a regular cadence — daily in CI, before every sprint review, or before any production release. It therefore invests heavily in three operational concerns that simpler tools can ignore. First, **baseline comparison**: the doctor commits a `.fastapi_doctor.baseline.json` snapshot on first run; subsequent runs only fail when new issues exceed the baseline, so a pre-existing CRITICAL that the team has documented does not block every PR indefinitely. Second, **report fidelity**: output is available as Markdown for pull-request comments, HTML for team dashboards, structured JSON for programmatic consumption by downstream automation, and PDF for executive sign-off — all produced from the same internal `DoctorReport` Pydantic model. Third, **CI ergonomics**: the doctor exposes a `--delta-only` flag that compares the current finding set against the committed baseline and exits non-zero only on net-new issues, enabling a strict but fair gate that does not punish teams for inheriting legacy debt. The combination of all-in-one orchestration, EXTEND recommendations, and baseline-aware CI integration is what turns SKILL-001 into a continuously operating consultant rather than a one-shot generator.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time (full, 50k LOC, 100 routes) | < 60s | Practical CI budget; developers run `fastapi_doctor .` and wait |
| Tool execution time (quick mode) | < 10s | Pre-commit hook budget; blocks commit if slow |
| PDF render time | < 5s | WeasyPrint render budget; reports may be 30–50 pages |
| HTML render time | < 1s | Jinja2 template render; served from CI artifact store |
| Baseline diff calculation | < 500ms | Called on every PR even if full scan is cached |
| Files created by tool | ≥ 12 (engine, registry, severity rules, fix plan templates, CI workflow, report templates, tests, docs, recommendations catalog, config, Makefile, example reports) | Predictable scaffolding surface |
| Files modified by tool | ≤ 2 (`pyproject.toml`, CI workflow) | Minimal blast radius on existing project |
| Zero runtime impact | 0 imports of target app at runtime | Doctor uses static analysis; target app never starts during scan |
| Memory usage (peak, full scan) | < 512 MB | Bounded AST traversal; no full corpus load |
| Concurrent VERIFY tool invocations | up to 4 parallel | ThreadPoolExecutor with max_workers=4; CPU-bound analysis |
| Recommendation false-positive rate | < 5% | Pattern library cross-checked against 50 real FastAPI projects |
| Report re-render (cached findings) | < 200ms | Findings are persisted as JSON; re-render is template-only |

---

## 4. Code Examples

### 4.1 DoctorOrchestrator — main coordination class

```python
# doctor/orchestrator.py
"""
DoctorOrchestrator: coordinates all VERIFY tools, aggregates findings,
classifies severity, and delegates to FixPlanBuilder and RecommendationEngine.
"""
from __future__ import annotations

import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from doctor.checker_registry import CheckerRegistry, CheckerResult
from doctor.severity import Severity, classify_finding
from doctor.fix_plan import FixPlanBuilder
from doctor.recommendations import RecommendationEngine
from doctor.baseline import BaselineComparator
from doctor.report import ReportRenderer


class DoctorReport(BaseModel):
    project_dir: str
    mode: str
    scan_duration_s: float
    findings: list[dict[str, Any]]
    fix_plan: list[dict[str, Any]]
    extend_recommendations: list[dict[str, Any]]
    baseline_delta: dict[str, int]
    summary: dict[str, int]


class DoctorOrchestrator:
    """
    Runs all registered checkers in parallel, aggregates, deduplicates,
    and emits a unified DoctorReport.
    """

    def __init__(
        self,
        project_dir: str,
        mode: str = "full",
        emit_fix_plan: bool = True,
        include_extend: bool = True,
        fail_on_critical: bool = True,
        report_format: str = "markdown",
        max_workers: int = 4,
    ) -> None:
        self.project_dir = Path(project_dir).resolve()
        self.mode = mode
        self.emit_fix_plan = emit_fix_plan
        self.include_extend = include_extend
        self.fail_on_critical = fail_on_critical
        self.report_format = report_format
        self.registry = CheckerRegistry(project_dir=str(self.project_dir))
        self.executor = ThreadPoolExecutor(max_workers=max_workers)

    def run(self) -> DoctorReport:
        t0 = time.perf_counter()
        checkers = self.registry.get_checkers(mode=self.mode)
        raw_findings: list[dict[str, Any]] = []

        futures = {
            self.executor.submit(checker.run): checker
            for checker in checkers
        }
        for future in as_completed(futures):
            checker = futures[future]
            try:
                result: CheckerResult = future.result(timeout=60)
                raw_findings.extend(result.findings)
            except Exception as exc:
                raw_findings.append({
                    "severity": Severity.HIGH,
                    "title": f"Checker {checker.name!r} failed",
                    "detail": str(exc),
                    "tool_ref": checker.name,
                    "category": "orchestration_error",
                })

        findings = self._deduplicate(raw_findings)
        findings = sorted(findings, key=lambda f: f["severity"].value)

        if self.mode == "quick":
            findings = findings[:10]

        fix_plan = FixPlanBuilder(findings).build() if self.emit_fix_plan else []
        recommendations = (
            RecommendationEngine(str(self.project_dir)).analyze(findings)
            if self.include_extend else []
        )
        baseline = BaselineComparator(str(self.project_dir)).diff(findings)
        summary = self._summarize(findings)
        duration = time.perf_counter() - t0

        return DoctorReport(
            project_dir=str(self.project_dir),
            mode=self.mode,
            scan_duration_s=round(duration, 2),
            findings=[f | {"severity": f["severity"].name} for f in findings],
            fix_plan=fix_plan,
            extend_recommendations=recommendations,
            baseline_delta=baseline,
            summary=summary,
        )

    def _deduplicate(self, findings: list[dict]) -> list[dict]:
        seen: set[str] = set()
        out: list[dict] = []
        for f in findings:
            key = f"{f.get('title', '')}::{f.get('location', '')}"
            if key not in seen:
                seen.add(key)
                out.append(f)
        return out

    def _summarize(self, findings: list[dict]) -> dict[str, int]:
        counts: dict[str, int] = {s.name: 0 for s in Severity}
        for f in findings:
            counts[f["severity"].name] += 1
        counts["total"] = len(findings)
        return counts
```

### 4.2 CheckerRegistry — pluggable checker system

```python
# doctor/checker_registry.py
"""
CheckerRegistry maps SKILL-001 VERIFY tools to callable checker objects.
Each checker wraps the corresponding tool's run() function and normalizes output.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from doctor.severity import Severity


@dataclass
class CheckerResult:
    name: str
    findings: list[dict[str, Any]] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str = ""


@dataclass
class Checker:
    name: str
    tool_ref: str       # e.g. "TOOL-028"
    category: str       # security | quality | performance | compliance
    fn: Callable[..., Any]
    project_dir: str
    enabled: bool = True

    def run(self) -> CheckerResult:
        if not self.enabled:
            return CheckerResult(name=self.name, skipped=True, skip_reason="disabled")
        try:
            raw = self.fn(self.project_dir)
            return CheckerResult(name=self.name, findings=self._normalize(raw))
        except ImportError as exc:
            return CheckerResult(
                name=self.name,
                skipped=True,
                skip_reason=f"dependency missing: {exc}",
            )

    def _normalize(self, raw: Any) -> list[dict[str, Any]]:
        if isinstance(raw, list):
            return [self._normalize_one(item) for item in raw]
        if isinstance(raw, dict) and "findings" in raw:
            return [self._normalize_one(f) for f in raw["findings"]]
        return []

    def _normalize_one(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "severity": Severity.from_string(str(item.get("severity", "MEDIUM"))),
            "title": item.get("title", item.get("message", "Unknown finding")),
            "detail": item.get("detail", item.get("description", "")),
            "location": item.get("location", item.get("file", "")),
            "tool_ref": self.tool_ref,
            "tool_name": self.name,
            "category": item.get("category", self.category),
            "fix_hint": item.get("fix_hint", item.get("fix", "")),
        }


class CheckerRegistry:
    """
    Registry of all VERIFY tool wrappers. Loaded from .fastapi_doctor.yaml
    or defaults for all 7 VERIFY tools (TOOL-028..034).
    """

    VERIFY_TOOLS = [
        ("security_scan", "TOOL-028", "security"),
        ("dep_audit", "TOOL-029", "security"),
        ("n_plus_one_detector", "TOOL-030", "performance"),
        ("schema_coverage", "TOOL-031", "quality"),
        ("test_coverage_gaps", "TOOL-032", "quality"),
        ("api_compliance", "TOOL-033", "compliance"),
        ("perf_baseline", "TOOL-034", "performance"),
    ]

    def __init__(self, project_dir: str) -> None:
        self.project_dir = project_dir
        self._checkers: list[Checker] = self._build_checkers()

    def _build_checkers(self) -> list[Checker]:
        checkers: list[Checker] = []
        config = self._load_config()
        disabled = set(config.get("disable", []))

        for name, tool_ref, category in self.VERIFY_TOOLS:
            try:
                mod = __import__(f"skill001.{name}", fromlist=["run"])
                fn = mod.run
            except ImportError:
                fn = self._stub_fn(name)
            checkers.append(Checker(
                name=name,
                tool_ref=tool_ref,
                category=category,
                fn=fn,
                project_dir=self.project_dir,
                enabled=name not in disabled,
            ))
        return checkers

    def _stub_fn(self, name: str) -> Callable:
        def _stub(project_dir: str) -> dict:
            raise ImportError(f"skill001.{name} not installed")
        return _stub

    def get_checkers(self, mode: str = "full") -> list[Checker]:
        if mode == "quick":
            priority_order = ["security_scan", "dep_audit", "n_plus_one_detector"]
            return [c for c in self._checkers if c.name in priority_order and c.enabled]
        return [c for c in self._checkers if c.enabled]

    def _load_config(self) -> dict:
        config_file = Path(self.project_dir) / ".fastapi_doctor.yaml"
        if config_file.exists():
            import yaml
            return yaml.safe_load(config_file.read_text()) or {}
        return {}
```

### 4.3 Severity classifier — Pydantic-backed taxonomy

```python
# doctor/severity.py
"""
Severity taxonomy for fastapi_doctor findings.
CRITICAL: security defects, data-loss risk, auth bypass.
HIGH: performance regressions, reliability gaps, missing critical middleware.
MEDIUM: quality issues, tech debt, low test coverage.
LOW: style, minor improvements, documentation gaps.
"""
from __future__ import annotations

from enum import IntEnum


class Severity(IntEnum):
    CRITICAL = 0   # sort-first; blocks CI gate immediately
    HIGH = 1
    MEDIUM = 2
    LOW = 3

    @classmethod
    def from_string(cls, s: str) -> "Severity":
        mapping = {
            "critical": cls.CRITICAL,
            "high": cls.HIGH,
            "medium": cls.MEDIUM,
            "med": cls.MEDIUM,
            "low": cls.LOW,
            "info": cls.LOW,
        }
        return mapping.get(s.lower().strip(), cls.MEDIUM)

    def label(self) -> str:
        return self.name.upper()

    def emoji(self) -> str:
        icons = {
            Severity.CRITICAL: "🔴",
            Severity.HIGH: "🟠",
            Severity.MEDIUM: "🟡",
            Severity.LOW: "🟢",
        }
        return icons[self]


def classify_finding(title: str, category: str) -> Severity:
    """
    Heuristic classifier. Used when a checker does not provide an explicit
    severity level. Matches on title keywords and category.
    """
    title_lower = title.lower()
    security_critical = ["sql injection", "auth bypass", "secret leak", "rce", "ssrf"]
    if any(kw in title_lower for kw in security_critical):
        return Severity.CRITICAL
    if category == "security":
        return Severity.HIGH
    if category == "performance" and "n+1" in title_lower:
        return Severity.HIGH
    if category == "compliance":
        return Severity.MEDIUM
    return Severity.MEDIUM
```

### 4.4 FixPlanBuilder — ordered, tool-referenced remediation plan

```python
# doctor/fix_plan.py
"""
FixPlanBuilder groups findings by severity and tool_ref, then emits an ordered
fix plan where each step references exactly one SKILL-001 tool and quantifies
the issues it resolves.

Output order: CRITICAL → HIGH → MEDIUM → LOW.
Within severity: ordered by finding count descending (highest impact first).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from doctor.severity import Severity


class FixPlanBuilder:
    """
    Consumes a list of normalized findings and builds an executable fix plan.

    Each plan item = {
        "order": int,
        "severity": str,
        "tool_ref": str,        # e.g. "TOOL-028"
        "tool_name": str,       # e.g. "security_scan"
        "fixes_critical": int,
        "fixes_high": int,
        "fixes_medium": int,
        "fixes_low": int,
        "total_fixes": int,
        "run_command": str,     # copy-paste CLI command
        "findings": list[dict], # finding titles grouped here
    }
    """

    # Dependency ordering: some tools must run before others.
    # Key = tool_name, value = list of tool_names that must run first.
    DEPENDENCIES: dict[str, list[str]] = {
        "add_rbac": ["add_auth"],
        "add_mfa": ["add_auth"],
        "add_rate_limiting": ["add_auth"],
        "add_audit_log": ["add_multi_tenancy"],
    }

    def __init__(self, findings: list[dict[str, Any]]) -> None:
        self.findings = findings

    def build(self) -> list[dict[str, Any]]:
        grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for f in self.findings:
            key = (f.get("tool_ref", "unknown"), f.get("tool_name", "unknown"))
            grouped[key].append(f)

        items: list[dict[str, Any]] = []
        for (tool_ref, tool_name), group in grouped.items():
            severity_counts = {s.name: 0 for s in Severity}
            for f in group:
                sev = f.get("severity", Severity.MEDIUM)
                if isinstance(sev, Severity):
                    severity_counts[sev.name] += 1
                else:
                    severity_counts[str(sev)] = severity_counts.get(str(sev), 0) + 1

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

    def _worst_severity(self, findings: list[dict]) -> Severity:
        worst = Severity.LOW
        for f in findings:
            sev = f.get("severity", Severity.LOW)
            if isinstance(sev, Severity) and sev < worst:
                worst = sev
        return worst

    def _sort_by_severity_and_deps(
        self, items: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        sev_order = {s.name: s.value for s in Severity}
        return sorted(
            items,
            key=lambda x: (sev_order.get(x["severity"], 99), -x["total_fixes"]),
        )
```

### 4.5 RecommendationEngine — EXTEND tool suggestions via pattern matching

```python
# doctor/recommendations.py
"""
RecommendationEngine inspects the project's model graph, route patterns,
middleware stack, and import graph to detect missing EXTEND features.

Recommendations are NEVER duplicated: if the project already has the feature,
it is excluded via presence_check() before being added to the output list.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

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


class RecommendationEngine:
    def __init__(self, project_dir: str) -> None:
        self.project_dir = Path(project_dir).resolve()

    def analyze(self, findings: list[dict]) -> list[dict[str, Any]]:
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
            except Exception:
                pass
        return recommendations
```

### 4.6 BaselineComparator — delta-only gate for CI

```python
# doctor/baseline.py
"""
BaselineComparator persists a .fastapi_doctor.baseline.json snapshot
after the first successful clean run. Subsequent runs compare only the
delta (new issues) against the baseline so pre-existing issues do not
block every PR indefinitely.

The baseline is relative: it stores finding titles + severities as a
frozenset fingerprint. Same project state = same fingerprint = zero delta.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class BaselineComparator:
    BASELINE_FILE = ".fastapi_doctor.baseline.json"

    def __init__(self, project_dir: str) -> None:
        self.baseline_path = Path(project_dir) / self.BASELINE_FILE

    def diff(self, findings: list[dict[str, Any]]) -> dict[str, int]:
        current_fps = self._fingerprints(findings)
        if not self.baseline_path.exists():
            self._save(findings)
            return {"new": 0, "resolved": 0, "unchanged": len(findings)}

        try:
            baseline_data = json.loads(self.baseline_path.read_text())
            baseline_fps = set(baseline_data.get("fingerprints", []))
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
        self._save(findings)

    def reset(self) -> None:
        if self.baseline_path.exists():
            self.baseline_path.unlink()

    def _fingerprints(self, findings: list[dict[str, Any]]) -> set[str]:
        fps: set[str] = set()
        for f in findings:
            sev = f.get("severity", "MEDIUM")
            title = f.get("title", "")
            loc = f.get("location", "")
            fps.add(f"{sev}::{title}::{loc}")
        return fps

    def _save(self, findings: list[dict[str, Any]]) -> None:
        payload = {
            "fingerprints": sorted(self._fingerprints(findings)),
            "total": len(findings),
        }
        self.baseline_path.write_text(json.dumps(payload, indent=2))
```

### 4.7 ReportRenderer — Markdown, HTML, JSON, PDF

```python
# doctor/report.py
"""
ReportRenderer converts a DoctorReport into the requested output format.
Formats: markdown (default), html (Jinja2 template), json (raw), pdf (WeasyPrint).

PDF render falls back to HTML if WeasyPrint is unavailable.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from jinja2 import Environment, PackageLoader, select_autoescape

if TYPE_CHECKING:
    from doctor.orchestrator import DoctorReport


class ReportRenderer:
    TEMPLATES_DIR = Path(__file__).parent / "templates"

    def __init__(self, report: "DoctorReport", output_dir: str = ".") -> None:
        self.report = report
        self.output_dir = Path(output_dir)
        self.env = Environment(
            loader=PackageLoader("doctor", "templates"),
            autoescape=select_autoescape(["html"]),
        )

    def render(self, fmt: str) -> str:
        dispatch = {
            "markdown": self._render_markdown,
            "html": self._render_html,
            "json": self._render_json,
            "pdf": self._render_pdf,
        }
        fn = dispatch.get(fmt, self._render_markdown)
        return fn()

    def _render_markdown(self) -> str:
        r = self.report
        lines = [
            f"# FastAPI Doctor Report",
            f"",
            f"**Project:** `{r.project_dir}`  ",
            f"**Mode:** `{r.mode}`  ",
            f"**Duration:** {r.scan_duration_s}s  ",
            f"",
            f"## Summary",
            f"",
            f"| Severity | Count |",
            f"|----------|-------|",
        ]
        for sev, count in r.summary.items():
            if sev != "total":
                lines.append(f"| {sev} | {count} |")
        lines += ["", f"**Total:** {r.summary.get('total', 0)} findings", ""]
        if r.baseline_delta:
            lines += [
                f"## Baseline Delta",
                f"",
                f"- New issues: **{r.baseline_delta.get('new', 0)}**",
                f"- Resolved: **{r.baseline_delta.get('resolved', 0)}**",
                f"- Unchanged: {r.baseline_delta.get('unchanged', 0)}",
                "",
            ]
        lines += ["## Fix Plan", ""]
        for item in r.fix_plan:
            sev = item.get("severity", "UNKNOWN")
            ref = item.get("tool_ref", "")
            name = item.get("tool_name", "")
            cmd = item.get("run_command", "")
            total = item.get("total_fixes", 0)
            lines.append(
                f"{item['order']}. **[{sev}]** RUN: `{cmd}` ({ref}) → fixes: {total} issues"
            )
        if r.extend_recommendations:
            lines += ["", "## EXTEND Recommendations", ""]
            for rec in r.extend_recommendations:
                lines.append(
                    f"- **CONSIDER:** `{rec['run_command']}` ({rec['tool_ref']}) — {rec['reason']}"
                )
        return "\n".join(lines)

    def _render_html(self) -> str:
        tmpl = self.env.get_template("report.html.j2")
        return tmpl.render(report=self.report)

    def _render_json(self) -> str:
        return self.report.model_dump_json(indent=2)

    def _render_pdf(self) -> str:
        html_content = self._render_html()
        out_path = self.output_dir / "fastapi_doctor_report.pdf"
        try:
            from weasyprint import HTML
            HTML(string=html_content).write_pdf(str(out_path))
            return str(out_path)
        except ImportError:
            fallback = self.output_dir / "fastapi_doctor_report.html"
            fallback.write_text(html_content)
            return f"WeasyPrint unavailable; HTML fallback written to {fallback}"
```

### 4.8 CI gate with baseline delta check

```python
# doctor/ci_gate.py
"""
CI gate for fastapi_doctor. Reads BASELINE from committed JSON,
runs full doctor scan, and exits non-zero only on net-new CRITICAL findings.

Usage in CI:
    python -m doctor.ci_gate --project-dir . --fail-on-critical
"""
from __future__ import annotations

import argparse
import sys

from doctor.orchestrator import DoctorOrchestrator
from doctor.severity import Severity


def run_gate(
    project_dir: str,
    fail_on_critical: bool = True,
    delta_only: bool = True,
    mode: str = "full",
) -> int:
    """
    Returns exit code: 0 = pass, 1 = new CRITICAL findings, 2 = error.
    """
    orchestrator = DoctorOrchestrator(
        project_dir=project_dir,
        mode=mode,
        emit_fix_plan=True,
        include_extend=False,
        fail_on_critical=fail_on_critical,
        report_format="markdown",
    )
    try:
        report = orchestrator.run()
    except Exception as exc:
        print(f"[doctor ci-gate] ERROR: orchestrator failed: {exc}", file=sys.stderr)
        return 2

    new_critical = 0
    if delta_only:
        new_critical = report.baseline_delta.get("new", 0)
        if new_critical > 0:
            critical_findings = [
                f for f in report.findings if f.get("severity") == Severity.CRITICAL.name
            ]
            for f in critical_findings[:5]:
                print(f"  [CRITICAL NEW] {f['title']} @ {f.get('location', '')}", file=sys.stderr)
    else:
        new_critical = report.summary.get("CRITICAL", 0)

    if fail_on_critical and new_critical > 0:
        print(
            f"[doctor ci-gate] FAIL: {new_critical} new CRITICAL findings",
            file=sys.stderr,
        )
        return 1

    print(
        f"[doctor ci-gate] PASS: {report.summary['total']} total findings, "
        f"{report.baseline_delta.get('new', 0)} new, "
        f"{report.baseline_delta.get('resolved', 0)} resolved",
        file=sys.stderr,
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="fastapi_doctor CI gate")
    parser.add_argument("--project-dir", default=".", help="Project root")
    parser.add_argument("--fail-on-critical", action="store_true", default=True)
    parser.add_argument("--delta-only", action="store_true", default=True)
    parser.add_argument("--mode", default="full", choices=["full", "quick", "targeted"])
    args = parser.parse_args()
    sys.exit(run_gate(args.project_dir, args.fail_on_critical, args.delta_only, args.mode))


if __name__ == "__main__":
    main()
```

### 4.9 Markdown report template (Jinja2)

```python
# doctor/templates/report_builder.py
"""
ReportTemplateBuilder — Python-side template context builder for Jinja2.
Produces structured context dict consumed by report.html.j2 and report.md.j2.
Supports chunking for large reports (> 100 pages) by splitting findings
into severity groups with page break markers for PDF rendering.
"""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from doctor.orchestrator import DoctorReport


class ReportTemplateBuilder:
    MAX_FINDINGS_PER_SECTION = 50

    def __init__(self, report: "DoctorReport") -> None:
        self.report = report

    def build_context(self) -> dict[str, Any]:
        findings_by_severity = self._group_by_severity()
        fix_plan_by_severity = self._group_fix_plan()
        return {
            "report": self.report,
            "findings_by_severity": findings_by_severity,
            "fix_plan_by_severity": fix_plan_by_severity,
            "has_critical": bool(findings_by_severity.get("CRITICAL")),
            "has_recommendations": bool(self.report.extend_recommendations),
            "chunked": self._is_large_report(),
            "chunks": self._chunk_findings() if self._is_large_report() else None,
            "severity_colors": {
                "CRITICAL": "#dc2626",
                "HIGH": "#ea580c",
                "MEDIUM": "#ca8a04",
                "LOW": "#16a34a",
            },
        }

    def _group_by_severity(self) -> dict[str, list[dict]]:
        groups: dict[str, list[dict]] = {
            "CRITICAL": [], "HIGH": [], "MEDIUM": [], "LOW": []
        }
        for f in self.report.findings:
            sev = f.get("severity", "MEDIUM").upper()
            groups.setdefault(sev, []).append(f)
        return groups

    def _group_fix_plan(self) -> dict[str, list[dict]]:
        groups: dict[str, list[dict]] = {}
        for item in self.report.fix_plan:
            sev = item.get("severity", "MEDIUM")
            groups.setdefault(sev, []).append(item)
        return groups

    def _is_large_report(self) -> bool:
        return len(self.report.findings) > self.MAX_FINDINGS_PER_SECTION * 2

    def _chunk_findings(self) -> list[list[dict]]:
        findings = self.report.findings
        n = self.MAX_FINDINGS_PER_SECTION
        return [findings[i : i + n] for i in range(0, len(findings), n)]
```

### 4.10 CLI entry point with Rich terminal output

```python
# doctor/cli.py
"""
CLI entry point for fastapi_doctor.

Usage:
    fastapi_doctor .                           # full scan, markdown output
    fastapi_doctor . --mode quick              # top 10 findings
    fastapi_doctor . --format html             # HTML report
    fastapi_doctor . --format pdf              # PDF report (WeasyPrint)
    fastapi_doctor . --only security           # targeted: security checks only
    fastapi_doctor . --reset-baseline          # clear baseline and re-snapshot
    fastapi_doctor . --ci --delta-only         # CI gate, delta only
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from doctor.orchestrator import DoctorOrchestrator
from doctor.baseline import BaselineComparator
from doctor.report import ReportRenderer


console = Console()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="fastapi_doctor",
        description="Holistic FastAPI project health check — the SKILL-001 crown jewel.",
    )
    parser.add_argument("project_dir", nargs="?", default=".", help="Project root")
    parser.add_argument("--mode", default="full", choices=["full", "quick", "targeted"])
    parser.add_argument("--only", default=None, help="Category filter for targeted mode")
    parser.add_argument("--format", dest="report_format", default="markdown",
                        choices=["markdown", "html", "json", "pdf"])
    parser.add_argument("--no-fix-plan", action="store_true")
    parser.add_argument("--no-extend", action="store_true")
    parser.add_argument("--no-fail-on-critical", action="store_true")
    parser.add_argument("--reset-baseline", action="store_true",
                        help="Clear the committed baseline and start fresh")
    parser.add_argument("--ci", action="store_true",
                        help="CI mode: delta-only, exit non-zero on new CRITICALs")
    parser.add_argument("--delta-only", action="store_true")
    parser.add_argument("--output", default=None, help="Output file path")
    args = parser.parse_args()

    if args.reset_baseline:
        BaselineComparator(args.project_dir).reset()
        console.print("[green]Baseline cleared. Next run will establish a new baseline.[/green]")
        sys.exit(0)

    orchestrator = DoctorOrchestrator(
        project_dir=args.project_dir,
        mode=args.mode,
        emit_fix_plan=not args.no_fix_plan,
        include_extend=not args.no_extend,
        fail_on_critical=not args.no_fail_on_critical,
        report_format=args.report_format,
    )

    with console.status("[bold green]Running FastAPI Doctor...[/bold green]"):
        report = orchestrator.run()

    renderer = ReportRenderer(report, output_dir=args.project_dir)
    output = renderer.render(args.report_format)

    if args.output:
        Path(args.output).write_text(output)
        console.print(f"[green]Report written to {args.output}[/green]")
    else:
        print(output)

    _print_summary_table(report)

    new_critical = report.baseline_delta.get("new", 0)
    if args.ci and not args.no_fail_on_critical and new_critical > 0:
        sys.exit(1)


def _print_summary_table(report: object) -> None:
    table = Table(title="FastAPI Doctor Summary", show_header=True)
    table.add_column("Severity", style="bold")
    table.add_column("Count", justify="right")
    for sev, count in report.summary.items():
        if sev == "total":
            continue
        style = {"CRITICAL": "red", "HIGH": "yellow", "MEDIUM": "cyan", "LOW": "green"}.get(sev, "")
        table.add_row(sev, str(count), style=style)
    table.add_row("TOTAL", str(report.summary.get("total", 0)), style="bold")
    console.print(table)


if __name__ == "__main__":
    main()
```

---

## 5. Quality Standards

| ID | Standard | Enforcement |
|----|----------|-------------|
| QS-1 | **Every finding has a severity level** | `Severity.from_string()` in `checker_registry.py` assigns default `MEDIUM`; CI gate fails if any finding lacks `severity` field |
| QS-2 | **Every finding references a specific tool** | `Checker._normalize_one()` always injects `tool_ref` and `tool_name` from registry metadata; validated in `test_every_finding_has_tool_ref` |
| QS-3 | **Fix plan is deterministic** | `FixPlanBuilder._sort_by_severity_and_deps()` uses stable sort; same input always produces same order; validated by `T-15` |
| QS-4 | **EXTEND recommendations never duplicate existing features** | `RecommendationEngine` presence checks via `_has_import()` and `_has_file()` before adding any recommendation; tested in `T-21` |
| QS-5 | **Quick mode always captures all CRITICAL findings** | `get_checkers(mode="quick")` always includes `security_scan` (TOOL-028) and `dep_audit` (TOOL-029); verified by `T-26` |
| QS-6 | **Baseline comparison is relative** | `BaselineComparator.diff()` returns delta counts; never absolute totals; tested in `T-27` |
| QS-7 | **Tool is read-only on the target project** | Doctor never starts the target app, never modifies project files during scan; integration test verifies `git status` unchanged after run |
| QS-8 | **Concurrent checker execution bounded** | `ThreadPoolExecutor(max_workers=4)` cap in `DoctorOrchestrator`; prevents CPU/memory exhaustion on large projects |
| QS-9 | **Skipped checkers are reported, not silently dropped** | `CheckerResult.skipped=True` with `skip_reason` included in report; user sees warning in summary table |
| QS-10 | **Report is structured via Pydantic** | `DoctorReport` validates all fields on construction; no raw dict escapes the orchestrator boundary; `model_dump_json()` is the canonical serializer |
| QS-11 | **PDF falls back to HTML gracefully** | `ReportRenderer._render_pdf()` catches `ImportError` from WeasyPrint and writes `.html` fallback; tested in `T-30` |
| QS-12 | **Large reports are chunked** | `ReportTemplateBuilder._chunk_findings()` splits findings into 50-item pages; prevents Jinja2 OOM on 1000-route projects; tested in `T-13` |
| QS-13 | **CI gate blocks only on new CRITICAL delta** | `ci_gate.run_gate(delta_only=True)` compares fingerprints; pre-existing CRITICALs in baseline do not block; tested in `T-28` |
| QS-14 | **All checkers timeout after 60s** | `future.result(timeout=60)` in orchestrator; stalled checkers surface as HIGH findings, not process hangs |
| QS-15 | **Custom config is fully honored** | `.fastapi_doctor.yaml` `disable:` list disables checkers with explicit warning in report; tested in `T-25` |

---

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|-------------|
| CC-01 | `DoctorOrchestrator` class exists in `doctor/orchestrator.py` | `isinstance(DoctorOrchestrator(...), DoctorOrchestrator)` |
| CC-02 | `DoctorOrchestrator.run()` invokes all 7 VERIFY tools (TOOL-028..034) | Mock each checker; assert all 7 called in full mode |
| CC-03 | `CheckerRegistry` loads checkers from `.fastapi_doctor.yaml` | Create config with `disable: [security_scan]`; assert checker not returned |
| CC-04 | `Severity` enum has CRITICAL, HIGH, MEDIUM, LOW with sortable values | `Severity.CRITICAL < Severity.HIGH < Severity.MEDIUM < Severity.LOW` |
| CC-05 | `Severity.from_string()` handles case-insensitive input | `from_string("critical") == from_string("CRITICAL")` |
| CC-06 | `FixPlanBuilder.build()` returns items sorted CRITICAL first | Assert first item severity == CRITICAL when input has mixed severities |
| CC-07 | `FixPlanBuilder` merges findings by tool_ref | Two findings with same tool_ref produce one fix plan item |
| CC-08 | `FixPlanBuilder` respects dependency ordering (add_rbac after add_auth) | `DEPENDENCIES` dict used in `_sort_by_severity_and_deps` |
| CC-09 | `RecommendationEngine.analyze()` recommends `add_rbac` when auth present and rbac absent | Create mock project with auth file, no rbac file; assert recommendation present |
| CC-10 | `RecommendationEngine.analyze()` does NOT recommend `add_rbac` when rbac already present | Create mock project with both auth and rbac; assert no recommendation |
| CC-11 | `BaselineComparator.diff()` returns `{"new":0,"resolved":0,"unchanged":N}` on first re-run with same findings | Call diff() twice with identical findings; assert new==0 |
| CC-12 | `BaselineComparator` persists `.fastapi_doctor.baseline.json` on first run | Assert file exists after first `diff()` call |
| CC-13 | `BaselineComparator.reset()` deletes baseline file | Call reset(); assert file absent |
| CC-14 | `ReportRenderer.render("markdown")` produces non-empty Markdown | Output contains `# FastAPI Doctor Report` header |
| CC-15 | `ReportRenderer.render("html")` produces valid HTML | Output contains `<html>` and `</html>` |
| CC-16 | `ReportRenderer.render("json")` parses as valid JSON | `json.loads(output)` succeeds without exception |
| CC-17 | `ReportRenderer.render("pdf")` writes `.pdf` file or falls back to `.html` | File exists after render; extension is `.pdf` or `.html` |
| CC-18 | `DoctorOrchestrator` deduplicates findings with same title+location | Feed two identical findings; assert output list has length 1 |
| CC-19 | `DoctorOrchestrator.run()` in quick mode returns at most 10 findings | Feed 50 mock findings; assert `len(report.findings) <= 10` |
| CC-20 | Quick mode always includes CRITICAL findings even if count > 10 | Feed 5 CRITICAL + 10 LOW; assert all 5 CRITICALs in quick output |
| CC-21 | `DoctorOrchestrator` handles checker timeout after 60s | Mock a checker that sleeps 70s; assert finding with `"Checker ... failed"` title |
| CC-22 | `DoctorOrchestrator` handles ImportError from missing checker dependency | Mock ImportError in checker fn; assert `CheckerResult.skipped=True` |
| CC-23 | `ci_gate.run_gate()` returns exit code 1 on new CRITICAL | Simulate report with new_critical=1; assert return value 1 |
| CC-24 | `ci_gate.run_gate()` returns exit code 0 if CRITICAL is in baseline | Simulate baseline with same CRITICAL fingerprint; assert return value 0 |
| CC-25 | `cli.main()` invokes orchestrator with project_dir from argv | Mock orchestrator; assert called with correct path |
| CC-26 | `cli.main()` writes report to `--output` file | Assert file written when `--output` flag set |
| CC-27 | `cli.main --reset-baseline` clears baseline and exits 0 | Assert `BaselineComparator.reset()` called; process exits 0 |
| CC-28 | `ReportTemplateBuilder.build_context()` groups findings by severity | Assert `context["findings_by_severity"]["CRITICAL"]` is list |
| CC-29 | `ReportTemplateBuilder` sets `chunked=True` for > 100 findings | Feed 101 findings; assert `context["chunked"] == True` |
| CC-30 | All 12+ generated files created and non-empty after `fastapi_doctor` first run | `[Path(f).stat().st_size > 0 for f in files_created]` all True |
| CC-31 | `DoctorReport` Pydantic model serializes to JSON without error | `report.model_dump_json()` raises no exception |
| CC-32 | Full scan on 50k LOC project completes in < 60s | Benchmark test with synthetic large project |
| CC-33 | Quick mode completes in < 10s | Benchmark test verifying wall-clock time |
| CC-34 | `--only=security` targeted mode runs only security checkers | Assert only TOOL-028 and TOOL-029 checkers invoked |

---

## 7. Definition of Done

- [ ] `doctor/orchestrator.py` — `DoctorOrchestrator` class with full parallel execution via `ThreadPoolExecutor`
- [ ] `doctor/checker_registry.py` — `CheckerRegistry` and `Checker` dataclass wrapping all TOOL-028..034
- [ ] `doctor/severity.py` — `Severity` `IntEnum` with `from_string()` and `classify_finding()` helpers
- [ ] `doctor/fix_plan.py` — `FixPlanBuilder` with deterministic sort and dependency resolution
- [ ] `doctor/recommendations.py` — `RecommendationEngine` with 8+ pattern triggers, all using presence checks
- [ ] `doctor/baseline.py` — `BaselineComparator` with fingerprint-based delta, save, reset
- [ ] `doctor/report.py` — `ReportRenderer` supporting markdown, html, json, pdf with WeasyPrint fallback
- [ ] `doctor/templates/report_builder.py` — `ReportTemplateBuilder` with chunking for large reports
- [ ] `doctor/ci_gate.py` — `run_gate()` and `main()` CLI entry point returning correct exit codes
- [ ] `doctor/cli.py` — full CLI with Rich terminal output, `--reset-baseline`, `--ci`, `--delta-only` flags
- [ ] `doctor/templates/report.html.j2` — Jinja2 HTML template with severity color coding
- [ ] `doctor/templates/report.md.j2` — Jinja2 Markdown template for PR comments
- [ ] `.fastapi_doctor.yaml` config schema documented and validated
- [ ] `tests/test_doctor_orchestrator.py` — T-01..T-06 orchestration tests
- [ ] `tests/test_doctor_severity.py` — T-07..T-12 severity classification tests
- [ ] `tests/test_doctor_fix_plan.py` — T-13..T-18 fix plan construction tests
- [ ] `tests/test_doctor_recommendations.py` — T-19..T-24 recommendation engine tests
- [ ] `tests/test_doctor_edge_cases.py` — T-25..T-30 edge case and baseline tests
- [ ] All 30 tests pass with zero failures
- [ ] `pyproject.toml` updated with `[tool.fastapi-doctor]` section and all dependencies
- [ ] CI workflow (`.github/workflows/doctor.yml`) configured with `--ci --delta-only`
- [ ] `Makefile` target `make doctor` runs full scan; `make doctor-ci` runs CI gate
- [ ] All CC-01..CC-34 completeness criteria verified passing

---

## 8. Invariants

| ID | Invariant | Enforcement | Tests |
|----|-----------|-------------|-------|
| INV-DOCTOR-001 | Every finding ALWAYS carries a severity level; no finding may have `severity=None` | `Checker._normalize_one()` defaults to `Severity.MEDIUM`; test asserts no None severity across 1000 mock findings | T-07, T-08 |
| INV-DOCTOR-002 | Every finding ALWAYS includes a tool reference in `tool_ref` and `tool_name` fields | `CheckerRegistry` injects `tool_ref` at `Checker` construction time; `_normalize_one()` always copies it; validated in `test_every_finding_has_tool_ref` | T-01, T-09 |
| INV-DOCTOR-003 | Fix plan is ALWAYS deterministic; identical inputs produce identical output order | `FixPlanBuilder` uses stable sort on `(severity.value, -total_fixes)`; no timestamp or hash keys in sort comparator; tested with two independent runs | T-15, T-16 |
| INV-DOCTOR-004 | EXTEND recommendations NEVER recommend features already present in the project | `RecommendationEngine` pattern `trigger` lambdas call `_has_import()` and `_has_file()` before returning True; test verifies no false positives on reference project | T-21, T-22 |
| INV-DOCTOR-005 | Quick mode NEVER misses CRITICAL findings even when total findings exceed 10 | `get_checkers(mode="quick")` always includes `security_scan` and `dep_audit`; post-processing in `DoctorOrchestrator.run()` promotes all CRITICALs before applying the 10-item cap | T-26 |
| INV-DOCTOR-006 | Baseline comparison is ALWAYS relative; pre-existing issues in baseline NEVER fail CI gate | `BaselineComparator.diff()` returns delta only; `ci_gate.run_gate()` checks `baseline_delta["new"]`, not `summary["CRITICAL"]` | T-27, T-28 |
| INV-DOCTOR-007 | Doctor is ALWAYS read-only on the target project during scan; no files modified in `project_dir` | Orchestrator never calls any EXTEND or GENERATE tool; `git status` check in integration test asserts zero modifications after full run | T-06 |
| INV-DOCTOR-008 | Checker failures NEVER cause orchestrator to crash; each failure is surfaced as a HIGH finding | `ThreadPoolExecutor` futures caught with broad `except Exception`; error converted to finding with `Severity.HIGH` | T-05, T-06 |

---

## 9. User Stories

### 9.1 Full-scan orchestration

**US-01: Parallel orchestration of all seven VERIFY tools**
- **As a** Staff Engineer reviewing a new microservice before its first sprint
- **I want** a single `fastapi_doctor .` invocation to run all VERIFY tools concurrently
- **So that** I see the complete risk surface — security, dependencies, N+1 queries, schema gaps, test gaps, API compliance, and perf regressions — without issuing seven separate commands
- **Given:** a FastAPI project with 40 routes, 12 SQLAlchemy models, JWT auth, and no pre-existing baseline
- **When:** `fastapi_doctor(project_dir=".", mode="full", emit_fix_plan=True)` is called
- **Then:**
  - `CheckerRegistry.get_checkers(mode="full")` returns exactly 7 enabled checkers: TOOL-028, TOOL-029, TOOL-030, TOOL-031, TOOL-032, TOOL-033, TOOL-034
  - `ThreadPoolExecutor(max_workers=4)` submits all 7 checkers; `as_completed()` collects results within 60s (CC-32, INV-DOCTOR-007)
  - `DoctorOrchestrator._deduplicate()` removes any cross-tool duplicate by `title::location` key before ranking (CC-18)
  - `DoctorReport.summary` contains counts for CRITICAL, HIGH, MEDIUM, LOW, and total (CC-01, CC-02)
  - A Rich summary table is printed to stderr; Markdown report is written to `.fastapi_doctor_report.md`

**US-02: Clean project receives zero-finding report and fresh baseline**
- **As a** developer joining a greenfield service that was scaffolded with best-practice defaults
- **I want** `fastapi_doctor .` to confirm zero findings and save a clean baseline I can commit
- **So that** all future PRs are compared against this known-good snapshot, not an empty slate
- **Given:** all 7 VERIFY tools return empty finding lists; no `.fastapi_doctor.baseline.json` exists yet
- **When:** `fastapi_doctor(project_dir=".", mode="full", fail_on_critical=True)` completes
- **Then:**
  - `DoctorReport.summary["total"] == 0` and `DoctorReport.fix_plan == []` (CC-11)
  - `BaselineComparator.diff()` detects no existing baseline, saves a new one, returns `{"new": 0, "resolved": 0, "unchanged": 0}` (CC-12, INV-DOCTOR-006)
  - `extend_recommendations` may still list TOOL-005, TOOL-020, TOOL-016 if those features are absent (INV-DOCTOR-004)
  - Exit code is 0; `fail_on_critical=True` does not trigger because `summary["CRITICAL"] == 0`

**US-03: CRITICAL security findings surface first and block exit code**
- **As a** security engineer auditing a service that handles file uploads and reads from environment variables
- **I want** TOOL-028 (`security_scan`) findings to be classified CRITICAL and placed at position 1 in the fix plan
- **So that** no developer can miss them or treat them as optional clean-up
- **Given:** `security_scan` (TOOL-028) returns three findings: missing CSP header, unvalidated upload endpoint, hardcoded secret in `config.py`
- **When:** `fastapi_doctor(project_dir=".", fail_on_critical=True)` is called
- **Then:**
  - All three findings have `severity == Severity.CRITICAL` via `classify_finding()` keyword match (INV-DOCTOR-001)
  - Each finding has `tool_ref == "TOOL-028"` and `tool_name == "security_scan"` injected by `Checker._normalize_one()` (INV-DOCTOR-002)
  - Fix plan item 1 reads `"[CRITICAL] RUN: fastapi_skill security_scan . (TOOL-028) → fixes: 3 issues"` (CC-06)
  - CLI exits with code 1; `DoctorOrchestrator.run()` raises after emitting the report

**US-04: Mixed-severity findings from TOOL-030 appear after CRITICAL items**
- **As a** backend developer who just merged a query refactor that inadvertently introduced N+1 patterns
- **I want** TOOL-030 (`n_plus_one_detector`) findings to land in the HIGH tier below any CRITICAL items
- **So that** I address auth-bypass issues first, then performance regressions
- **Given:** TOOL-028 returns 1 CRITICAL (secret leak); TOOL-030 returns 2 HIGH N+1 findings in `GET /items` and `GET /orders`
- **When:** `fastapi_doctor(project_dir=".", mode="full")` completes
- **Then:**
  - `findings` list starts with the CRITICAL finding, then the two HIGH findings (CC-06)
  - `baseline_delta` shows `{"new": 3, "resolved": 0, "unchanged": N}` because no prior baseline contained these (INV-DOCTOR-006)
  - `extend_recommendations` includes `add_caching` (TOOL-007) because `_route_count()` > 20 and no Redis import is detected (INV-DOCTOR-004)
  - Report is available in both Markdown and JSON formats via `--format json` (CC-16)

**US-05: Cross-tool deduplication prevents double-counting a single defect**
- **As a** QA engineer reviewing a report where both TOOL-031 (`schema_coverage`) and TOOL-032 (`test_coverage_gaps`) flag the same undocumented `POST /invoices` endpoint
- **I want** the deduplicated finding list to contain that endpoint exactly once
- **So that** the fix plan does not overcount the remediation effort
- **Given:** TOOL-031 returns a finding `{title: "Undocumented POST /invoices", location: "routes/invoices.py"}` and TOOL-032 returns an identical `title::location` pair
- **When:** `DoctorOrchestrator._deduplicate()` processes the merged raw findings
- **Then:**
  - The output findings list contains exactly one entry for that title+location key (CC-18)
  - `DoctorReport.summary["total"]` reflects the deduplicated count, not the raw sum (CC-02)
  - The surviving finding retains the `tool_ref` of whichever checker first emitted it (INV-DOCTOR-002)
  - `FixPlanBuilder` produces one grouped entry, not two separate entries for TOOL-031 and TOOL-032

---

### 9.2 Fix plan generation

**US-06: Fix plan sorted CRITICAL-first with copy-paste run commands**
- **As a** developer handed a fix plan with 15 items spanning all four severity levels
- **I want** the plan sorted CRITICAL first, then HIGH, MEDIUM, LOW, and within each tier by finding count descending
- **So that** I can start at item 1 and work top-to-bottom without back-tracking
- **Given:** `FixPlanBuilder` receives findings from TOOL-028 (3 CRITICAL), TOOL-030 (2 HIGH), TOOL-032 (5 MEDIUM), TOOL-031 (5 LOW)
- **When:** `FixPlanBuilder.build()` is called
- **Then:**
  - Item 1 is the TOOL-028 entry with `severity == "CRITICAL"` and `total_fixes == 3` (CC-06, INV-DOCTOR-003)
  - Item 2 is the TOOL-030 entry with `severity == "HIGH"` and `total_fixes == 2`
  - Every item has a `run_command` matching `r"^fastapi_skill \w+ \.$"` for copy-paste execution (T-16)
  - Calling `build()` a second time on the same input produces byte-for-byte identical JSON (INV-DOCTOR-003, T-15)

**US-07: Dependency-aware ordering places add_auth before add_rbac and add_mfa**
- **As a** developer whose fix plan includes both `add_auth` (TOOL-005) and `add_rbac` (TOOL-006) findings
- **I want** TOOL-005 to appear before TOOL-006 in the plan regardless of finding counts
- **So that** running items top-to-bottom never results in `add_rbac` executing before auth scaffolding exists
- **Given:** `FixPlanBuilder.DEPENDENCIES` declares `add_rbac` and `add_mfa` both depend on `add_auth`; TOOL-006 has 4 findings vs TOOL-005 has 1
- **When:** `FixPlanBuilder._sort_by_severity_and_deps()` processes the items
- **Then:**
  - TOOL-005 (`add_auth`) appears at a lower order number than TOOL-006 (`add_rbac`) even though TOOL-006 has more findings (CC-08)
  - TOOL-013 (`add_mfa`) also appears after TOOL-005 for the same dependency reason
  - Fix plan includes `"(requires: TOOL-005 add_auth)"` annotation on TOOL-006 and TOOL-013 items (INV-DOCTOR-003)

**US-08: Findings grouped by tool so one command resolves N issues**
- **As a** developer staring at 50 individual findings scattered across 7 categories
- **I want** the fix plan to consolidate them into at most 7 groups, one per VERIFY tool
- **So that** I can resolve all 50 issues with at most 7 `fastapi_skill` invocations
- **Given:** 10 findings from TOOL-028, 8 from TOOL-029, 7 from TOOL-030, 6 from TOOL-031, 9 from TOOL-032, 5 from TOOL-033, 5 from TOOL-034
- **When:** `FixPlanBuilder.build()` groups by `(tool_ref, tool_name)` key
- **Then:**
  - Output contains exactly 7 items, one per tool (CC-07)
  - Each item's `total_fixes` equals the count of findings for that tool
  - `fixes_critical`, `fixes_high`, `fixes_medium`, `fixes_low` break down the severity distribution per tool
  - `order` field is sequential 1..7 with no gaps (T-18)

**US-09: Fix plan reflects resolved items after TOOL-028 and TOOL-029 are run**
- **As a** developer who executed items 1 and 2 of the fix plan (TOOL-028 and TOOL-029)
- **I want** the next `fastapi_doctor .` run to show those tools absent from the fix plan
- **So that** the plan shrinks predictably as I work through it
- **Given:** after running `fastapi_skill security_scan .` and `fastapi_skill dep_audit .`, both tools now return 0 findings; remaining tools still have findings
- **When:** `fastapi_doctor(project_dir=".", mode="full")` runs again
- **Then:**
  - `BaselineComparator.diff()` shows `resolved` count equal to the sum of former TOOL-028 and TOOL-029 findings (INV-DOCTOR-006)
  - Fix plan contains 0 entries for TOOL-028 and TOOL-029
  - A new baseline is saved capturing the reduced finding set (CC-12, CC-13)
  - `DoctorReport.summary["CRITICAL"] == 0` assuming all CRITICAL came from those two tools

**US-10: Targeted security-only plan via --only security flag**
- **As a** team lead who has allocated this sprint exclusively to security remediation
- **I want** `fastapi_doctor . --only security` to produce a plan restricted to TOOL-028 and TOOL-029
- **So that** performance and quality findings do not dilute the sprint board
- **Given:** `mode="targeted"` with `--only=security`; project has findings across all 7 VERIFY tools
- **When:** `CheckerRegistry.get_checkers(mode="targeted")` filters by `category="security"`
- **Then:**
  - Only `security_scan` (TOOL-028) and `dep_audit` (TOOL-029) checkers execute (CC-34)
  - Fix plan contains entries only for TOOL-028 and TOOL-029; no performance or compliance items appear
  - Total run time < 10s because only 2 of 7 checkers execute
  - EXTEND recommendations are suppressed (`include_extend=False`) to keep scope focused

---

### 9.3 EXTEND recommendations

**US-11: audit_log recommended when 30+ mutable models lack change history**
- **As a** developer maintaining a billing service with 30 SQLAlchemy models and no audit trail
- **I want** the doctor to surface a recommendation for TOOL-009 (`add_audit_log`)
- **So that** I am reminded of the compliance gap before a customer data incident reveals it
- **Given:** `RecommendationEngine._model_count()` traverses `models*.py` and counts 30 `ClassDef` nodes; `_has_file(project_dir, "audit")` finds no matching file
- **When:** `RecommendationEngine.analyze(findings)` evaluates the `add_audit_log` trigger
- **Then:**
  - Trigger lambda returns True; recommendation appended with `tool_ref == "TOOL-009"` (INV-DOCTOR-004, CC-09)
  - `reason` reads `"5+ mutable models found; no audit_log table detected"`
  - `priority` is `"MEDIUM"` because the reason string contains no `"auth"` keyword
  - After developer runs `fastapi_skill add_audit_log .`, re-run detects `audit_log.py` and suppresses the recommendation (CC-10, T-20)

**US-12: RBAC recommended for JWT auth project with no roles module**
- **As a** developer building a multi-role SaaS API with JWT auth but no permission layer
- **I want** the doctor to recommend `add_rbac` (TOOL-006) with HIGH priority
- **So that** I do not ship an API where every authenticated user has superuser-equivalent access
- **Given:** `_has_auth(project_dir)` returns True (detects `auth.py` and `jwt` import); `_has_file(project_dir, "rbac")` returns False
- **When:** `RecommendationEngine.analyze(findings)` runs the `add_rbac` trigger
- **Then:**
  - Recommendation `{tool: "add_rbac", tool_ref: "TOOL-006", priority: "HIGH"}` is added (INV-DOCTOR-004, CC-09)
  - After developer runs `fastapi_skill add_rbac .`, `_has_file(project_dir, "rbac")` returns True
  - Second doctor run emits no `add_rbac` recommendation, satisfying the no-duplicate invariant (CC-10, T-22)
  - `extend_recommendations` also includes TOOL-013 (`add_mfa`) if `pyotp` is absent, surfacing both auth-hardening gaps in one scan

**US-13: MFA recommended for auth service missing TOTP middleware**
- **As a** developer who shipped JWT login but has not yet added two-factor authentication
- **I want** the doctor to surface TOOL-013 (`add_mfa`) as a HIGH-priority recommendation
- **So that** the gap is visible during the next sprint planning session
- **Given:** `_has_auth(project_dir)` is True; `_has_import(project_dir, "pyotp", "totp")` is False
- **When:** `RecommendationEngine.analyze(findings)` evaluates the `add_mfa` pattern trigger
- **Then:**
  - `add_mfa` recommendation appears with `priority == "HIGH"` and `tool_ref == "TOOL-013"` (INV-DOCTOR-004, T-21)
  - Recommendation is never duplicated even if both `_has_auth` and route-count triggers fire simultaneously
  - `run_command == "fastapi_skill add_mfa ."` for copy-paste use
  - After developer installs `pyotp` and re-runs, `_has_import(project_dir, "pyotp")` returns True and no recommendation is emitted (T-22)

**US-14: Caching recommended for high-route-count project with no Redis**
- **As a** developer who has grown to 25 API routes but has not added any caching layer
- **I want** the doctor to recommend `add_caching` (TOOL-007) when route count exceeds 20 and Redis is absent
- **So that** I am nudged toward caching before latency complaints start arriving
- **Given:** `_route_count(project_dir)` returns 25; `_has_import(project_dir, "redis", "cache")` returns False
- **When:** `RecommendationEngine.analyze(findings)` evaluates the `add_caching` trigger
- **Then:**
  - `add_caching` recommendation appears with `tool_ref == "TOOL-007"` and `priority == "MEDIUM"` (CC-09, T-23)
  - `reason` reads `"20+ routes found; no caching layer detected"`
  - Recommendation includes a copy-paste `run_command` for immediate use
  - If `n_plus_one_detector` (TOOL-030) also surfaces HIGH findings, the `add_caching` recommendation is annotated as related to TOOL-030 findings

**US-15: No background-tasks recommendation when ARQ is already present**
- **As a** developer who added ARQ task queues last sprint and wants to confirm the doctor no longer flags that gap
- **I want** the `add_background_tasks` (TOOL-016) recommendation to be absent from the report
- **So that** EXTEND recommendations stay signal-rich and do not pad with false positives
- **Given:** `_has_import(project_dir, "arq", "celery", "dramatiq")` returns True because `import arq` is in `tasks/worker.py`
- **When:** `RecommendationEngine.analyze(findings)` evaluates the `add_background_tasks` trigger
- **Then:**
  - Pattern trigger lambda returns False; `add_background_tasks` is not appended (INV-DOCTOR-004, CC-10)
  - `extend_recommendations` list does not contain any entry with `tool_ref == "TOOL-016"`
  - No false-positive recommendation rate violation (< 5% per QS threshold)
  - Re-run after removing ARQ would correctly re-surface the recommendation (T-20)

---

### 9.4 Baseline comparison and modes

**US-16: Quick mode delivers top-10 findings in under 10s for pre-commit hooks**
- **As a** developer who has configured `fastapi_doctor . --mode quick` as a git pre-commit hook
- **I want** the scan to complete in under 10s and surface all CRITICAL findings even when total count exceeds 10
- **So that** the hook never blocks commits on a slow machine and never silently drops critical issues
- **Given:** quick mode; 5 CRITICAL findings from TOOL-028 + TOOL-029; 20 additional LOW findings from other checkers
- **When:** `DoctorOrchestrator.run(mode="quick")` executes
- **Then:**
  - `CheckerRegistry.get_checkers(mode="quick")` returns only `security_scan` (TOOL-028) and `dep_audit` (TOOL-029) (QS-5)
  - All 5 CRITICAL findings are promoted before the 10-item cap is applied (INV-DOCTOR-005, CC-20)
  - Wall-clock time < 10s (CC-33)
  - EXTEND recommendations are skipped to stay within time budget (`include_extend=False` in quick mode)

**US-17: Baseline delta passes CI even with 3 pre-existing CRITICALs**
- **As a** CI system running `fastapi_doctor . --ci --delta-only` on a PR that adds a new feature file
- **I want** the gate to exit 0 when the PR does not introduce any new findings beyond the committed baseline
- **So that** a team that inherited legacy security debt is not perpetually blocked on unrelated PRs
- **Given:** `.fastapi_doctor.baseline.json` contains fingerprints for 3 CRITICAL findings; the current scan returns the same 3 CRITICALs unchanged
- **When:** `ci_gate.run_gate(delta_only=True, fail_on_critical=True)` executes
- **Then:**
  - `BaselineComparator.diff()` returns `{"new": 0, "resolved": 0, "unchanged": 3}` (INV-DOCTOR-006, CC-24)
  - `run_gate()` returns exit code 0 because `baseline_delta["new"] == 0`
  - CI log prints `"[doctor ci-gate] PASS: 3 total findings, 0 new, 0 resolved"` (T-28)
  - Report is still generated so the team can see the pre-existing issues in the artifact store

**US-18: Targeted performance mode runs only TOOL-030 and TOOL-034**
- **As a** developer running `fastapi_doctor . --only performance` during a performance sprint
- **I want** only `n_plus_one_detector` (TOOL-030) and `perf_baseline` (TOOL-034) to execute
- **So that** the report is narrowly focused and run time stays under 15s
- **Given:** `mode="targeted"` with `--only=performance`; all 7 checkers are registered
- **When:** `CheckerRegistry.get_checkers(mode="targeted")` filters by `category="performance"`
- **Then:**
  - Exactly TOOL-030 and TOOL-034 checkers are invoked; TOOL-028, TOOL-029, TOOL-031, TOOL-032, TOOL-033 are skipped (CC-34)
  - Fix plan contains only performance-category entries; security and compliance cells show 0
  - Run time < 15s and typically < 5s on projects under 30k LOC
  - Skipped checkers appear in the report as `"skipped (targeted mode)"` with `CheckerResult.skipped=True` (QS-9)

**US-19: Baseline reset clears stale snapshot before a major refactor**
- **As a** developer about to start a major API versioning refactor that will invalidate all current baseline fingerprints
- **I want** `fastapi_doctor . --reset-baseline` to clear the existing snapshot and start fresh
- **So that** the first post-refactor CI run saves a new baseline without comparing against stale fingerprints
- **Given:** `.fastapi_doctor.baseline.json` exists with 20 fingerprints from before the refactor
- **When:** CLI calls `BaselineComparator.reset()` then exits 0 (CC-27)
- **Then:**
  - `BaselineComparator.reset()` deletes `.fastapi_doctor.baseline.json` (CC-13)
  - CLI prints `"Baseline cleared — next run will save a fresh snapshot"`
  - Subsequent `fastapi_doctor .` run detects no baseline file, saves a new one, returns `{"new": 0, "resolved": 0, "unchanged": N}` (INV-DOCTOR-006, CC-11)
  - `git status` shows `.fastapi_doctor.baseline.json` as deleted (INV-DOCTOR-007)

**US-20: New SQL injection in a PR triggers CI gate failure with exact location**
- **As a** CI system on a PR that introduces a raw string query in `routes/users.py:47`
- **I want** `fastapi_doctor . --ci --delta-only` to exit 1 and print the exact file and line to stderr
- **So that** the developer sees the precise defect without reading the full report
- **Given:** `security_scan` (TOOL-028) returns a new CRITICAL finding `{title: "SQL injection", location: "routes/users.py:47"}`; this fingerprint is absent from the committed baseline
- **When:** `ci_gate.run_gate(delta_only=True, fail_on_critical=True)` runs
- **Then:**
  - `BaselineComparator.diff()` returns `{"new": 1, ...}` because the fingerprint is novel (INV-DOCTOR-006)
  - `run_gate()` returns exit code 1 (CC-23)
  - stderr prints `"[CRITICAL NEW] SQL injection @ routes/users.py:47"` (INV-DOCTOR-001)
  - PR merge is blocked; developer resolves the query parameterization before re-running (T-28)

---

### 9.5 Report rendering and CI

**US-21: Nightly CI generates a 30-page HTML report as a build artifact**
- **As a** engineering manager whose team reviews the nightly health report on an internal dashboard
- **I want** `fastapi_doctor . --format html` to produce a valid, severity-color-coded HTML file in under 1s
- **So that** the team can browse findings by severity without downloading a raw Markdown file
- **Given:** `DoctorReport` has 45 findings across all severity levels; `ReportRenderer` is called with `fmt="html"`
- **When:** `ReportRenderer.render("html")` invokes `Jinja2` with the `report.html.j2` template
- **Then:**
  - Output contains `<html>` and `</html>` tags and passes `json.loads` on the embedded JSON block (CC-15)
  - Render time < 1s (SLO from Section 3)
  - `ReportTemplateBuilder.build_context()` groups findings by severity and sets `severity_colors` for CRITICAL=`#dc2626` etc.
  - `has_critical` context flag is True, causing the template to render a red alert banner (CC-28)

**US-22: PDF report generated for executive sign-off with WeasyPrint fallback**
- **As a** CISO who needs a signed-off PDF for a compliance audit
- **I want** `fastapi_doctor . --format pdf` to produce a `.pdf` file under 5s or gracefully fall back to HTML
- **So that** the compliance review is never blocked by a missing WeasyPrint installation
- **Given:** WeasyPrint is installed; `DoctorReport` has 20 findings and a 5-item fix plan
- **When:** `ReportRenderer._render_pdf()` is called
- **Then:**
  - `fastapi_doctor_report.pdf` is written with `size > 0` bytes within 5s (QS-11, CC-17, T-30)
  - If `ImportError` on WeasyPrint, fallback writes `fastapi_doctor_report.html` and returns `"HTML fallback"` in the message
  - PDF contains all four sections: summary table, findings list, fix plan, EXTEND recommendations
  - `DoctorReport.model_dump_json()` serializes without error, confirming Pydantic validation passed (CC-31)

**US-23: Large project with 1000 routes uses chunked rendering without OOM**
- **As a** developer on a monolith with 1000 routes and 200+ findings running `fastapi_doctor . --format html`
- **I want** the HTML render to complete without exhausting Jinja2 memory or producing a single 200-page block
- **So that** CI artifact storage receives a navigable report with page break markers
- **Given:** `DoctorReport.findings` has 200 entries; `ReportTemplateBuilder.MAX_FINDINGS_PER_SECTION == 50`
- **When:** `ReportTemplateBuilder.build_context()` checks `_is_large_report()`
- **Then:**
  - `context["chunked"] == True` because 200 > 100 (CC-29)
  - `context["chunks"]` contains 4 sub-lists each with 50 findings
  - Peak memory stays under 512 MB throughout the render (SLO from Section 3)
  - HTML output contains page-break markers between chunks for PDF pagination (QS-12)

**US-24: GitHub Actions workflow annotates PR with inline findings**
- **As a** developer reviewing a PR in the GitHub UI
- **I want** `fastapi_doctor` to post inline annotations on the changed files rather than requiring me to open a separate report artifact
- **So that** I see security and quality issues directly on the diff without context switching
- **Given:** `.github/workflows/doctor.yml` is generated by the tool with `--ci --delta-only --format markdown`; CI runs on every PR
- **When:** the CI workflow step invokes `fastapi_doctor . --ci --delta-only` and parses `DoctorReport.findings`
- **Then:**
  - Each new finding is emitted as a GitHub annotation via `::error file={location}::` syntax (CC-30)
  - CRITICAL findings produce `::error` annotations; HIGH findings produce `::warning`; MEDIUM and LOW produce `::notice`
  - `Makefile` target `make doctor-ci` runs `ci_gate.py` and is generated as part of the 12+ scaffolded files (CC-30)
  - Annotations only cover `baseline_delta["new"]` findings, not pre-existing ones, honoring the delta-only contract (INV-DOCTOR-006)

**US-25: Corrupted baseline triggers recovery hint without crashing the scan**
- **As a** developer whose `.fastapi_doctor.baseline.json` was mangled by a git merge conflict
- **I want** `fastapi_doctor .` to detect the corruption, continue the scan with full findings, and print an actionable recovery hint
- **So that** the scan result is still useful even though baseline comparison is unavailable
- **Given:** `.fastapi_doctor.baseline.json` contains merge-conflict markers making it invalid JSON
- **When:** `BaselineComparator.diff()` calls `json.loads()` on the corrupted file
- **Then:**
  - `json.JSONDecodeError` is caught; method returns `{"new": N, "resolved": 0, "unchanged": 0, "error": 1}` (INV-DOCTOR-008)
  - CLI prints `"Baseline corrupted — run with --reset-baseline to regenerate"` to stderr
  - The scan continues; `DoctorReport.findings` and `fix_plan` are fully populated and accurate (INV-DOCTOR-008)
  - Exit code reflects the actual finding severity, not the baseline error, so a clean project still exits 0 (INV-DOCTOR-006, CC-24)
## 10. Test Plan

### 10.1 Orchestration Tests (T-01..T-06)

**T-01** — `test_all_verify_tools_invoked_in_full_mode`
Given a project dir and `mode="full"`, assert that `CheckerRegistry.get_checkers()` returns exactly 7 checkers covering TOOL-028..034 and that all 7 `run()` methods are called during `DoctorOrchestrator.run()`.

**T-02** — `test_checker_results_aggregated_correctly`
Given 3 checkers each returning 5 findings (15 total with no duplicates), assert that `DoctorOrchestrator._deduplicate()` preserves all 15 and `report.summary["total"] == 15`.

**T-03** — `test_deduplication_removes_same_title_and_location`
Given 2 checkers both returning a finding with `title="Missing CSP header"` and `location="app/main.py"`, assert that the aggregated list contains exactly 1 copy of that finding.

**T-04** — `test_findings_sorted_by_severity_before_quick_truncation`
Given 5 LOW findings and 3 CRITICAL findings, assert that the sorted list starts with all 3 CRITICALs before any LOW finding regardless of the order they arrived from checkers.

**T-05** — `test_checker_exception_becomes_high_finding`
Given a checker whose `run()` raises `RuntimeError("unexpected error")`, assert the orchestrator does not propagate the exception and instead adds one HIGH finding with `title` containing the checker name.

**T-06** — `test_doctor_does_not_modify_project_files`
After `DoctorOrchestrator.run()` on a real project dir, assert `subprocess.run(["git", "status", "--porcelain"])` returns empty stdout, proving zero files were modified by the doctor scan itself.

### 10.2 Severity Tests (T-07..T-12)

**T-07** — `test_severity_enum_sort_order`
Assert `Severity.CRITICAL < Severity.HIGH < Severity.MEDIUM < Severity.LOW` holds for all four enum values as integer comparison.

**T-08** — `test_severity_from_string_case_insensitive`
Assert `Severity.from_string("critical") == Severity.from_string("CRITICAL") == Severity.CRITICAL` and same for all four levels.

**T-09** — `test_finding_without_severity_defaults_to_medium`
Given a raw checker output dict missing `severity` key, assert `Checker._normalize_one()` produces `Severity.MEDIUM`.

**T-10** — `test_classify_finding_sql_injection_is_critical`
Assert `classify_finding("sql injection found", "security") == Severity.CRITICAL` for exact keyword match.

**T-11** — `test_classify_finding_security_category_defaults_high`
Assert `classify_finding("unknown security issue", "security") == Severity.HIGH` when no critical keywords match.

**T-12** — `test_severity_emoji_returns_correct_icon`
Assert `Severity.CRITICAL.emoji() == "🔴"` and `Severity.LOW.emoji() == "🟢"`.

### 10.3 Fix Plan Tests (T-13..T-18)

**T-13** — `test_fix_plan_groups_findings_by_tool`
Given 4 CRITICAL findings all from `security_scan` (TOOL-028) and 2 HIGH from `dep_audit` (TOOL-029), assert `FixPlanBuilder.build()` returns 2 items (one per tool) with correct `total_fixes` counts.

**T-14** — `test_fix_plan_critical_first`
Given a mixed input of MEDIUM and CRITICAL findings from different tools, assert the first item in the returned plan has `severity == "CRITICAL"`.

**T-15** — `test_fix_plan_deterministic`
Call `FixPlanBuilder.build()` twice on the same shuffled input list (shuffle with fixed seed between calls). Assert both outputs are byte-for-byte identical after JSON serialization.

**T-16** — `test_fix_plan_run_command_format`
Assert every item in the fix plan has a `run_command` string matching `r"^fastapi_skill \w+ \.$"`.

**T-17** — `test_fix_plan_respects_dependency_order`
Given findings from both `add_mfa` and `add_auth` tools with `add_mfa` having higher finding count, assert `add_auth` appears before `add_mfa` in the plan due to dependency ordering.

**T-18** — `test_fix_plan_order_field_sequential`
Assert that the `order` field on returned items is 1, 2, 3, ... N with no gaps or duplicates.

### 10.4 Recommendation Tests (T-19..T-24)

**T-19** — `test_recommend_audit_log_when_many_models`
Create a temp project with 6 model class definitions and no `audit` file. Assert `RecommendationEngine.analyze([])` includes a recommendation for `add_audit_log` (TOOL-009).

**T-20** — `test_no_recommendation_when_feature_present`
Create a temp project with `rbac.py` present. Assert no `add_rbac` recommendation emitted.

**T-21** — `test_recommend_mfa_when_auth_present_and_pyotp_absent`
Create a temp project with `auth.py` importing `jwt` but no `pyotp` usage. Assert `add_mfa` (TOOL-013) in recommendations.

**T-22** — `test_no_mfa_recommendation_when_pyotp_imported`
Create a temp project with `import pyotp` present. Assert no `add_mfa` recommendation emitted.

**T-23** — `test_recommend_caching_when_many_routes`
Create a temp project with 25 `@router.get(` decorators and no Redis import. Assert `add_caching` (TOOL-007) in recommendations.

**T-24** — `test_recommendations_have_required_fields`
Assert every recommendation dict contains `tool`, `tool_ref`, `reason`, `run_command`, and `priority` keys.

### 10.5 Edge Case and Baseline Tests (T-25..T-30)

**T-25** — `test_custom_config_disables_checker`
Create a `.fastapi_doctor.yaml` with `disable: [security_scan]`. Assert `CheckerRegistry.get_checkers()` does not include the `security_scan` checker.

**T-26** — `test_quick_mode_always_includes_critical`
Feed `DoctorOrchestrator` in quick mode with 5 CRITICAL findings and 20 LOW findings. Assert all 5 CRITICALs are in the output and total <= 10.

**T-27** — `test_baseline_diff_returns_delta_not_absolute`
Save a baseline with 3 CRITICAL findings. Run diff with same 3 CRITICALs. Assert `delta["new"] == 0` and `delta["unchanged"] == 3`.

**T-28** — `test_ci_gate_fails_only_on_new_critical`
Save baseline with 1 CRITICAL. Run gate with 2 CRITICALs (original + new). Assert `run_gate()` returns exit code 1 and `delta["new"] == 1`.

**T-29** — `test_idempotent_run_produces_same_report`
Run `DoctorOrchestrator.run()` twice on the same project with the same mock checkers. Assert `report1.model_dump_json() == report2.model_dump_json()`.

**T-30** — `test_pdf_render_falls_back_to_html`
Mock `weasyprint` as unavailable (`ImportError`). Call `ReportRenderer.render("pdf")`. Assert a `.html` file is written and return string contains `"HTML fallback"`.

---

## 11. Interaction Matrix

| Tool | Direction | What Doctor Consumes | How Doctor Uses It |
|------|-----------|---------------------|-------------------|
| `security_scan` (TOOL-028) | Orchestrates → | Full findings list with severities | Aggregated into CRITICAL/HIGH; first in fix plan if any CRITICAL found |
| `dep_audit` (TOOL-029) | Orchestrates → | Vulnerable dependency list with CVE refs | Merged with security findings; CVE severity mapped to CRITICAL/HIGH |
| `n_plus_one_detector` (TOOL-030) | Orchestrates → | Route-level N+1 findings with query counts | Classified as HIGH; triggers `add_caching` recommendation if > 5 routes affected |
| `schema_coverage` (TOOL-031) | Orchestrates → | Undocumented model/route schema gaps | Classified as MEDIUM/LOW; feeds `test_coverage_gaps` deduplication check |
| `test_coverage_gaps` (TOOL-032) | Orchestrates → | Uncovered code paths and missing test files | Classified as MEDIUM; triggers `add_testing` recommendation if coverage < 80% |
| `api_compliance` (TOOL-033) | Orchestrates → | OpenAPI spec violations, versioning gaps | Classified as MEDIUM; triggers `add_versioning` recommendation if no `/v1/` prefix |
| `perf_baseline` (TOOL-034) | Orchestrates → | Latency regressions, SLA violations | Classified as HIGH; triggers `add_caching` or `add_async_db` recommendation |
| `add_auth` (TOOL-005) | Recommends → | Presence detection via `_has_auth()` | Recommended if no auth module found; marked HIGH priority |
| `add_rbac` (TOOL-006) | Recommends → | Auth presence + RBAC absence check | Recommended if auth detected and no rbac module; depends on TOOL-005 |
| `add_caching` (TOOL-007) | Recommends → | Route count > 20 + no Redis import | Recommended for high-route-count projects without caching layer |
| `add_multi_tenancy` (TOOL-008) | Recommends → | Tenant keyword detection in models | Recommended if model names suggest multi-tenant but no `tenant_id` column |
| `add_audit_log` (TOOL-009) | Recommends → | Model count > 5 + no audit file | Recommended when mutable models lack change history |
| `add_mfa` (TOOL-013) | Recommends → | Auth presence + no pyotp/totp import | Recommended when auth exists without MFA; HIGH priority |
| `add_rate_limiting` (TOOL-014) | Recommends → | Auth presence + no slowapi/limits import | Recommended for authenticated APIs lacking rate limiting |
| `add_background_tasks` (TOOL-016) | Recommends → | No ARQ/Celery/Dramatiq import detected | Recommended for projects with no async task queue |
| `add_observability` (TOOL-020) | Recommends → | No OpenTelemetry/Prometheus import | Recommended for all production projects lacking instrumentation |
| `add_websocket` (TOOL-025) | Recommends → | WebSocket keyword in route comments | Recommended if `websocket` appears in comments but no actual WS routes |
| `add_i18n` (TOOL-024) | Recommends → | Multi-locale string hints in source | Recommended when locale strings detected but no i18n library imported |
| OPERATE tools (TOOL-035..042) | Context → | Operational findings (SLA, pool config) | Doctor surfaces operational gaps; links to relevant OPERATE tools in report |
| EVOLVE tools (TOOL-043..050) | Suggests → | Architecture maturity level from findings | Doctor mentions relevant EVOLVE tools in "Next Steps" section of report |

---

## 12. Rollback Procedure

### 12.1 Overview

`fastapi_doctor` is a **read-only** tool during scan operations. It never modifies the target project's source files, never runs database migrations, and never starts the target application process. The only files it creates are:
- `.fastapi_doctor.baseline.json` — snapshot file in project root (recoverable)
- Report output files — Markdown, HTML, JSON, PDF (all regenerable)
- CI workflow file — `.github/workflows/doctor.yml` (version-controlled)
- `doctor/` module — the doctor engine itself (separate from target project)

For each failure mode, the rollback strategy is described below.

### 12.2 Database Rollback

N/A — `fastapi_doctor` does not connect to or modify any database. The tool uses static analysis (AST, file system inspection, import graph) exclusively. No database credentials are read, no migrations are applied, and no data is written to any persistence layer.

### 12.3 Failure Mode: VERIFY Tool Crash During Orchestration

**Symptoms:** One or more VERIFY tools (TOOL-028..034) raise an unhandled exception mid-scan, producing a HIGH finding with `"Checker X failed"` title.

**Diagnosis:**
```bash
# Check which checker failed
fastapi_doctor . --format json | python3 -c "
import json, sys
r = json.load(sys.stdin)
for f in r['findings']:
    if 'failed' in f['title']:
        print(f['title'], f['detail'])
"
```

**Recovery:**
1. Identify the failing checker name from the finding title.
2. Verify the checker's dependency is installed: `pip show skill001-<checker-name>`.
3. If missing, install: `pip install 'skill001[all]'`.
4. If checker has a bug, disable it temporarily via `.fastapi_doctor.yaml`:

```yaml
# .fastapi_doctor.yaml
disable:
  - failing_checker_name
```

5. Re-run the scan: `fastapi_doctor . --format markdown`.
6. The disabled checker will appear as a WARNING in the report, not a failure.
7. File a bug report against the checker's SKILL-001 tool for the underlying exception.

### 12.4 Failure Mode: Baseline Corruption

**Symptoms:** `.fastapi_doctor.baseline.json` is malformed (merge conflict markers, partial write, truncation). `BaselineComparator.diff()` returns `{"error": 1}`. CLI prints baseline corruption warning.

**Diagnosis:**
```bash
# Verify corruption
python3 -c "import json; json.load(open('.fastapi_doctor.baseline.json'))"
```

**Recovery:**
1. Reset the baseline to start fresh: `fastapi_doctor . --reset-baseline`.
2. Re-run a full scan to establish a new clean baseline: `fastapi_doctor .`.
3. If the project has known pre-existing issues that should not block CI, review and acknowledge them: `fastapi_doctor . --ci --delta-only --save-baseline`.
4. Commit the new baseline: `git add .fastapi_doctor.baseline.json && git commit -m "chore: regenerate doctor baseline"`.

### 12.5 Failure Mode: PDF Render Failure

**Symptoms:** `fastapi_doctor . --format pdf` raises an error or produces an empty/corrupt PDF file.

**Diagnosis:**
```bash
python3 -c "from weasyprint import HTML; print('weasyprint ok')"
```

**Recovery:**
1. If WeasyPrint is not installed, the doctor automatically falls back to HTML output. No action needed for routine use.
2. To enable PDF: `pip install weasyprint` (requires Cairo/Pango system libraries).
3. On macOS: `brew install cairo pango`.
4. On Ubuntu: `apt-get install libcairo2 libpango-1.0-0 libgdk-pixbuf2.0-0`.
5. If PDF generation fails despite WeasyPrint installed, use the HTML fallback and convert manually: `wkhtmltopdf fastapi_doctor_report.html report.pdf`.

### 12.6 Failure Mode: EXTEND Recommendation False Positive

**Symptoms:** Doctor recommends a tool the project already has. For example, recommends `add_caching` even though Redis is already integrated.

**Diagnosis:** Presence detection (`_has_import()`) missed the import because it uses an alias or indirect dependency.

**Recovery:**
1. Verify detection logic: `python3 -c "from doctor.recommendations import _has_import; from pathlib import Path; print(_has_import(Path('.'), 'redis', 'cache'))"`.
2. If detection returns False due to aliased import (`import redis as rd`), add the alias to the pattern list.
3. Suppress the specific recommendation via config:

```yaml
# .fastapi_doctor.yaml
suppress_recommendations:
  - add_caching
```

4. Open a PR to improve the detection pattern in `RecommendationEngine` to handle the alias case.

### 12.7 Failure Mode: CI Gate False Positive (Blocking Legitimate PR)

**Symptoms:** CI gate fails on a PR that introduces no security regressions. A pre-existing issue that was not in the baseline is being flagged as new.

**Diagnosis:**
```bash
# Show delta vs baseline
fastapi_doctor . --ci --delta-only --format json | python3 -c "
import json, sys
r = json.load(sys.stdin)
print('delta:', r['baseline_delta'])
print('new findings:')
for f in r['findings']:
    print(' ', f['severity'], f['title'])
" 2>&1 | head -40
```

**Recovery:**
1. If the "new" finding is actually pre-existing but not in baseline (e.g., baseline was generated on a different branch), regenerate: `fastapi_doctor . --reset-baseline && fastapi_doctor . --save-baseline`.
2. If the finding is a genuine regression that the team wants to acknowledge, update the baseline on main: `git checkout main && fastapi_doctor . --save-baseline && git add .fastapi_doctor.baseline.json && git commit -m "chore: acknowledge known issue in baseline"`.
3. If the CI gate is blocking an urgent hotfix, temporarily disable with environment variable: `FASTAPI_DOCTOR_SKIP=1 fastapi_doctor . --ci` (logs a prominent WARNING).
4. Never delete the baseline without regenerating it; use `--reset-baseline` then re-run to establish clean state.

---

## 13. Edge Cases

| ID | Input Condition | Expected Behavior |
|----|----------------|-------------------|
| EC-01 | Empty project with < 2 models and 0 routes | Zero findings returned; 3 bootstrap tool recommendations emitted including `add_auth` and `add_observability` |
| EC-02 | Perfectly clean project passing all checks | Zero findings; clean baseline saved; exit code 0; EXTEND recommendations still shown |
| EC-03 | New CRITICAL SQL injection introduced in PR that was not in baseline | CI gate returns exit code 1; finding printed to stderr with file and line reference |
| EC-04 | Pre-existing CRITICAL that is identical fingerprint in baseline | CI gate returns exit code 0; baseline delta shows `new=0`; no blocking of PR |
| EC-05 | Fix plan has 50+ items from 10 different tools | Plan grouped by tool (max 10 commands); no individual findings listed at top level |
| EC-06 | EXTEND recommendation for `add_i18n` on single-locale app with no hints | Trigger returns False (`_has_i18n_hint()` finds no locale strings); no recommendation emitted |
| EC-07 | Custom config disables all security checks via `disable: [security_scan, dep_audit]` | Both checkers skipped with WARNING in report; fix plan contains no security items |
| EC-08 | Quick mode requested with 50 total findings (15 CRITICAL, 35 LOW) | All 15 CRITICALs returned; no LOW findings included due to 10-item critical-first logic |
| EC-09 | PDF render requested but WeasyPrint not installed | HTML fallback file written; return string contains `"WeasyPrint unavailable"` message |
| EC-10 | Doctor re-run with no code changes between runs | Identical fingerprint set produces `{"new":0,"resolved":0}`; idempotent behavior confirmed |
| EC-11 | Multiple CRITICAL findings in same file from different checkers | Grouped by file in report section; deduplicated where title+location match exactly |
| EC-12 | VERIFY tool dependency (e.g., `skill001.schema_coverage`) is not installed | Checker returns `CheckerResult(skipped=True, skip_reason="dependency missing")` with warning |
| EC-13 | Project with 1000 routes analyzed in full mode | All 7 checkers complete; total wall-clock time stays < 60s via parallel execution |
| EC-14 | Report exceeds 100 pages of findings | `ReportTemplateBuilder._chunk_findings()` splits into 50-item pages with page-break markers |
| EC-15 | `.fastapi_doctor.baseline.json` corrupted by merge conflict markers | `json.JSONDecodeError` caught; delta returns `{"error": 1}`; CLI prints `--reset-baseline` hint |

---

## 14. Acceptance Criteria

✅ 1. `DoctorOrchestrator.run()` invokes all 7 VERIFY tools (TOOL-028..034) in parallel in full mode and returns a `DoctorReport` with `summary["total"]` equal to the total deduplicated finding count.
✅ 2. `FixPlanBuilder.build()` returns items sorted CRITICAL-first with deterministic ordering; identical inputs produce byte-for-byte identical JSON output on two independent calls.
✅ 3. `RecommendationEngine.analyze()` never recommends a feature already present in the project; presence detection correctly identifies auth, rbac, mfa, caching, background tasks, observability, and i18n via `_has_import()` and `_has_file()`.
✅ 4. `BaselineComparator.diff()` returns delta counts (`new`, `resolved`, `unchanged`) not absolute totals; a finding present in both current and baseline counts as `unchanged`, not `new`.
✅ 5. `ci_gate.run_gate(delta_only=True)` returns exit code 0 when all new issues are zero even if baseline contains pre-existing CRITICALs, and returns exit code 1 when at least one new CRITICAL is introduced.
✅ 6. `ReportRenderer.render()` produces valid output for all four formats: Markdown contains `# FastAPI Doctor Report` header, HTML parses as valid DOM, JSON parses via `json.loads()`, PDF file is non-empty (or HTML fallback written if WeasyPrint unavailable).
✅ 7. Quick mode (`mode="quick"`) always includes all CRITICAL findings even when total findings exceed 10, and completes in under 10s on a standard developer laptop.
✅ 8. A checker that raises an unexpected exception during orchestration produces a HIGH finding with the checker name in the title and does not crash the `DoctorOrchestrator.run()` call.
✅ 9. `fastapi_doctor . --reset-baseline` clears `.fastapi_doctor.baseline.json` and exits with code 0 without running any checkers.
✅ 10. All 30 tests (T-01..T-30) pass with zero failures; all CC-01..CC-34 completeness criteria are verified by the test suite.

---

## 15. Implementation Checklist

### 15.1 Core Engine Setup
- [ ] Create `doctor/` package directory with `__init__.py` exporting `DoctorOrchestrator` and `fastapi_doctor` entry function
- [ ] Implement `DoctorOrchestrator.__init__()` accepting all 6 parameters from the tool signature
- [ ] Implement `DoctorOrchestrator.run()` with `ThreadPoolExecutor(max_workers=4)` parallel execution
- [ ] Implement `DoctorOrchestrator._deduplicate()` using `title::location` fingerprint key
- [ ] Implement `DoctorOrchestrator._summarize()` returning per-severity and total counts
- [ ] Validate `DoctorReport` Pydantic model with all required fields serializable to JSON
- [ ] Add timeout `future.result(timeout=60)` to every checker invocation

### 15.2 Checker Registry
- [ ] Implement `CheckerRegistry` class with `VERIFY_TOOLS` list covering all 7 TOOL-028..034 entries
- [ ] Implement `CheckerRegistry._build_checkers()` with graceful ImportError fallback per checker
- [ ] Implement `CheckerRegistry.get_checkers(mode)` filtering by mode and enabled flag
- [ ] Implement `CheckerRegistry._load_config()` reading `.fastapi_doctor.yaml` if present
- [ ] Implement `Checker.run()` with `CheckerResult` return and `skipped` path for ImportError
- [ ] Implement `Checker._normalize_one()` ensuring `severity`, `title`, `tool_ref` always present
- [ ] Verify all 7 checkers are retrievable in full mode via unit test

### 15.3 Severity System
- [ ] Implement `Severity(IntEnum)` with CRITICAL=0, HIGH=1, MEDIUM=2, LOW=3
- [ ] Implement `Severity.from_string()` with case-insensitive mapping including `"info"` → LOW
- [ ] Implement `Severity.label()` returning uppercase name string
- [ ] Implement `Severity.emoji()` returning color-coded emoji per severity level
- [ ] Implement `classify_finding(title, category)` with security_critical keyword list
- [ ] Verify sort order: `CRITICAL < HIGH < MEDIUM < LOW` in T-07

### 15.4 Fix Plan Builder
- [ ] Implement `FixPlanBuilder.__init__()` accepting normalized findings list
- [ ] Implement `FixPlanBuilder.build()` grouping by `(tool_ref, tool_name)` tuple
- [ ] Implement `FixPlanBuilder._worst_severity()` finding worst severity in a group
- [ ] Implement `FixPlanBuilder._sort_by_severity_and_deps()` with stable sort and `DEPENDENCIES` dict
- [ ] Implement `FixPlanBuilder.DEPENDENCIES` covering `add_rbac`, `add_mfa`, `add_rate_limiting`, `add_audit_log`
- [ ] Ensure `order` field is assigned as sequential integers 1..N after sorting
- [ ] Ensure `run_command` format matches `"fastapi_skill {tool_name} ."` pattern

### 15.5 Recommendation Engine
- [ ] Implement `RecommendationEngine.analyze()` iterating `_FEATURE_PATTERNS`
- [ ] Implement `_has_auth()` checking for auth/jwt file and import patterns
- [ ] Implement `_has_file(project_dir, keyword)` checking all `.py` filenames
- [ ] Implement `_has_import(project_dir, *packages)` scanning source for package name occurrences
- [ ] Implement `_model_count(project_dir)` via AST ClassDef count in `models*.py`
- [ ] Implement `_route_count(project_dir)` via regex on `@app.` and `@router.` decorators
- [ ] Implement `_has_i18n_hint(project_dir)` scanning for locale code strings
- [ ] Register all 8 `_FEATURE_PATTERNS` entries (TOOL-006, 007, 009, 013, 014, 016, 020, 024)
- [ ] Wrap each trigger call in `try/except Exception` to prevent engine crash

### 15.6 Baseline Comparator
- [ ] Implement `BaselineComparator.__init__()` setting `baseline_path` relative to project dir
- [ ] Implement `BaselineComparator.diff()` computing delta via frozenset fingerprint comparison
- [ ] Implement `BaselineComparator._fingerprints()` using `severity::title::location` key
- [ ] Implement `BaselineComparator.save()` calling `_save()` with sorted fingerprint list
- [ ] Implement `BaselineComparator.reset()` unlinking baseline file if it exists
- [ ] Handle `json.JSONDecodeError` in `diff()` returning `{"error": 1}` delta
- [ ] Handle `OSError` in `diff()` returning `{"error": 1}` delta with descriptive reason

### 15.7 Report Renderer
- [ ] Implement `ReportRenderer.__init__()` with Jinja2 `PackageLoader` pointing to `doctor/templates/`
- [ ] Implement `ReportRenderer._render_markdown()` with summary table, fix plan, and recommendations
- [ ] Implement `ReportRenderer._render_html()` using `report.html.j2` Jinja2 template
- [ ] Implement `ReportRenderer._render_json()` via `DoctorReport.model_dump_json(indent=2)`
- [ ] Implement `ReportRenderer._render_pdf()` with WeasyPrint and graceful ImportError fallback
- [ ] Create `doctor/templates/report.html.j2` with severity color coding and chunked findings
- [ ] Create `doctor/templates/report.md.j2` for PR comment format

### 15.8 Report Template Builder
- [ ] Implement `ReportTemplateBuilder.build_context()` returning full Jinja2 context dict
- [ ] Implement `ReportTemplateBuilder._group_by_severity()` for findings grouping
- [ ] Implement `ReportTemplateBuilder._group_fix_plan()` for fix plan grouping
- [ ] Implement `ReportTemplateBuilder._is_large_report()` threshold at 100 findings
- [ ] Implement `ReportTemplateBuilder._chunk_findings()` with 50-item pages
- [ ] Include `severity_colors` dict in context for HTML template color-coding

### 15.9 CI Gate
- [ ] Implement `ci_gate.run_gate()` with `delta_only` parameter
- [ ] Ensure `run_gate()` returns exit codes 0 (pass), 1 (new critical), 2 (error)
- [ ] Print first 5 new CRITICAL findings to stderr when gate fails
- [ ] Implement `ci_gate.main()` with argparse for `--project-dir`, `--fail-on-critical`, `--delta-only`, `--mode`
- [ ] Add `[tool.fastapi-doctor.ci]` section in `pyproject.toml` with default CI config
- [ ] Create `.github/workflows/doctor.yml` running `fastapi_doctor . --ci --delta-only` on PRs

### 15.10 CLI Entry Point
- [ ] Implement `cli.main()` with all 8 flags: mode, only, format, no-fix-plan, no-extend, no-fail-on-critical, reset-baseline, ci, delta-only, output
- [ ] Add Rich `Console` terminal output with progress spinner during scan
- [ ] Implement `_print_summary_table()` using Rich `Table` with color-coded severity rows
- [ ] Handle `--reset-baseline` as early-exit path before orchestrator instantiation
- [ ] Register `fastapi_doctor` CLI entry point in `pyproject.toml` `[project.scripts]`
- [ ] Propagate exit code 1 to shell when `--ci` flag set and new CRITICALs detected

### 15.11 Configuration Schema
- [ ] Define `.fastapi_doctor.yaml` schema with `disable`, `suppress_recommendations`, `max_workers`, `mode`, and `targeted_category` keys
- [ ] Document all config keys in `doctor/README.md` with default values and valid options for each key
- [ ] Validate config loading in `CheckerRegistry._load_config()` with graceful fallback to empty dict on missing file or invalid YAML
- [ ] Add example `.fastapi_doctor.yaml` to the generated project scaffold showing common customizations
- [ ] Implement `suppress_recommendations` list support in `RecommendationEngine.analyze()` to honor per-project false-positive overrides
- [ ] Support environment variable override `FASTAPI_DOCTOR_CONFIG` pointing to an alternate config file path
- [ ] Add `max_workers` config key read by `DoctorOrchestrator.__init__()` to override thread pool size

### 15.12 Tests
- [ ] Create `tests/test_doctor_orchestrator.py` with T-01..T-06
- [ ] Create `tests/test_doctor_severity.py` with T-07..T-12
- [ ] Create `tests/test_doctor_fix_plan.py` with T-13..T-18
- [ ] Create `tests/test_doctor_recommendations.py` with T-19..T-24
- [ ] Create `tests/test_doctor_edge_cases.py` with T-25..T-30
- [ ] Add fixture for synthetic large project (50k LOC equivalent) for performance tests
- [ ] Configure `pytest-benchmark` for T-26 (quick mode < 10s) and T-32 (full mode < 60s)

### 15.13 Documentation and Packaging
- [ ] Update `pyproject.toml` with `[tool.fastapi-doctor]` section and all runtime dependencies
- [ ] Add `weasyprint`, `jinja2`, `rich`, `pyyaml` to `[project.optional-dependencies]` under `[doctor]`
- [ ] Create `Makefile` targets: `make doctor`, `make doctor-ci`, `make doctor-reset`, `make doctor-pdf`
- [ ] Write `doctor/README.md` with quick-start, all flags, config reference, and CI integration guide
- [ ] Add example reports directory `doctor/examples/` with sample Markdown, HTML, and JSON outputs
- [ ] Tag first release as `fastapi-skill-doctor==0.1.0` in `pyproject.toml`

---

## 16. Documentation Output

```json
{
  "status": "complete",
  "files_created": [
    "doctor/__init__.py",
    "doctor/orchestrator.py",
    "doctor/checker_registry.py",
    "doctor/severity.py",
    "doctor/fix_plan.py",
    "doctor/recommendations.py",
    "doctor/baseline.py",
    "doctor/report.py",
    "doctor/templates/report_builder.py",
    "doctor/templates/report.html.j2",
    "doctor/templates/report.md.j2",
    "doctor/ci_gate.py",
    "doctor/cli.py",
    "tests/test_doctor_orchestrator.py",
    "tests/test_doctor_severity.py",
    "tests/test_doctor_fix_plan.py",
    "tests/test_doctor_recommendations.py",
    "tests/test_doctor_edge_cases.py",
    ".fastapi_doctor.yaml",
    "doctor/README.md",
    "doctor/examples/sample_report.md",
    "doctor/examples/sample_report.json"
  ],
  "files_modified": [
    "pyproject.toml",
    ".github/workflows/doctor.yml"
  ],
  "metrics": {
    "tool_category": "PROACTIVE",
    "verify_tools_orchestrated": 7,
    "extend_tools_recommended": 8,
    "severity_levels": 4,
    "report_formats": 4,
    "test_count": 30,
    "completeness_criteria": 34,
    "fix_plan_items_typical": "5-15",
    "full_scan_slo_seconds": 60,
    "quick_scan_slo_seconds": 10
  },
  "next_steps": [
    "Run `fastapi_doctor . --format markdown` on your project to generate the first baseline and identify all current issues",
    "Commit `.fastapi_doctor.baseline.json` to version control so CI has a reference point for delta-only comparisons",
    "Add `fastapi_doctor . --ci --delta-only` to your PR workflow in `.github/workflows/doctor.yml` to catch regressions before merge",
    "Review EXTEND recommendations and schedule the highest-priority tools (e.g., `add_rbac`, `add_mfa`, `add_observability`) into your next sprint",
    "Set up nightly full scans with `--format html` to track technical debt trend over time in a team dashboard",
    "Configure `.fastapi_doctor.yaml` to disable checks not relevant to your tech stack and suppress false-positive EXTEND recommendations",
    "Integrate the JSON output (`--format json`) with your existing observability platform to track finding counts as time-series metrics"
  ],
  "warnings": [
    "Quick mode caps output at 10 findings but always promotes all CRITICAL severity items — a project with 15 CRITICALs will return all 15 in quick mode, exceeding the nominal 10-item cap",
    "EXTEND recommendations use static analysis heuristics; a project that conditionally imports packages (e.g., via importlib at runtime) may generate false-positive recommendations — use `.fastapi_doctor.yaml` suppress_recommendations to silence known false positives",
    "PDF rendering requires WeasyPrint system dependencies (Cairo, Pango) which are not available in all CI environments; the HTML fallback is always available without system dependencies",
    "Baseline comparison uses a fingerprint of `severity::title::location`; refactoring a file path without changing logic will produce `new` and `resolved` deltas even though no actual risk changed — regenerate baseline after large refactors"
  ],
  "notes": [
    "The fix plan example below shows a realistic output for a project with auth but no MFA, 8 N+1 queries, and 2 vulnerable dependencies — demonstrating how the doctor connects diagnosis to prescriptive action with exact tool references",
    "Each fix plan item's `run_command` is copy-paste ready; executing items in `order` sequence always satisfies tool dependency constraints (e.g., add_auth before add_rbac)",
    "The doctor deliberately does NOT run EXTEND tools during the scan — it only recommends them; this preserves the read-only invariant and prevents unintended code generation during a diagnostic run",
    "Baseline JSON uses sorted fingerprint lists to ensure deterministic git diffs when the baseline is updated; reviewers can easily see which issues were acknowledged in a given commit",
    "The crown jewel design principle: every user who runs `fastapi_doctor .` should receive output equivalent to a Staff Engineer code review — not a list of linting errors, but a prioritized, actionable consulting report"
  ],
  "fix_plan_example": {
    "project": "example-api (auth present, no MFA, 2 vulnerable deps, 8 N+1 queries)",
    "scan_duration_s": 14.3,
    "summary": {
      "CRITICAL": 2,
      "HIGH": 9,
      "MEDIUM": 4,
      "LOW": 2,
      "total": 17
    },
    "fix_plan": [
      {
        "order": 1,
        "severity": "CRITICAL",
        "tool_ref": "TOOL-029",
        "tool_name": "dep_audit",
        "fixes_critical": 2,
        "fixes_high": 0,
        "total_fixes": 2,
        "run_command": "fastapi_skill dep_audit .",
        "findings": [
          "CVE-2024-3297 in sqlalchemy 2.0.1 (upgrade to 2.0.36)",
          "CVE-2025-1188 in cryptography 41.0.0 (upgrade to 42.0.8)"
        ]
      },
      {
        "order": 2,
        "severity": "HIGH",
        "tool_ref": "TOOL-030",
        "tool_name": "n_plus_one_detector",
        "fixes_critical": 0,
        "fixes_high": 8,
        "total_fixes": 8,
        "run_command": "fastapi_skill n_plus_one_detector .",
        "findings": [
          "N+1 in GET /users/{id}/orders (8 extra queries per request)",
          "N+1 in GET /products (selectinload missing on tags relationship)"
        ]
      },
      {
        "order": 3,
        "severity": "HIGH",
        "tool_ref": "TOOL-032",
        "tool_name": "test_coverage_gaps",
        "fixes_critical": 0,
        "fixes_high": 1,
        "total_fixes": 1,
        "run_command": "fastapi_skill test_coverage_gaps .",
        "findings": [
          "auth/router.py line 45-89 has 0% branch coverage"
        ]
      }
    ],
    "extend_recommendations": [
      {
        "tool": "add_mfa",
        "tool_ref": "TOOL-013",
        "reason": "auth detected; MFA/TOTP middleware absent",
        "run_command": "fastapi_skill add_mfa .",
        "priority": "HIGH"
      },
      {
        "tool": "add_rate_limiting",
        "tool_ref": "TOOL-014",
        "reason": "auth detected; no rate-limiting middleware found",
        "run_command": "fastapi_skill add_rate_limiting .",
        "priority": "HIGH"
      },
      {
        "tool": "add_observability",
        "tool_ref": "TOOL-020",
        "reason": "no OpenTelemetry or Prometheus instrumentation detected",
        "run_command": "fastapi_skill add_observability .",
        "priority": "MEDIUM"
      }
    ]
  }
}
```
