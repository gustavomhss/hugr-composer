"""META-003: fastapi_audit_tool — Pydantic contract specification v2 (SOTA).

This file IS the spec. Every field is a requirement. Every validator is
an invariant. If the contract validates, the tool is correct. If it
doesn't, the tool has a bug.

v2 fixes from self-audit:
- P14 now has concrete secret patterns (regex list)
- P09 now defines AST-based detection method
- P08 now requires project generation to verify fingerprint
- GeneratedCodeQuality now specifies fixture config (models, auth)
- TestCoverage now checks tests PASS (not just exist)
- WiringCheck now has model_validator that REJECTS unwired tools
- SpecCheck now REJECTS missing specs (not informative)
- Added QS checks: docstrings, logger, ConfigDict
- Added RunnerSpec defining execution order
- Added SecretPattern enum with concrete detection patterns

Usage::

    from meta.contracts.audit_tool_contract import AuditInput, run_audit

    output = run_audit(AuditInput(
        tool_path="adapt/extend/infrastructure/add_webhook_retry.py"
    ))
    # If this line executes, the tool passed ALL checks.
    # If it raises ValidationError, the tool has a specific bug.
    print(output.verdict)  # PASS
"""

from __future__ import annotations

import re
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Verdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class CheckStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"


# ---------------------------------------------------------------------------
# Secret detection patterns — concrete, not vague
# ---------------------------------------------------------------------------

SECRET_PATTERNS: list[re.Pattern] = [
    re.compile(r'password\s*=\s*["\'][^"\']{3,}["\']', re.IGNORECASE),
    re.compile(r'secret\s*=\s*["\'][^"\']{3,}["\']', re.IGNORECASE),
    re.compile(r'api_key\s*=\s*["\'][^"\']{3,}["\']', re.IGNORECASE),
    re.compile(r'token\s*=\s*["\'][^"\']{3,}["\']', re.IGNORECASE),
    re.compile(r'AKIA[0-9A-Z]{16}'),  # AWS access key
    re.compile(r'sk_live_[0-9a-zA-Z]{24,}'),  # Stripe live key
    re.compile(r'ghp_[0-9a-zA-Z]{36}'),  # GitHub PAT
]

# Allowlist: these are NOT secrets even though they match patterns
SECRET_ALLOWLIST: list[str] = [
    '"changethis"',
    '"bearer"',
    'os.getenv',
    'settings.',
    'getattr(settings',
    '= ""',
    "= ''",
    '= Field(',
    'default=',
    'PLACEHOLDER',
    'example',
    'canary',       # canary tokens use fake credentials deliberately
    'honeypot',
    'decoy',
    'dummy',
    'AKIA0000',     # clearly fake AWS key pattern
]


# ---------------------------------------------------------------------------
# Fixture configuration — deterministic project generation
# ---------------------------------------------------------------------------

class FixtureConfig(BaseModel):
    """Defines EXACTLY how the fixture project is generated for quality checks.

    Removing ambiguity: every audit uses the SAME fixture.
    """
    model_config = ConfigDict(frozen=True)

    name: str = Field(
        default="audit_fixture",
        description="Fixture project name"
    )
    models: dict[str, dict[str, str]] = Field(
        default={"Item": {"title": "str", "description": "str"}},
        description="Models to generate. Default: single Item model."
    )
    with_auth: bool = Field(
        default=True,
        description="Include auth stack (JWT, users, etc.)"
    )


# ---------------------------------------------------------------------------
# Input contract
# ---------------------------------------------------------------------------

