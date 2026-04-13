"""
SKILL-001 Core Models — Shared Pydantic contracts.

These models are used by core tools and can be extended by modules.
Modules import from here; they don't redefine these types.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════

class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class HealthLevel(str, Enum):
    LIVENESS = "liveness"
    READINESS = "readiness"
    STARTUP = "startup"


# ═══════════════════════════════════════════════════════════
# FINDINGS
# ═══════════════════════════════════════════════════════════

class Finding(BaseModel):
    """A single finding from analysis."""
    rule_id: str = Field(description="e.g., 'CORE-01' or 'AUTH-03'")
    severity: Severity
    title: str
    description: str
    file_path: str | None = None
    line_number: int | None = None
    fix_suggestion: str | None = None


# ═══════════════════════════════════════════════════════════
# STATIC ANALYSIS
# ═══════════════════════════════════════════════════════════

class SyncInAsyncViolation(BaseModel):
    """Sync blocking call inside async function."""
    file_path: str
    line_number: int
    function_name: str
    blocking_call: str


class DeprecatedPattern(BaseModel):
    """Usage of deprecated FastAPI pattern."""
    file_path: str
    line_number: int
    pattern: str
    replacement: str


class PoolAnalysis(BaseModel):
    """Connection pool configuration."""
    pool_size: int | None = None
    max_overflow: int | None = None
    pool_recycle: int | None = None
    pool_pre_ping: bool | None = None
    estimated_max_connections: int | None = None
    exceeds_pg_max: bool | None = None


class CoreAnalysisResult(BaseModel):
    """Result from core static analysis."""
    # Boolean flags — 8 core checks
    has_lifespan: bool
    has_structured_logging: bool
    has_correlation_id: bool
    has_health_checks: list[HealthLevel] = Field(default_factory=list)
    has_security_headers: bool
    has_cors: bool
    cors_wildcard: bool = False
    has_graceful_shutdown: bool

    # Violations
    sync_in_async: list[SyncInAsyncViolation] = Field(default_factory=list)
    deprecated_patterns: list[DeprecatedPattern] = Field(default_factory=list)

    # Config analysis
    pool_config: PoolAnalysis | None = None
    middleware_order: list[str] = Field(default_factory=list)
    pydantic_strict_inputs: bool | None = None

    # Overall
    score: float = Field(ge=0.0, le=1.0)
    findings: list[Finding] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════
# RUNTIME CHECKS
# ═══════════════════════════════════════════════════════════

class HealthCheckResult(BaseModel):
    """Result from checking a health endpoint."""
    level: HealthLevel
    endpoint: str
    status_code: int
    response_time_ms: float
    body: dict[str, Any] | None = None
    passed: bool


class SecurityHeadersResult(BaseModel):
    """Result from checking security headers."""
    url: str
    headers_present: dict[str, str] = Field(default_factory=dict)
    headers_missing: list[str] = Field(default_factory=list)
    score: float = Field(ge=0.0, le=1.0)
    findings: list[Finding] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════
# SCAFFOLD
# ═══════════════════════════════════════════════════════════

class ScaffoldInput(BaseModel):
    """Input for project scaffolding."""
    project_name: str = Field(description="Project name (snake_case)")
    output_dir: str = Field(description="Directory to create project in")
    with_db: bool = Field(default=True)
    with_redis: bool = Field(default=False)
    cors_origins: list[str] = Field(default_factory=lambda: ["https://localhost:3000"])
    worker_count: int = Field(default=4, ge=1, le=32)


class ScaffoldResult(BaseModel):
    """Output from project scaffolding."""
    created_files: list[str]
    project_path: str
    run_command: str
