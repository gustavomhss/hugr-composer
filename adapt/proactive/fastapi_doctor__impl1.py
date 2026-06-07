"""Helper module for TOOL-051 fastapi_doctor (split per 500-LOC cap).

Contains the severity taxonomy, checker registry, and individual VERIFY-tool
checker wrappers. These are imported back into ``fastapi_doctor.py`` so that
the public surface (``MCP_TOOL`` dict + ``fastapi_doctor`` entry) remains in the
registered module path. Behaviour is identical to the pre-split version.
"""

from __future__ import annotations

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