class AuditInput(BaseModel):
    """What the audit tool receives."""
    model_config = ConfigDict(frozen=True)

    tool_path: str = Field(
        description="Relative path to the tool .py file from skill root."
    )
    skill_root: str = Field(
        default=".",
        description="Root directory of SKILL-001."
    )
    fixture: FixtureConfig = Field(
        default_factory=FixtureConfig,
        description="Fixture project configuration for quality checks."
    )
    sdk_names: list[str] = Field(
        default_factory=list,
        description="Optional SDK names that must be lazy-imported (e.g. ['boto3', 'stripe'])."
    )

    @field_validator("tool_path")
    @classmethod
    def must_be_add_file(cls, v: str) -> str:
        name = Path(v).name
        if not name.startswith("add_"):
            raise ValueError(f"Must start with 'add_', got: {name}")
        if name.startswith("test_"):
            raise ValueError(f"Must not be test file: {name}")
        if not name.endswith(".py"):
            raise ValueError(f"Must be .py: {name}")
        return v


# ---------------------------------------------------------------------------
# Pattern check — individual
# ---------------------------------------------------------------------------

class PatternCheck(BaseModel):
    """Result of a single pattern check."""
    model_config = ConfigDict(frozen=True)

    id: str = Field(description="Check ID, e.g. P01_IMPORT_AST")
    name: str = Field(description="Human-readable name")
    status: CheckStatus
    detail: str = Field(description="Evidence: what was found or what's missing")
    line: int = Field(default=0, description="Line number (0 if N/A)")
    detection_method: str = Field(
        description="HOW this check is performed (AST, regex, string match, etc.)"
    )


# ---------------------------------------------------------------------------
# The 20 mandatory checks — expanded from 15
# ---------------------------------------------------------------------------

REQUIRED_CHECKS: list[tuple[str, str, str]] = [
    # (id, name, detection_method)
    ("P01_IMPORT_AST",
     "import ast present",
     "String match: 'import ast' in source lines (not in template strings)"),
    ("P02_FUTURE_ANNOTATIONS",
     "from __future__ import annotations",
     "String match: exact line present before any other import"),
    ("P03_MCP_TOOL_DICT",
     "MCP_TOOL dict with 4 keys",
     "AST: find module-level Dict assignment named MCP_TOOL, verify keys name/description/tags/entry"),
    ("P04_MCP_ENTRY_MATCHES",
     "MCP_TOOL entry matches function name",
     "AST: compare MCP_TOOL['entry'] string value with def name of public function"),
    ("P05_ENSURE_PREREQUISITES",
     "ensure_prerequisites() called",
     "AST: find Call node with func name 'ensure_prerequisites' inside the entry function body"),
    ("P06_VALIDATE_PROJECT_DIR_WITH_TIMING",
     "validate_project_dir error return has _elapsed_ms",
     "AST: find the first return ToolResult after validate_project_dir call, verify _elapsed_ms keyword"),
    ("P07_IDEMPOTENCY_GUARD",
     "Idempotency guard returns no_op",
     "AST: find return ToolResult with status='no_op' keyword in entry function body"),
    ("P08_IDEMPOTENCY_FINGERPRINT_EXISTS",
     "Fingerprint string exists in generated code",
     "RUNTIME: generate fixture project, apply tool, read the fingerprint file, verify the "
     "exact string from the guard condition exists in the generated file content"),
    ("P09_DRY_RUN_BEFORE_WRITES",
     "dry_run returns before any write_text() call",
     "AST: find the line number of the dry_run return, find the line number of the first "
     "write_text() or write() call, verify dry_run_line < first_write_line"),
    ("P10_TEXTWRAP_DEDENT",
     "textwrap.dedent on all template strings",
     "String match: every def _write_* function body contains 'textwrap.dedent'"),
    ("P11_AST_PARSE_VALIDATION",
     "ast.parse validation loop before success return",
     "AST: find for-loop containing ast.parse() call, verify it appears before the final "
     "return ToolResult(status='success')"),
    ("P12_ELAPSED_MS_UTILITY",
     "_elapsed_ms function defined",
     "AST: find FunctionDef named '_elapsed_ms' at module level"),
    ("P13_ELAPSED_MS_ALL_RETURNS",
     "_elapsed_ms on every return ToolResult path",
     "AST: find ALL return statements returning ToolResult(...), for each verify that "
     "the keyword arguments contain 'execution_time_ms' with a call to '_elapsed_ms'"),
    ("P14_NO_HARDCODED_SECRETS",
     "No hardcoded secrets in templates",
     "Regex: scan all textwrap.dedent template strings against SECRET_PATTERNS, "
     "filter through SECRET_ALLOWLIST, fail if any unallowed match remains"),
    ("P15_TOOL_DOCSTRING",
     "Entry function has docstring",
     "AST: verify ast.get_docstring(entry_function_node) is not None and len > 20"),
    ("P16_GENERATED_DOCSTRINGS",
     "Public functions in generated code have docstrings",
     "RUNTIME: after applying tool, AST-walk generated app/ files, verify every "
     "public function (not starting with _) has ast.get_docstring != None"),
    ("P17_GENERATED_LOGGER",
     "Generated code uses logging.getLogger(__name__)",
     "RUNTIME: grep generated app/ files for 'getLogger(__name__)' or 'getLogger'"),
    ("P18_GENERATED_CONFIG_DICT",
     "ORM Pydantic models use ConfigDict(from_attributes=True)",
     "RUNTIME: AST-walk generated schemas, find classes with 'model_config', "
     "verify 'from_attributes' in the config assignment. SKIP if no ORM models."),
    ("P19_NO_PRINT_STATEMENTS",
     "Generated code uses logger, not print()",
     "RUNTIME: AST-walk generated app/ files, verify zero ast.Call nodes "
     "with func.id == 'print'"),
    ("P20_HTTP_ERROR_FORMAT",
     "Error responses use {'detail': ...} format",
     "RUNTIME: grep generated route files for HTTPException, verify all use "
     "detail= keyword (not custom body)"),
]


