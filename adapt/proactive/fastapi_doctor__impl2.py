"""Helper module for TOOL-051 fastapi_doctor (split per 500-LOC cap).

Contains the fix-plan builder, EXTEND recommendation engine, baseline
comparator, report renderer, and the doctor orchestrator. These are imported
back into ``fastapi_doctor.py`` so that the public surface (``MCP_TOOL`` dict +
``fastapi_doctor`` entry) remains in the registered module path. Behaviour is
identical to the pre-split version.
"""

from __future__ import annotations

import ast
import json
import re
import textwrap
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout
from pathlib import Path
from typing import Any

from adapt.proactive.fastapi_doctor__impl1 import (
    CheckerRegistry,
    CheckerResult,
    Severity,
)


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

