"""META-003: fastapi_audit_tool — Pydantic contract specification.

This file IS the spec. Every field is a requirement. Every validator is
an invariant. If the contract validates, the tool is correct. If it
doesn't, the tool has a bug.

Usage:

    from meta.contracts.audit_tool_contract import (
        AuditInput,
        AuditOutput,
        PatternCheck,
        ReturnPathAnalysis,
        GeneratedCodeQuality,
        AuditVerdict,
    )

    # Define input
    inp = AuditInput(tool_path="adapt/extend/infrastructure/add_webhook_retry.py")

    # Run audit (the actual implementation)
    output = run_audit(inp)

    # Output validates or raises — no ambiguity
    print(output.verdict)  # PASS or FAIL
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Verdict(str, Enum):
    """Final audit verdict."""
    PASS = "PASS"
    FAIL = "FAIL"


class CheckStatus(str, Enum):
    """Individual check result."""
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"  # check not applicable (e.g., no SDK deps)


# ---------------------------------------------------------------------------
# Input contract
# ---------------------------------------------------------------------------

class AuditInput(BaseModel):
    """What the audit tool receives.

    Only ONE required field: the path to the tool file. Everything else
    is discovered by reading the file.
    """
    model_config = ConfigDict(frozen=True)

    tool_path: str = Field(
        description="Relative path to the tool .py file from skill root. "
                    "Example: 'adapt/extend/infrastructure/add_webhook_retry.py'"
    )
    skill_root: str = Field(
        default=".",
        description="Root directory of SKILL-001. Defaults to cwd."
    )

    @field_validator("tool_path")
    @classmethod
    def must_be_add_file(cls, v: str) -> str:
        """Tool path must be an add_*.py file, not a test."""
        name = Path(v).name
        if not name.startswith("add_"):
            raise ValueError(f"Tool file must start with 'add_', got: {name}")
        if name.startswith("test_"):
            raise ValueError(f"Tool file must not be a test file: {name}")
        if not name.endswith(".py"):
            raise ValueError(f"Tool file must be .py: {name}")
        return v


# ---------------------------------------------------------------------------
# Pattern checks (the 15 mandatory checks)
# ---------------------------------------------------------------------------

class PatternCheck(BaseModel):
    """Result of a single pattern check.

    Each check has:
    - id: unique identifier (e.g., "P01_IMPORT_AST")
    - name: human-readable name
    - status: PASS / FAIL / SKIP
    - detail: what was found or what's wrong
    - line: line number where the issue is (0 if N/A)
    """
    model_config = ConfigDict(frozen=True)

    id: str = Field(description="Check ID, e.g. P01_IMPORT_AST")
    name: str = Field(description="Human-readable check name")
    status: CheckStatus
    detail: str = Field(description="What was found or what's wrong")
    line: int = Field(default=0, description="Line number (0 if N/A)")


class PatternCheckResults(BaseModel):
    """All 15 pattern checks grouped.

    Invariant: all 15 must be present. None can be skipped without reason.
    """
    model_config = ConfigDict(frozen=True)

    checks: list[PatternCheck] = Field(min_length=15, max_length=20)

    # Convenience properties
    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c.status == CheckStatus.PASS)

    @property
    def failed(self) -> int:
        return sum(1 for c in self.checks if c.status == CheckStatus.FAIL)

    @property
    def all_pass(self) -> bool:
        return self.failed == 0

    @property
    def failures(self) -> list[PatternCheck]:
        return [c for c in self.checks if c.status == CheckStatus.FAIL]


# The 15 check IDs — these are INVIOLABLE. Every audit must run all 15.
REQUIRED_CHECKS: list[str] = [
    "P01_IMPORT_AST",
    "P02_FUTURE_ANNOTATIONS",
    "P03_MCP_TOOL_DICT",
    "P04_MCP_ENTRY_MATCHES",
    "P05_ENSURE_PREREQUISITES",
    "P06_VALIDATE_PROJECT_DIR",
    "P07_IDEMPOTENCY_GUARD",
    "P08_IDEMPOTENCY_FINGERPRINT_EXISTS",
    "P09_DRY_RUN_BEFORE_WRITES",
    "P10_TEXTWRAP_DEDENT",
    "P11_AST_PARSE_VALIDATION",
    "P12_ELAPSED_MS_UTILITY",
    "P13_ELAPSED_MS_ALL_RETURNS",
    "P14_NO_HARDCODED_SECRETS",
    "P15_TOOL_DOCSTRING",
]


# ---------------------------------------------------------------------------
# Return path analysis
# ---------------------------------------------------------------------------

class ReturnPath(BaseModel):
    """A single `return ToolResult(...)` occurrence."""
    model_config = ConfigDict(frozen=True)

    line: int = Field(description="Line number of the return statement")
    status: str = Field(description="The status value: success/no_op/error/dry_run")
    has_elapsed_ms: bool = Field(description="Whether _elapsed_ms is in this return block")


class ReturnPathAnalysis(BaseModel):
    """Analysis of ALL return paths in the tool.

    Invariant: every return MUST have _elapsed_ms.
    """
    model_config = ConfigDict(frozen=True)

    paths: list[ReturnPath] = Field(min_length=1)

    @property
    def total(self) -> int:
        return len(self.paths)

    @property
    def with_elapsed(self) -> int:
        return sum(1 for p in self.paths if p.has_elapsed_ms)

    @property
    def missing_elapsed(self) -> list[ReturnPath]:
        return [p for p in self.paths if not p.has_elapsed_ms]

    @model_validator(mode="after")
    def all_have_elapsed(self) -> "ReturnPathAnalysis":
        missing = self.missing_elapsed
        if missing:
            lines = [str(p.line) for p in missing]
            raise ValueError(
                f"{len(missing)} return path(s) missing _elapsed_ms at lines: {', '.join(lines)}"
            )
        return self


# ---------------------------------------------------------------------------
# Generated code quality (requires generating a project + applying the tool)
# ---------------------------------------------------------------------------

class LazyImportViolation(BaseModel):
    """A top-level SDK import in generated code."""
    model_config = ConfigDict(frozen=True)

    file: str = Field(description="Relative path of the file")
    sdk: str = Field(description="SDK name found at top level")
    line: int = Field(description="Line number")


class FunctionLOC(BaseModel):
    """A function's line count in generated code."""
    model_config = ConfigDict(frozen=True)

    file: str
    function: str
    loc: int

    @field_validator("loc")
    @classmethod
    def max_50(cls, v: int) -> int:
        if v > 50:
            raise ValueError(f"Function exceeds 50 LOC: {v}")
        return v