class PatternCheckResults(BaseModel):
    """All 20 pattern checks."""
    model_config = ConfigDict(frozen=True)

    checks: list[PatternCheck] = Field(min_length=20, max_length=25)

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

    @model_validator(mode="after")
    def all_required_present(self) -> "PatternCheckResults":
        """Every required check ID must be present."""
        present_ids = {c.id for c in self.checks}
        required_ids = {r[0] for r in REQUIRED_CHECKS}
        missing = required_ids - present_ids
        if missing:
            raise ValueError(f"Missing required checks: {sorted(missing)}")
        return self


# ---------------------------------------------------------------------------
# Return path analysis
# ---------------------------------------------------------------------------

class ReturnPath(BaseModel):
    """A single `return ToolResult(...)` occurrence."""
    model_config = ConfigDict(frozen=True)

    line: int = Field(description="Line number")
    status: str = Field(description="Status value in the ToolResult")
    has_elapsed_ms: bool = Field(description="Has execution_time_ms=_elapsed_ms(...)")
    context: str = Field(
        default="",
        description="Surrounding code context (3 lines before/after) for debugging"
    )


class ReturnPathAnalysis(BaseModel):
    """ALL return paths. Every one MUST have _elapsed_ms."""
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
            details = [f"L{p.line} ({p.status})" for p in missing]
            raise ValueError(
                f"{len(missing)} return(s) missing _elapsed_ms: {details}"
            )
        return self

    @model_validator(mode="after")
    def minimum_paths(self) -> "ReturnPathAnalysis":
        """Every tool should have at least 4 return paths:
        error, prereq_error/no_op, dry_run, success."""
        if len(self.paths) < 4:
            raise ValueError(
                f"Only {len(self.paths)} return paths — minimum 4 "
                "(error, prereq/no_op, dry_run, success)"
            )
        return self


# ---------------------------------------------------------------------------
# Generated code quality
# ---------------------------------------------------------------------------

class LazyImportViolation(BaseModel):
    model_config = ConfigDict(frozen=True)
    file: str
    sdk: str
    line: int
    import_statement: str = Field(description="The actual import line for debugging")


class FunctionLOC(BaseModel):
    model_config = ConfigDict(frozen=True)
    file: str
    function: str
    loc: int

    @field_validator("loc")
    @classmethod
    def max_50(cls, v: int) -> int:
        if v > 50:
            raise ValueError(f"Function {v} LOC exceeds 50")
        return v


class MissingDocstring(BaseModel):
    """A public function missing a docstring in generated code."""
    model_config = ConfigDict(frozen=True)
    file: str
    function: str
    line: int


class GeneratedCodeQuality(BaseModel):
    """Quality of the GENERATED code (not the tool itself).

    Requires generating a fixture project with FixtureConfig and applying
    the tool to it.
    """
    model_config = ConfigDict(frozen=True)

    # Generation
    project_generated: bool
    tool_status: str = Field(description="ToolResult.status from applying the tool")
    files_created: list[str]
    files_modified: list[str]

    # Parse
    all_py_parse: bool
    parse_errors: list[str] = Field(default_factory=list)

    # LOC
    max_function: FunctionLOC | None = None
    all_functions: list[FunctionLOC] = Field(
        default_factory=list,
        description="ALL functions in generated app/ with their LOC"
    )

    # Lazy imports
    lazy_import_violations: list[LazyImportViolation] = Field(default_factory=list)

    # Ruff
    ruff_f401_clean: bool
    ruff_violations: list[str] = Field(default_factory=list)

    # Config
    config_fields_inside_class: bool
    config_fields_checked: list[str] = Field(
        default_factory=list,
        description="Which config fields were verified for 4-space indent"
    )

    # Docstrings
    missing_docstrings: list[MissingDocstring] = Field(default_factory=list)

    # Logger
    uses_logger_not_print: bool = Field(
        description="Generated code uses logging.getLogger, not print()"
    )

    # Validators — each enforces an invariant
    @model_validator(mode="after")
    def must_generate(self) -> "GeneratedCodeQuality":
        if not self.project_generated:
            raise ValueError("Fixture project generation FAILED")
        return self

    @model_validator(mode="after")
    def must_apply(self) -> "GeneratedCodeQuality":
        if self.tool_status != "success":
            raise ValueError(f"Tool returned '{self.tool_status}', expected 'success'")
        return self

    @model_validator(mode="after")
    def must_parse(self) -> "GeneratedCodeQuality":
        if not self.all_py_parse:
            raise ValueError(f"Parse errors: {self.parse_errors}")
        return self

    @model_validator(mode="after")
    def must_ruff_clean(self) -> "GeneratedCodeQuality":
        if not self.ruff_f401_clean:
            raise ValueError(f"Ruff F401: {self.ruff_violations}")
        return self

    @model_validator(mode="after")
    def no_lazy_violations(self) -> "GeneratedCodeQuality":
        if self.lazy_import_violations:
            details = [f"{v.file}:{v.line} {v.import_statement}" for v in self.lazy_import_violations]
            raise ValueError(f"Top-level SDK imports: {details}")
        return self

    @model_validator(mode="after")
    def must_use_logger(self) -> "GeneratedCodeQuality":
        if not self.uses_logger_not_print:
            raise ValueError("Generated code uses print() instead of logger")
        return self


# ---------------------------------------------------------------------------
# Test coverage — must exist AND pass
# ---------------------------------------------------------------------------