class GeneratedCodeQuality(BaseModel):
    """Quality analysis of the code the tool GENERATES (not the tool itself).

    This requires actually running the tool on a fixture project and
    inspecting the output.
    """
    model_config = ConfigDict(frozen=True)

    project_generated: bool = Field(description="Was a fixture project successfully generated?")
    tool_applied: bool = Field(description="Did the tool return status='success'?")
    files_created: list[str] = Field(description="Absolute paths of created files")
    files_modified: list[str] = Field(description="Absolute paths of modified files")

    # Parse correctness
    all_py_parse: bool = Field(description="Do ALL generated .py files pass ast.parse?")
    parse_errors: list[str] = Field(default_factory=list)

    # Function LOC
    max_function: FunctionLOC | None = Field(
        default=None,
        description="The longest function in generated app/ code"
    )

    # Lazy imports
    lazy_import_violations: list[LazyImportViolation] = Field(default_factory=list)

    # Ruff
    ruff_f401_clean: bool = Field(description="Does generated app/ pass ruff --select F401?")
    ruff_violations: list[str] = Field(default_factory=list)

    # Config
    config_fields_inside_class: bool = Field(
        description="Are injected config fields inside the Settings class body (4-space indent)?"
    )

    @model_validator(mode="after")
    def must_generate_and_apply(self) -> "GeneratedCodeQuality":
        if not self.project_generated:
            raise ValueError("Fixture project generation FAILED")
        if not self.tool_applied:
            raise ValueError("Tool application FAILED (status != success)")
        return self

    @model_validator(mode="after")
    def must_parse_clean(self) -> "GeneratedCodeQuality":
        if not self.all_py_parse:
            raise ValueError(f"Parse errors: {self.parse_errors}")
        return self

    @model_validator(mode="after")
    def must_be_ruff_clean(self) -> "GeneratedCodeQuality":
        if not self.ruff_f401_clean:
            raise ValueError(f"Ruff F401 violations: {self.ruff_violations}")
        return self

    @model_validator(mode="after")
    def no_lazy_violations(self) -> "GeneratedCodeQuality":
        if self.lazy_import_violations:
            details = [f"{v.file}:{v.line} {v.sdk}" for v in self.lazy_import_violations]
            raise ValueError(f"Top-level SDK imports: {details}")
        return self


# ---------------------------------------------------------------------------
# Test coverage check
# ---------------------------------------------------------------------------

class TestCoverage(BaseModel):
    """Verification that tests exist and have minimum counts."""
    model_config = ConfigDict(frozen=True)

    structural_file: str = Field(description="Path to structural test file")
    structural_exists: bool
    structural_test_count: int = Field(ge=0)

    behavior_file: str = Field(description="Path to behavior test file")
    behavior_exists: bool
    behavior_test_count: int = Field(ge=0)

    @model_validator(mode="after")
    def structural_minimum(self) -> "TestCoverage":
        if self.structural_exists and self.structural_test_count < 20:
            raise ValueError(
                f"Only {self.structural_test_count} structural tests — minimum 20"
            )
        return self