class TestCoverage(BaseModel):
    """Tests must exist, have minimum count, AND pass."""
    model_config = ConfigDict(frozen=True)

    structural_file: str
    structural_exists: bool
    structural_test_count: int = Field(ge=0)
    structural_passed: int = Field(ge=0)
    structural_failed: int = Field(ge=0)

    behavior_file: str
    behavior_exists: bool
    behavior_test_count: int = Field(ge=0)
    behavior_passed: int = Field(ge=0)
    behavior_failed: int = Field(ge=0)

    @model_validator(mode="after")
    def structural_must_exist(self) -> "TestCoverage":
        if not self.structural_exists:
            raise ValueError(f"Structural test file missing: {self.structural_file}")
        return self

    @model_validator(mode="after")
    def structural_minimum(self) -> "TestCoverage":
        if self.structural_exists and self.structural_test_count < 20:
            raise ValueError(f"{self.structural_test_count} structural tests — minimum 20")
        return self

    @model_validator(mode="after")
    def structural_must_pass(self) -> "TestCoverage":
        if self.structural_exists and self.structural_failed > 0:
            raise ValueError(f"{self.structural_failed} structural test(s) FAILED")
        return self

    @model_validator(mode="after")
    def behavior_must_pass_if_exists(self) -> "TestCoverage":
        if self.behavior_exists and self.behavior_failed > 0:
            raise ValueError(f"{self.behavior_failed} behavior test(s) FAILED")
        return self


# ---------------------------------------------------------------------------
# Wiring — MUST be wired, not optional
# ---------------------------------------------------------------------------

class WiringCheck(BaseModel):
    """Tool MUST be wired into all 5 test infrastructure files."""
    model_config = ConfigDict(frozen=True)

    in_boot: bool
    in_stress: bool
    in_property: bool
    in_chains: bool
    in_crosscomp: bool

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

    @model_validator(mode="after")
    def must_be_fully_wired(self) -> "WiringCheck":
        if not self.fully_wired:
            raise ValueError(f"Not wired in: {self.missing}")
        return self


# ---------------------------------------------------------------------------
# Spec — MUST exist, not optional
# ---------------------------------------------------------------------------

class SpecCheck(BaseModel):
    """Formal spec MUST exist."""
    model_config = ConfigDict(frozen=True)

    spec_exists: bool
    spec_path: str | None = None
    spec_lines: int = 0
    spec_sections: int = 0

    @model_validator(mode="after")
    def must_have_spec(self) -> "SpecCheck":
        if not self.spec_exists:
            raise ValueError("Formal spec file MISSING")
        return self

    @model_validator(mode="after")
    def spec_minimum_quality(self) -> "SpecCheck":
        if self.spec_exists:
            if self.spec_sections < 10:
                raise ValueError(f"Spec has {self.spec_sections} sections — minimum 10")
            if self.spec_lines < 300:
                raise ValueError(f"Spec has {self.spec_lines} lines — minimum 300")
        return self


# ---------------------------------------------------------------------------
# Runner spec — defines execution order
# ---------------------------------------------------------------------------

class RunnerStep(BaseModel):
    """A single step in the audit runner."""
    model_config = ConfigDict(frozen=True)

    order: int = Field(description="Execution order (1-based)")
    name: str = Field(description="Step name")
    requires_project: bool = Field(
        description="Does this step need a generated fixture project?"
    )
    description: str


RUNNER_STEPS: list[RunnerStep] = [
    RunnerStep(order=1, name="parse_tool_source",
               requires_project=False,
               description="Read and AST-parse the tool file. Extract MCP_TOOL, "
                          "entry function, return paths, template strings."),
    RunnerStep(order=2, name="static_pattern_checks",
               requires_project=False,
               description="Run P01-P15 checks on the parsed AST. These only "
                          "need the tool source, not a generated project."),
    RunnerStep(order=3, name="return_path_analysis",
               requires_project=False,
               description="Find ALL return ToolResult(...) nodes via AST. "
                          "For each, verify _elapsed_ms keyword is present."),
    RunnerStep(order=4, name="generate_fixture_project",
               requires_project=True,
               description="Generate a fixture project using FixtureConfig. "
                          "Apply the tool. Record ToolResult."),
    RunnerStep(order=5, name="runtime_quality_checks",
               requires_project=True,
               description="Run P16-P20 checks on the GENERATED code. "
                          "AST-walk app/ for docstrings, logger, ConfigDict, "
                          "print(), HTTPException format."),
    RunnerStep(order=6, name="generated_code_quality",
               requires_project=True,
               description="Check: all .py parse, max function LOC ≤50, "
                          "ruff F401 clean, lazy imports, config indent."),
    RunnerStep(order=7, name="check_test_coverage",
               requires_project=False,
               description="Verify structural + behavior test files exist, "
                          "count tests, run pytest, record pass/fail."),
    RunnerStep(order=8, name="check_wiring",
               requires_project=False,
               description="Grep for tool name in all 5 test infrastructure files."),
    RunnerStep(order=9, name="check_spec",
               requires_project=False,
               description="Find specs/*{tool_name}*.md, count lines + sections."),
    RunnerStep(order=10, name="compute_verdict",
                requires_project=False,
                description="Aggregate all results. PASS only if ALL components pass. "
                           "FAIL with specific reasons otherwise."),
]


# ---------------------------------------------------------------------------
# Output contract
# ---------------------------------------------------------------------------

class AuditOutput(BaseModel):
    """Complete audit output. The contract IS the spec.

    If this model validates, the tool is correct.
    If it raises ValidationError, the tool has a specific bug.
    """
    model_config = ConfigDict(frozen=True)

    tool_name: str
    tool_path: str
    tool_loc: int
    mcp_tool_name: str

    patterns: PatternCheckResults
    return_paths: ReturnPathAnalysis
    quality: GeneratedCodeQuality
    tests: TestCoverage
    wiring: WiringCheck
    spec: SpecCheck

    verdict: Verdict

    # Execution metadata
    runner_steps_executed: int = Field(ge=10, le=10,
        description="Must execute exactly 10 steps")
    audit_duration_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def verdict_reflects_reality(self) -> "AuditOutput":
        issues = []
        if not self.patterns.all_pass:
            issues.append(f"patterns: {self.patterns.failed} failed")
        if not self.tests.structural_exists:
            issues.append("tests: structural missing")
        if self.tests.structural_failed > 0:
            issues.append(f"tests: {self.tests.structural_failed} structural failed")
        if self.tests.behavior_exists and self.tests.behavior_failed > 0:
            issues.append(f"tests: {self.tests.behavior_failed} behavior failed")

        if issues and self.verdict == Verdict.PASS:
            raise ValueError(f"PASS but {len(issues)} issues: {issues}")
        if not issues and self.verdict == Verdict.FAIL:
            raise ValueError("FAIL but no issues — should be PASS")
        return self


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def expected_paths(tool_path: str) -> dict[str, str]:
    """Given a tool path, return expected test + behavior + spec paths."""
    p = Path(tool_path)
    name = p.stem
    parent = p.parent
    return {
        "test": str(parent / f"test_{name}.py"),
        "behavior": str(parent / f"test_{name}_behavior.py"),
        "spec_pattern": f"specs/TOOL-*-{name}.md",
    }


def detect_sdk_names(tool_source: str) -> list[str]:
    """Auto-detect which SDKs should be lazy-imported by scanning templates.

    Looks for known SDK names inside textwrap.dedent blocks.
    """
    known_sdks = {
        "stripe", "boto3", "resend", "postmarker", "sendgrid",
        "celery", "arq", "apscheduler", "temporalio",
        "torch", "sklearn", "onnxruntime", "tensorflow",
        "firebase_admin", "apns2", "twilio",
        "sqladmin", "bleach", "weasyprint", "openpyxl",
        "sentry_sdk", "opentelemetry", "prometheus_client",
        "redis", "httpx", "py_webauthn", "cedarpy",
        "hvac",  # HashiCorp Vault
    }
    found = set()
    for sdk in known_sdks:
        if sdk in tool_source:
            found.add(sdk)
    return sorted(found)