# ---------------------------------------------------------------------------
# Wiring check
# ---------------------------------------------------------------------------

class WiringCheck(BaseModel):
    """Is the tool wired into all test infrastructure?"""
    model_config = ConfigDict(frozen=True)

    in_boot: bool = Field(description="Present in test_boot.py EXTEND_TOOLS")
    in_stress: bool = Field(description="Present in test_stress.py _ALL_TOOLS")
    in_property: bool = Field(description="Present in property_tests.py _TOOL_REGISTRY")
    in_chains: bool = Field(description="Present in test_boot_chains.py ALL_TOOLS_FORWARD")
    in_crosscomp: bool = Field(description="Present in test_cross_composition.py ALL_EXTEND")

    @property
    def fully_wired(self) -> bool:
        return all([self.in_boot, self.in_stress, self.in_property,
                    self.in_chains, self.in_crosscomp])

    @property
    def missing(self) -> list[str]:
        result = []
        if not self.in_boot: result.append("test_boot.py")
        if not self.in_stress: result.append("test_stress.py")
        if not self.in_property: result.append("property_tests.py")
        if not self.in_chains: result.append("test_boot_chains.py")
        if not self.in_crosscomp: result.append("test_cross_composition.py")
        return result


# ---------------------------------------------------------------------------
# Spec check
# ---------------------------------------------------------------------------

class SpecCheck(BaseModel):
    """Does a formal spec exist for this tool?"""
    model_config = ConfigDict(frozen=True)

    spec_exists: bool
    spec_path: str | None = None
    spec_lines: int = 0
    spec_sections: int = 0


# ---------------------------------------------------------------------------
# Output contract (the full audit result)
# ---------------------------------------------------------------------------

class AuditOutput(BaseModel):
    """Complete audit output. This IS the spec — if it validates, the tool is correct.

    Invariants enforced by validators:
    - All 15 pattern checks must pass
    - All return paths must have _elapsed_ms
    - Generated code must parse, be ruff-clean, have no lazy violations
    - Structural test file must exist with ≥20 tests
    """
    model_config = ConfigDict(frozen=True)

    # Metadata
    tool_name: str = Field(description="Tool function name, e.g. 'add_webhook_retry'")
    tool_path: str = Field(description="Relative path to tool file")
    tool_loc: int = Field(description="Lines of code in tool file")
    mcp_tool_name: str = Field(description="MCP tool name from MCP_TOOL dict")

    # Pattern checks
    patterns: PatternCheckResults

    # Return path analysis
    return_paths: ReturnPathAnalysis

    # Generated code quality
    quality: GeneratedCodeQuality

    # Test coverage
    tests: TestCoverage

    # Wiring
    wiring: WiringCheck

    # Spec
    spec: SpecCheck

    # Verdict
    verdict: Verdict

    @model_validator(mode="after")
    def verdict_must_reflect_reality(self) -> "AuditOutput":
        """Verdict MUST be FAIL if any component has issues."""
        issues = []
        if not self.patterns.all_pass:
            issues.append(f"patterns: {self.patterns.failed} failed")
        if self.return_paths.missing_elapsed:
            issues.append(f"return_paths: {len(self.return_paths.missing_elapsed)} missing")
        if not self.quality.all_py_parse:
            issues.append("quality: parse errors")
        if not self.quality.ruff_f401_clean:
            issues.append("quality: ruff violations")
        if self.quality.lazy_import_violations:
            issues.append("quality: lazy import violations")
        if not self.tests.structural_exists:
            issues.append("tests: structural file missing")

        if issues and self.verdict == Verdict.PASS:
            raise ValueError(
                f"Verdict is PASS but {len(issues)} issues found: {issues}"
            )
        if not issues and self.verdict == Verdict.FAIL:
            raise ValueError(
                "Verdict is FAIL but no issues found — should be PASS"
            )
        return self


# ---------------------------------------------------------------------------
# Helper: determine expected test/behavior/spec paths from tool path
# ---------------------------------------------------------------------------

def expected_paths(tool_path: str) -> dict[str, str]:
    """Given a tool path, return expected test + behavior + spec paths.

    Args:
        tool_path: e.g. 'adapt/extend/infrastructure/add_webhook_retry.py'

    Returns:
        Dict with keys: test, behavior, spec
    """
    p = Path(tool_path)
    name = p.stem  # add_webhook_retry
    parent = p.parent  # adapt/extend/infrastructure

    return {
        "test": str(parent / f"test_{name}.py"),
        "behavior": str(parent / f"test_{name}_behavior.py"),
        "spec": f"specs/TOOL-XXX-{name}.md",  # XXX = needs lookup
    }
