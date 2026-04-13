<!--
{
  "tool_num": "029",
  "tool_name": "security_scan",
  "model": "deepseek/deepseek-chat",
  "elapsed_seconds": 507.2072455720627,
  "prompt_tokens": 47066,
  "completion_tokens": 11306,
  "cost_usd": 0.06528159,
  "calls": 6
}
-->

# TOOL-029: security_scan

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-08

---

## 1. Overview

| Parameter       | Value                                                                 |
|-----------------|-----------------------------------------------------------------------|
| Tool name       | `fastapi_security_scan`                                              |
| Category        | VERIFY                                                               |
| Complexity      | High                                                                 |
| Dependencies    | existing FastAPI project, bandit, semgrep, pip-audit                |
| Signature       | `security_scan(project_dir: str, fail_on: Literal["high", "medium", "low"] = "high", checks: list[str] | None = None, exclude_paths: list[str] | None = None) -> dict` |
| Parameters      | `project_dir`: project root path<br>`fail_on`: minimum severity that fails the build<br>`checks`: specific check families to run (None = all)<br>`exclude_paths`: paths to skip |

## 2. Purpose

The `fastapi_security_scan` tool performs static security analysis on FastAPI codebases to identify and mitigate common vulnerabilities. It integrates **bandit** for Python security linting, **semgrep** for pattern-based checks with FastAPI-specific rules, and **pip-audit** for detecting known CVEs in dependencies. The tool generates a SARIF report compatible with GitHub's Security tab and fails the build if any finding exceeds the specified severity threshold (`fail_on`). It creates config files for each scanner, a unified runner script, CI integration, and exclusion rules for false positives. Key design decisions include using SARIF as the output format, implementing FastAPI-specific semgrep rules, and ensuring that scans never modify source code while persisting all findings regardless of the fail threshold.

## 3. Performance SLOs

| Metric                  | Target                          | Why                                                                 |
|------------------------|---------------------------------|---------------------------------------------------------------------|
| Tool execution time     | < 4s                           | Install config quickly without delaying the actual scan            |
| Files modified          | ≤ 2                            | Minimize changes to existing project files                         |
| Files created           | ≥ 8                            | Generate necessary configs, rules, and reports                     |
| Full scan runtime       | < 60s for 50K LOC codebase      | Ensure scans complete quickly even for large projects              |
| Report generation       | < 500 ms                       | Generate reports swiftly for immediate feedback                   |
| Latency overhead        | 0 ms                           | No runtime production overhead (scan-time only)                   |
| Memory overhead         | < 50 MB                        | Keep memory usage low during scans                                 |
| Migration runtime       | 0s — no DB changes             | No database modifications required for scans                       |

---

## 4. Code Examples (Before / After)

### 4.1 Settings module: BEFORE
```python
# app/core/config.py
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    PROJECT_NAME: str = "My FastAPI App"
    VERSION: str = "1.0.0"
    
    # Security settings
    SECRET_KEY: str = "my-super-secret-key-12345"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # Database
    DATABASE_URL: str = "postgresql://user:pass@localhost/db"
    
    # API
    API_V1_STR: str = "/api/v1"
    
    class Config:
        env_file = ".env"
```

### 4.2 Settings module: AFTER
```python
# app/core/config.py
from pydantic_settings import BaseSettings
from typing import Optional
import secrets


class Settings(BaseSettings):
    PROJECT_NAME: str = "My FastAPI App"
    VERSION: str = "1.0.0"
    
    # Security settings - now from environment variables
    SECRET_KEY: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # Database
    DATABASE_URL: str = ""
    
    # API
    API_V1_STR: str = "/api/v1"
    
    # Security scan configuration
    SECURITY_SCAN_FAIL_ON: str = "high"
    SECURITY_SCAN_EXCLUDE_PATHS: list[str] = ["tests/", "migrations/", ".venv/"]
    SECURITY_SCAN_ENABLED_CHECKS: list[str] = ["bandit", "semgrep", "pip-audit"]
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.SECRET_KEY:
            raise ValueError("SECRET_KEY must be set in environment variables")
        if not self.DATABASE_URL:
            raise ValueError("DATABASE_URL must be set in environment variables")
    
    class Config:
        env_file = ".env"
        env_prefix = "APP_"
```

### 4.3 Security scanner service (NEW)
```python
# app/services/security_scanner.py
import subprocess
import json
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple
from dataclasses import dataclass
import tempfile
import sys


@dataclass
class ScanResult:
    tool: str
    findings: List[Dict]
    error: Optional[str] = None
    exit_code: int = 0


class SecurityScanner:
    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self.config_dir = project_dir / ".security"
        
    def run_bandit(self, exclude_paths: List[str]) -> ScanResult:
        """Run bandit security linter."""
        config_path = self.config_dir / "bandit.yaml"
        output_file = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        
        cmd = [
            "bandit", "-r", str(self.project_dir),
            "-f", "json",
            "-o", output_file.name,
            "-c", str(config_path)
        ]
        
        if exclude_paths:
            cmd.extend(["-x", ",".join(exclude_paths)])
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            with open(output_file.name, "r") as f:
                findings = json.load(f).get("results", [])
            
            return ScanResult(
                tool="bandit",
                findings=findings,
                exit_code=result.returncode
            )
        except subprocess.TimeoutExpired:
            return ScanResult(
                tool="bandit",
                findings=[],
                error="Bandit scan timed out after 300 seconds",
                exit_code=1
            )
        finally:
            Path(output_file.name).unlink(missing_ok=True)
    
    def run_semgrep(self, checks: Optional[List[str]]) -> ScanResult:
        """Run semgrep with FastAPI-specific rules."""
        config_path = self.config_dir / "semgrep"
        output_file = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        
        cmd = [
            "semgrep", "scan",
            "--config", str(config_path),
            "--json",
            "--output", output_file.name,
            str(self.project_dir)
        ]
        
        if checks:
            cmd.extend(["--include", ",".join(checks)])
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            with open(output_file.name, "r") as f:
                data = json.load(f)
                findings = data.get("results", [])
            
            return ScanResult(
                tool="semgrep",
                findings=findings,
                exit_code=result.returncode
            )
        except subprocess.TimeoutExpired:
            return ScanResult(
                tool="semgrep",
                findings=[],
                error="Semgrep scan timed out after 300 seconds",
                exit_code=1
            )
        finally:
            Path(output_file.name).unlink(missing_ok=True)
    
    def run_pip_audit(self) -> ScanResult:
        """Run pip-audit for dependency CVEs."""
        output_file = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        
        cmd = [
            "pip-audit",
            "--format", "json",
            "--output", output_file.name
        ]
        
        # Check for requirements files
        req_files = [
            self.project_dir / "requirements.txt",
            self.project_dir / "requirements-dev.txt",
            self.project_dir / "pyproject.toml"
        ]
        
        for req_file in req_files:
            if req_file.exists():
                cmd.extend(["--requirement", str(req_file)])
                break
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            with open(output_file.name, "r") as f:
                data = json.load(f)
                findings = data.get("vulnerabilities", [])
            
            return ScanResult(
                tool="pip-audit",
                findings=findings,
                exit_code=result.returncode
            )
        except subprocess.TimeoutExpired:
            return ScanResult(
                tool="pip-audit",
                findings=[],
                error="pip-audit scan timed out after 60 seconds",
                exit_code=1
            )
        finally:
            Path(output_file.name).unlink(missing_ok=True)
```

### 4.4 Security findings CRUD (NEW)
```python
# app/crud/security_finding.py
from typing import List, Optional, Dict, Any
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, and_
from sqlalchemy.orm import selectinload

from app.models.security_finding import SecurityFinding
from app.schemas.security_finding import SecurityFindingCreate, SecurityFindingUpdate


async def create_finding(
    db: AsyncSession,
    *,
    finding_in: SecurityFindingCreate
) -> SecurityFinding:
    """Create a new security finding."""
    db_finding = SecurityFinding(
        scan_id=finding_in.scan_id,
        tool=finding_in.tool,
        check_id=finding_in.check_id,
        file_path=finding_in.file_path,
        line_number=finding_in.line_number,
        severity=finding_in.severity,
        confidence=finding_in.confidence,
        message=finding_in.message,
        rule_id=finding_in.rule_id,
        rule_name=finding_in.rule_name,
        rule_url=finding_in.rule_url,
        raw_data=finding_in.raw_data
    )
    db.add(db_finding)
    await db.commit()
    await db.refresh(db_finding)
    return db_finding


async def bulk_create_findings(
    db: AsyncSession,
    *,
    findings: List[SecurityFindingCreate]
) -> List[SecurityFinding]:
    """Create multiple security findings in bulk."""
    db_findings = []
    for finding_in in findings:
        db_finding = SecurityFinding(
            scan_id=finding_in.scan_id,
            tool=finding_in.tool,
            check_id=finding_in.check_id,
            file_path=finding_in.file_path,
            line_number=finding_in.line_number,
            severity=finding_in.severity,
            confidence=finding_in.confidence,
            message=finding_in.message,
            rule_id=finding_in.rule_id,
            rule_name=finding_in.rule_name,
            rule_url=finding_in.rule_url,
            raw_data=finding_in.raw_data
        )
        db_findings.append(db_finding)
    
    db.add_all(db_findings)
    await db.commit()
    
    # Refresh all created findings
    for finding in db_findings:
        await db.refresh(finding)
    
    return db_findings


async def get_findings_by_scan(
    db: AsyncSession,
    *,
    scan_id: UUID,
    skip: int = 0,
    limit: int = 100,
    severity: Optional[str] = None,
    tool: Optional[str] = None
) -> List[SecurityFinding]:
    """Get findings for a specific scan with optional filters."""
    query = select(SecurityFinding).where(SecurityFinding.scan_id == scan_id)
    
    if severity:
        query = query.where(SecurityFinding.severity == severity)
    
    if tool:
        query = query.where(SecurityFinding.tool == tool)
    
    query = query.offset(skip).limit(limit).order_by(
        SecurityFinding.severity.desc(),
        SecurityFinding.line_number.asc()
    )
    
    result = await db.execute(query)
    return result.scalars().all()


async def mark_finding_as_fixed(
    db: AsyncSession,
    *,
    finding_id: UUID,
    fixed_by: str,
    fix_comment: Optional[str] = None
) -> Optional[SecurityFinding]:
    """Mark a security finding as fixed."""
    stmt = (
        update(SecurityFinding)
        .where(SecurityFinding.id == finding_id)
        .values(
            fixed=True,
            fixed_by=fixed_by,
            fix_comment=fix_comment,
            fixed_at=func.now()
        )
        .returning(SecurityFinding)
    )
    
    result = await db.execute(stmt)
    await db.commit()
    return result.scalar_one_or_none()
```

### 4.5 Security scan API endpoint (NEW)
```python
# app/api/endpoints/security_scan.py
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from typing import List, Literal, Optional
from uuid import UUID, uuid4
from pathlib import Path
import asyncio

from app.core.deps import get_current_user, get_db
from app.core.config import get_settings
from app.services.security_scanner import SecurityScanner
from app.schemas.security_scan import (
    SecurityScanRequest,
    SecurityScanResponse,
    SecurityScanStatus
)
from app.crud.security_scan import create_scan, update_scan_status
from app.crud.security_finding import bulk_create_findings
from app.models.user import User
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/security", tags=["security"])


@router.post("/scan", response_model=SecurityScanResponse)
async def trigger_security_scan(
    request: SecurityScanRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Trigger a security scan of the codebase."""
    if not current_user.is_admin:
        raise HTTPException(
            status_code=403,
            detail="Only administrators can trigger security scans"
        )
    
    # Create scan record
    scan_id = uuid4()
    scan_data = {
        "id": scan_id,
        "initiated_by": current_user.id,
        "fail_on": request.fail_on,
        "checks": request.checks,
        "exclude_paths": request.exclude_paths
    }
    
    await create_scan(db, scan_data=scan_data)
    
    # Start background scan
    background_tasks.add_task(
        run_security_scan_background,
        scan_id=scan_id,
        project_dir=Path.cwd(),
        request=request,
        db=db
    )
    
    return SecurityScanResponse(
        scan_id=scan_id,
        status=SecurityScanStatus.PENDING,
        message="Security scan started in background"
    )


@router.get("/scan/{scan_id}", response_model=SecurityScanResponse)
async def get_scan_status(
    scan_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get the status and results of a security scan."""
    from app.crud.security_scan import get_scan_by_id
    
    scan = await get_scan_by_id(db, scan_id=scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    
    if not current_user.is_admin and scan.initiated_by != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="You can only view your own scans"
        )
    
    return SecurityScanResponse(
        scan_id=scan.id,
        status=scan.status,
        started_at=scan.started_at,
        completed_at=scan.completed_at,
        findings_count=scan.findings_count,
        critical_count=scan.critical_count,
        high_count=scan.high_count,
        medium_count=scan.medium_count,
        low_count=scan.low_count,
        passed=scan.passed,
        report_path=scan.report_path
    )


async def run_security_scan_background(
    scan_id: UUID,
    project_dir: Path,
    request: SecurityScanRequest,
    db: AsyncSession
):
    """Background task to run the security scan."""
    await update_scan_status(db, scan_id=scan_id, status=SecurityScanStatus.RUNNING)
    
    try:
        scanner = SecurityScanner(project_dir)
        findings = []
        
        # Run bandit
        if not request.checks or "bandit" in request.checks:
            bandit_result = scanner.run_bandit(request.exclude_paths or [])
            findings.extend(convert_bandit_findings(bandit_result, scan_id))
        
        # Run semgrep
        if not request.checks or "semgrep" in request.checks:
            semgrep_result = scanner.run_semgrep(request.checks)
            findings.extend(convert_semgrep_findings(semgrep_result, scan_id))
        
        # Run pip-audit
        if not request.checks or "pip-audit" in request.checks:
            audit_result = scanner.run_pip_audit()
            findings.extend(convert_pip_audit_findings(audit_result, scan_id))
        
        # Store findings
        if findings:
            await bulk_create_findings(db, findings=findings)
        
        # Update scan status
        await update_scan_status(
            db,
            scan_id=scan_id,
            status=SecurityScanStatus.COMPLETED,
            findings_count=len(findings),
            passed=determine_if_passed(findings, request.fail_on)
        )
        
    except Exception as e:
        await update_scan_status(
            db,
            scan_id=scan_id,
            status=SecurityScanStatus.FAILED,
            error_message=str(e)
        )
```

### 4.6 Security scan schemas (NEW)
```python
# app/schemas/security_scan.py
from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Dict, Any
from uuid import UUID
from datetime import datetime
from enum import Enum


class SecurityScanStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class SecurityScanRequest(BaseModel):
    fail_on: Literal["critical", "high", "medium", "low"] = Field(
        default="high",
        description="Minimum severity that fails the build"
    )
    checks: Optional[List[str]] = Field(
        default=None,
        description="Specific check families to run (bandit, semgrep, pip-audit)"
    )
    exclude_paths: Optional[List[str]] = Field(
        default=None,
        description="Paths to exclude from scanning"
    )


class SecurityScanResponse(BaseModel):
    scan_id: UUID
    status: SecurityScanStatus
    message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    findings_count: int = 0
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    passed: Optional[bool] = None
    report_path: Optional[str] = None
    error_message: Optional[str] = None


class SecurityFindingCreate(BaseModel):
    scan_id: UUID
    tool: str = Field(..., max_length=32)
    check_id: str = Field(..., max_length=64)
    file_path: str = Field(..., max_length=512)
    line_number: int = Field(..., ge=1)
    severity: str = Field(..., max_length=16)
    confidence: str = Field(..., max_length=16)
    message: str = Field(..., max_length=1024)
    rule_id: Optional[str] = Field(None, max_length=128)
    rule_name: Optional[str] = Field(None, max_length=256)
    rule_url: Optional[str] = Field(None, max_length=512)
    raw_data: Optional[Dict[str, Any]] = None


class SecurityFindingResponse(BaseModel):
    id: UUID
    scan_id: UUID
    tool: str
    check_id: str
    file_path: str
    line_number: int
    severity: str
    confidence: str
    message: str
    rule_id: Optional[str]
    rule_name: Optional[str]
    rule_url: Optional[str]
    fixed: bool
    fixed_by: Optional[str]
    fix_comment: Optional[str]
    fixed_at: Optional[datetime]
    created_at: datetime
    
    class Config:
        from_attributes = True
```

### 4.7 Security middleware (NEW)
```python
# app/middleware/security_headers.py
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from typing import Callable, Dict


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add security headers to all responses.
    This is an example fix for security scan findings about missing security headers.
    """
    
    def __init__(self, app, **kwargs):
        super().__init__(app)
        self.headers = {
            "X-Frame-Options": "DENY",
            "X-Content-Type-Options": "nosniff",
            "X-XSS-Protection": "1; mode=block",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
            "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'",
            "Permissions-Policy": "geolocation=(), microphone=(), camera=()"
        }
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        
        # Don't add headers to error responses that might already have custom headers
        if response.status_code >= 400 and response.status_code < 600:
            return response
        
        # Add security headers
        for header, value in self.headers.items():
            response.headers[header] = value
        
        # Remove server header if present
        if "Server" in response.headers:
            del response.headers["Server"]
        
        return response


# app/middleware/__init__.py
from fastapi import FastAPI


def add_security_middleware(app: FastAPI) -> None:
    """Add security middleware to the FastAPI app."""
    from .security_headers import SecurityHeadersMiddleware
    
    app.add_middleware(SecurityHeadersMiddleware)
```

### 4.8 Migration for security scan tables
```python
# alembic/versions/0030_add_security_scan_tables.py
"""Add security scan tables

Revision ID: 0030
Revises: 0029
Create Date: 2026-04-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0030"
down_revision = "0029"


def upgrade() -> None:
    # Create security_scans table
    op.create_table(
        "security_scans",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("initiated_by", sa.UUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("fail_on", sa.String(16), nullable=False, server_default="high"),
        sa.Column("checks", postgresql.ARRAY(sa.String(32)), nullable=True),
        sa.Column("exclude_paths", postgresql.ARRAY(sa.String(512)), nullable=True),
        sa.Column("findings_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("critical_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("high_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("medium_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("low_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("report_path", sa.String(1024), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    
    # Create security_findings table
    op.create_table(
        "security_findings",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("scan_id", sa.UUID(), sa.ForeignKey("security_scans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tool", sa.String(32), nullable=False),
        sa.Column("check_id", sa.String(64), nullable=False),
        sa.Column("file_path", sa.String(512), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("confidence", sa.String(16), nullable=False),
        sa.Column("message", sa.String(1024), nullable=False),
        sa.Column("rule_id", sa.String(128), nullable=True),
        sa.Column("rule_name", sa.String(256), nullable=True),
        sa.Column("rule_url", sa.String(512), nullable=True),
        sa.Column("raw_data", postgresql.JSONB(), nullable=True),
        sa.Column("fixed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("fixed_by", sa.UUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("fix_comment", sa.Text(), nullable=True),
        sa.Column("fixed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    
    # Create indexes
    op.create_index("ix_security_scans_status", "security_scans", ["status"])
    op.create_index("ix_security_scans_initiated_by", "security_scans", ["initiated_by"])
    op.create_index("ix_security_scans_created_at", "security_scans", ["created_at"])
    
    op.create_index("ix_security_findings_scan_id", "security_findings", ["scan_id"])
    op.create_index("ix_security_findings_severity", "security_findings", ["severity"])
    op.create_index("ix_security_findings_tool", "security_findings", ["tool"])
    op.create_index("ix_security_findings_fixed", "security_findings", ["fixed"])
    op.create_index("ix_security_findings_file_path", "security_findings", ["file_path"])
    
    # Create check constraints
    op.create_check_constraint(
        "ck_security_scans_status",
        "security_scans",
        "status IN ('pending', 'running', 'completed', 'failed')"
    )
    op.create_check_constraint(
        "ck_security_scans_fail_on",
        "security_scans",
        "fail_on IN ('critical', 'high', 'medium', 'low')"
    )
    op.create_check_constraint(
        "ck_security_findings_severity",
        "security_findings",
        "severity IN ('critical', 'high', 'medium', 'low', 'info')"
    )
    op.create_check_constraint(
        "ck_security_findings_confidence",
        "security_findings",
        "confidence IN ('high', 'medium', 'low')"
    )


def downgrade() -> None:
    op.drop_table("security_findings")
    op.drop_table("security_scans")
```

### 4.9 Security scan configuration module (NEW)
```python
# app/core/security_config.py
import yaml
from pathlib import Path
from typing import Dict, Any, List
import json


class SecurityConfig:
    """Manages security scan configuration files."""
    
    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self.config_dir = project_dir / ".security"
        self.config_dir.mkdir(exist_ok=True)
    
    def create_bandit_config(self) -> Path:
        """Create bandit configuration file."""
        config = {
            "exclude_dirs": ["tests", "migrations", ".venv", "__pycache__"],
            "skips": ["B101", "B105"],  # Skip assert_used, hardcoded_password_string
            "tests": [
                "B201",  # flask_debug_true
                "B301", "B302", "B303", "B304", "B305", "B306",  # pickle, marshal, etc.
                "B308",  # mark_safe
                "B310",  # urllib_urlopen
                "B311",  # random
                "B403",  # import_pickle
                "B404",  # import_subprocess
                "B502",  # ssl_with_bad_version
                "B506",  # yaml_load
                "B602",  # subprocess_without_shell_equals_true
            ],
            "confidence_level": "high",
            "severity_level": "medium"
        }
        
        config_path = self.config_dir / "bandit.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f, default_flow_style=False)
        
        return config_path
    
    def create_semgrep_rules(self) -> Path:
        """Create semgrep rules directory with FastAPI-specific rules."""
        rules_dir = self.config_dir / "semgrep"
        rules_dir.mkdir(exist_ok=True)
        
        # FastAPI-specific rules
        fastapi_rules = {
            "rules": [
                {
                    "id": "fastapi-hardcoded-secret",
                    "pattern": "SECRET_KEY = \"...\"",
                    "message": "Hardcoded secret key - use environment variables",
                    "severity": "ERROR",
                    "languages": ["python"],
                    "fix": "SECRET_KEY = os.getenv(\"SECRET_KEY\")"
                },
                {
                    "id": "fastapi-missing-auth",
                    "pattern": |
                        @router.$METHOD("$PATH")
                        async def $FUNC(...):
                            ...
                    "message": "Route missing authentication dependency",
                    "severity": "WARNING",
                    "languages": ["python"],
                    "pattern-not": |
                        @router.$METHOD("$PATH")
                        async def $FUNC(..., $AUTH: $TYPE = Depends(...)):
                            ...
                },
                {
                    "id": "fastapi-raw-sql",
                    "pattern": "session.execute(\"SELECT ... $VAR ...\")",
                    "message": "Potential SQL injection - use parameterized queries",
                    "severity": "ERROR",
                    "languages": ["python"],
                    "fix": "session.execute(text(\"... :param ...\"), {\"param\": $VAR})"
                }
            ]
        }
        
        rules_path = rules_dir / "fastapi-rules.yaml"
        with open(rules_path, "w") as f:
            yaml.dump(fastapi_rules, f, default_flow_style=False)
        
        return rules_dir
    
    def create_exclusion_file(self, exclude_paths: List[str]) -> Path:
        """Create file with paths to exclude from scanning."""
        exclusion_file = self.project_dir / ".securityignore"
        
        default_exclusions = [
            "# Exclude test and development files",
            "tests/",
            "test_*.py",
            "*_test.py",
            "migrations/",

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **All findings are persisted regardless of fail threshold** | `scripts/sarif_generator.py` writes SARIF report with all findings, filtered only in CI via `fail_on` parameter |
| QS-2 | **Scan never modifies source code** | `security_scan()` function in `scripts/security_scan.py` runs scanners in read-only mode with `--json` output |
| QS-3 | **Exclusions are always explicit** | `.bandit` config file requires `exclude_dirs` and `skips` lists; `.semgrepignore` file defines path exclusions |
| QS-4 | **Custom rules are versioned in repo** | `.semgrep/fastapi/security.yml` contains FastAPI-specific rules tracked in Git |
| QS-5 | **pip-audit always checks lockfile** | `pip-audit` command in CI workflow uses `--requirement requirements.txt` or `--lockfile poetry.lock` |
| QS-6 | **Severity levels are consistently mapped** | `map_severity()` function in `scripts/sarif_generator.py` converts tool-specific levels to SARIF standard |
| QS-7 | **Findings are deduplicated across tools** | `security_scan()` function merges results from bandit, semgrep, and pip-audit with unique rule IDs |
| QS-8 | **False positives require justification** | `# nosec` and `# semgrep: ignore` comments require accompanying explanation in code |
| QS-9 | **Custom rules are validated at startup** | `scripts/security_scan.py` calls `semgrep --validate` on `.semgrep/fastapi/security.yml` before scanning |
| QS-10 | **Reports include fix suggestions** | `.semgrep/fastapi/security.yml` rules include `fix:` blocks with concrete remediation steps |
| QS-11 | **Tool is idempotent across runs** | `security_scan()` function generates same results when re-run with identical config and code |
| QS-12 | **CI integration uploads SARIF** | `.github/workflows/security-scan.yml` uses `github/codeql-action/upload-sarif@v2` to publish findings |

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `.bandit` config file exists | File exists, parses with `configparser` |
| CC-02 | `.semgrep/fastapi/security.yml` exists | File exists, contains FastAPI-specific rules |
| CC-03 | `scripts/security_scan.py` exists | File exists, exports `security_scan()` function |
| CC-04 | `scripts/sarif_generator.py` exists | File exists, exports `generate_sarif()` function |
| CC-05 | `.github/workflows/security-scan.yml` exists | File exists, contains `security-scan` job |
| CC-06 | `tests/test_security_scan.py` exists | File exists, contains 30 tests |
| CC-07 | Bandit finds hardcoded secrets | T-01 |
| CC-08 | Semgrep finds missing Depends() | T-07 |
| CC-09 | pip-audit finds CVEs | T-03 |
| CC-10 | Custom rules find raw SQL | T-08 |
| CC-11 | File exclusions work | T-13 |
| CC-12 | Inline suppressions work | T-14 |
| CC-13 | Rule disable works | T-15 |
| CC-14 | CI uploads SARIF | T-19 |
| CC-15 | PR annotations work | T-20 |
| CC-16 | Exit codes match severity | T-21 |
| CC-17 | Reports include fix suggestions | Inspect SARIF output |
| CC-18 | Findings are deduplicated | T-22 |
| CC-19 | Tool is idempotent | T-25 |
| CC-20 | Empty project scans cleanly | T-26 |
| CC-21 | Generated code is excluded | T-27 |
| CC-22 | Vendored code is excluded | T-28 |
| CC-23 | Severity mapping is consistent | Inspect `map_severity()` |
| CC-24 | Custom rules are validated | T-29 |
| CC-25 | False positives require justification | grep `# nosec` comments |
| CC-26 | Reports persist all findings | Inspect SARIF output |
| CC-27 | Scan never modifies code | Inspect `security_scan()` |
| CC-28 | Exclusions are explicit | Inspect `.bandit` and `.semgrepignore` |
| CC-29 | Custom rules are versioned | grep `.semgrep/fastapi/security.yml` |
| CC-30 | pip-audit checks lockfile | Inspect CI workflow |

## 7. Definition of Done (DoD)

- [ ] All 30 Completeness Criteria verified
- [ ] SARIF report generated for all findings
- [ ] CI workflow uploads SARIF to GitHub Security tab
- [ ] Custom FastAPI rules validated and versioned
- [ ] Exclusions configured in `.bandit` and `.semgrepignore`
- [ ] False positive suppressions justified with comments
- [ ] All 30 tests pass in `tests/test_security_scan.py`
- [ ] Severity levels consistently mapped to SARIF standard
- [ ] Findings deduplicated across bandit, semgrep, and pip-audit
- [ ] Reports include fix suggestions for each finding
- [ ] Tool is idempotent across runs
- [ ] Scan never modifies source code
- [ ] pip-audit checks lockfile, not freeze
- [ ] Custom rules directory `.semgrep/fastapi` exists

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-SS-01 | Scan NEVER modifies source code | `security_scan()` function runs scanners in read-only mode with `--json` output | T-25 |
| INV-SS-02 | All findings are PERSISTED regardless of fail threshold | `scripts/sarif_generator.py` writes SARIF report with all findings, filtered only in CI | T-19 |
| INV-SS-03 | Exclusions are ALWAYS explicit | `.bandit` config file requires `exclude_dirs` and `skips` lists; `.semgrepignore` defines path exclusions | T-13 |
| INV-SS-04 | Scan exits non-zero if any finding >= fail_on severity | `security_scan()` function compares finding severity to `fail_on` threshold | T-21 |
| INV-SS-05 | Reports include finding location, severity, rule ID, and fix suggestion | `scripts/sarif_generator.py` includes required SARIF fields in report | T-22 |
| INV-SS-06 | pip-audit ALWAYS checks current lockfile | `.github/workflows/security-scan.yml` uses `--lockfile` parameter for pip-audit | T-03 |
| INV-SS-07 | Custom rules are VERSIONED in repo | `.semgrep/fastapi/security.yml` is tracked in Git with semantic versioning | T-29 |
| INV-SS-08 | Tool is IDEMPOTENT across runs | `security_scan()` function generates same results when re-run with identical config and code | T-25 |

---

## 9. User Stories

### 9.1 Core functionality (US-01 .. US-05)

**US-01: Detect hardcoded secrets**
- **As a** security engineer
- **I want** to find hardcoded API keys and passwords
- **So that** I can rotate them before deployment
- **Given:** `app/config.py` contains `API_KEY = "sk_live_1234567890"`
- **When:** I run `security_scan(project_dir="/app", fail_on="high")`
- **Then:**
  - Bandit rule B105 flags the line (INV-SS-05)
  - Report includes fix suggestion to use env vars (CC-17)
  - Scan exits with code 1 (INV-SS-04)

**US-02: Find SQL injection risks**
- **As a** backend developer
- **I want** to detect raw SQL strings
- **So that** I can use parameterized queries
- **Given:** `app/db.py` contains `session.execute("SELECT * FROM users WHERE id=" + user_id)`
- **When:** I run the scan with custom semgrep rules
- **Then:**
  - Semgrep rule `fastapi-raw-sql` flags the line (CC-10)
  - Report suggests using `text()` with params (QS-10)
  - Finding severity is ERROR (INV-SS-05)

**US-03: Check for missing auth on routes**
- **As a** API developer
- **I want** to find routes without authentication
- **So that** I can secure sensitive endpoints
- **Given:** `app/main.py` contains `@app.get("/admin")` without Depends()
- **When:** I run the scan with FastAPI custom rules
- **Then:**
  - Semgrep rule `fastapi-missing-auth` flags the route (CC-08)
  - Report suggests adding `Depends(get_current_user)` (QS-10)
  - Finding severity is WARNING (INV-SS-05)

**US-04: Audit dependencies for CVEs**
- **As a** DevOps engineer
- **When:** I run `security_scan(project_dir="/app")`
- **Then:**
  - pip-audit checks `requirements.txt` (INV-SS-06)
  - Report lists any CVEs with severity levels (CC-09)
  - Findings persist even if below fail threshold (INV-SS-02)

**US-05: Generate SARIF report**
- **As a** CI/CD engineer
- **I want** to integrate findings into GitHub Security
- **So that** developers can track fixes
- **Given:** scan found 3 high severity issues
- **When:** I run the scan with default config
- **Then:**
  - SARIF report includes all findings (QS-1)
  - GitHub Actions uploads report (CC-14)
  - Findings deduplicated across tools (QS-7)

### 9.2 Configuration & exclusions (US-06 .. US-10)

**US-06: Exclude test files**
- **As a** developer
- **I want** to skip test directories
- **So that** I don't get false positives in test code
- **Given:** `.bandit` config with `exclude_dirs = tests`
- **When:** I run the scan on `/app/tests/test_auth.py`
- **Then:**
  - File is excluded from bandit scan (INV-SS-03)
  - Scan completes without findings in test files (T-13)
  - Report notes excluded paths (QS-3)

**US-07: Suppress false positives**
- **As a** security engineer
- **I want** to annotate intentional exceptions
- **So that** I can track justified suppressions
- **Given:** `app/utils.py` contains `# nosec: justified in ticket SEC-123`
- **When:** I run the scan with default config
- **Then:**
  - Finding is suppressed but still logged (CC-12)
  - Report includes justification comment (QS-8)
  - Scan exits with code 0 if no other findings (INV-SS-04)

**US-08: Disable specific rules**
- **As a** team lead
- **I want** to turn off noisy rules
- **So that** we can focus on critical issues
- **Given:** `.bandit` config with `skips = B101`
- **When:** I run the scan on code with `assert` statements
- **Then:**
  - Bandit rule B101 is skipped (INV-SS-03)
  - Report notes disabled rules (QS-3)
  - Scan completes faster without B101 checks (CC-13)

**US-09: Custom rule validation**
- **As a** security architect
- **I want** to ensure custom rules are valid
- **So that** scans don't fail due to syntax errors
- **Given:** `.semgrep/fastapi/security.yml` with custom rules
- **When:** I run `security_scan(project_dir="/app")`
- **Then:**
  - Semgrep validates rules before scanning (QS-9)
  - Invalid rules cause scan to fail fast (T-29)
  - Report includes rule validation status (CC-24)

**US-10: Version control for custom rules**
- **As a** security engineer
- **I want** to track rule changes
- **So that** we can audit security checks
- **Given:** `.semgrep/fastapi/security.yml` in Git
- **When:** I modify a rule
- **Then:**
  - Changes are versioned in Git (INV-SS-07)
  - CI fails if rules file is missing (CC-02)
  - Report includes rule version metadata (QS-4)

### 9.3 Edge cases & error handling (US-11 .. US-15)

**US-11: Handle empty projects**
- **As a** developer
- **I want** the scan to work on new projects
- **So that** I can enforce security from day one
- **Given:** `/app` directory with no Python files
- **When:** I run `security_scan(project_dir="/app")`
- **Then:**
  - Scan completes successfully (CC-20)
  - Report shows 0 findings (T-26)
  - Exit code is 0 (INV-SS-04)

**US-12: Graceful semgrep failure**
- **As a** CI/CD engineer
- **I want** the scan to continue if semgrep fails
- **So that** we still get bandit and pip-audit results
- **Given:** semgrep not installed
- **When:** I run the scan with default config
- **Then:**
  - Tool warns about missing semgrep (CC-02)
  - Bandit and pip-audit still run (QS-7)
  - Report notes skipped semgrep scan (INV-SS-02)

**US-13: Handle generated code**
- **As a** backend developer
- **I want** to exclude alembic migrations
- **So that** I don't get false positives in generated SQL
- **Given:** `.semgrepignore` with `alembic/versions/`
- **When:** I run the scan on `/app/alembic/versions/0001_init.py`
- **Then:**
  - Generated code is excluded (CC-21)
  - Report notes excluded paths (QS-3)
  - Scan completes without migration findings (T-27)

**US-14: Offline pip-audit**
- **As a** security engineer
- **I want** to check dependencies offline
- **So that** I can scan air-gapped systems
- **Given:** no internet access
- **When:** I run `security_scan(project_dir="/app")`
- **Then:**
  - pip-audit uses local CVE database (CC-09)
  - Report notes offline mode (INV-SS-06)
  - Scan completes with dependency findings (T-03)

**US-15: Handle interrupted scans**
- **As a** CI/CD engineer
- **I want** partial results if scan is interrupted
- **So that** I can debug the failure
- **Given:** scan interrupted mid-bandit run
- **When:** I inspect the output
- **Then:**
  - Partial SARIF report is generated (INV-SS-02)
  - Exit code is non-zero (INV-SS-04)
  - Report notes incomplete scan (CC-11)

### 9.4 CI/CD integration (US-16 .. US-20)

**US-16: Upload SARIF to GitHub**
- **As a** DevOps engineer
- **I want** to integrate findings into GitHub Security
- **So that** developers can track fixes
- **Given:** GitHub Actions workflow with `upload-sarif`
- **When:** I push to `main` branch
- **Then:**
  - SARIF report is uploaded (CC-14)
  - Findings appear in Security tab (T-19)
  - PRs show annotations (CC-15)

**US-17: Fail CI on high severity**
- **As a** security engineer
- **I want** CI to fail on critical issues
- **So that** we block insecure deployments
- **Given:** scan finds high severity SQL injection
- **When:** CI runs with `fail_on="high"`
- **Then:**
  - CI job fails (INV-SS-04)
  - SARIF report persists all findings (INV-SS-02)
  - PR shows failed check (CC-20)

**US-18: Annotate PRs with findings**
- **As a** developer
- **I want** to see security issues in PRs
- **So that** I can fix them before merging
- **Given:** PR with hardcoded secret
- **When:** CI runs security scan
- **Then:**
  - PR shows inline annotation (CC-15)
  - Annotation links to fix suggestion (QS-10)
  - Severity level is visible (INV-SS-05)

**US-19: Track scan history**
- **As a** security manager
- **I want** to track scan results over time
- **So that** I can measure improvement
- **Given:** `security_scans` table in DB
- **When:** I run `security_scan(project_dir="/app")`
- **Then:**
  - Findings are logged (CC-26)
  - Scan metadata is persisted (CC-28)
  - History is queryable (CC-29)

**US-20: Enforce justification for suppressions**
- **As a** security auditor
- **I want** to track why findings are suppressed
- **So that** we can review exceptions
- **Given:** `# nosec` comment without justification
- **When:** I run the scan
- **Then:**
  - Finding is flagged as unverified (QS-8)
  - CI fails if justification missing (CC-25)
  - Report highlights unverified suppressions (INV-SS-03)

### 9.5 Performance & observability (US-21 .. US-25)

**US-21: Fast scan for small projects**
- **As a** developer
- **I want** quick feedback on security issues
- **So that** I can iterate faster
- **Given:** project with 100 LOC
- **When:** I run `security_scan(project_dir="/app")`
- **Then:**
  - Scan completes in < 4s (CC-01)
  - Report generated in < 500ms (CC-04)
  - Exit code reflects findings (INV-SS-04)

**US-22: Handle large codebases**
- **As a** enterprise developer
- **I want** to scan large projects efficiently
- **So that** I can secure complex systems
- **Given:** project with 50K LOC
- **When:** I run the scan with default config
- **Then:**
  - Scan completes in < 60s (CC-03)
  - Memory usage < 50MB (CC-07)
  - Report includes performance metrics (CC-23)

**US-23: Idempotent scans**
- **As a** CI/CD engineer
- **I want** consistent results across runs
- **So that** I can trust the findings
- **Given:** unchanged codebase
- **When:** I run `security_scan(project_dir="/app")` twice
- **Then:**
  - Results are identical (INV-SS-08)
  - Exit codes match (CC-16)
  - Report timestamps differ but findings same (T-25)

**US-24: Track scan metrics**
- **As a** DevOps engineer
- **I want** to monitor scan performance
- **So that** I can optimize CI times
- **Given:** Prometheus metrics endpoint
- **When:** I run the scan
- **Then:**
  - Execution time is recorded (CC-01)
  - Memory usage is tracked (CC-07)
  - Findings count is logged (CC-26)

**US-25: Validate severity mapping**
- **As a** security engineer
- **I want** consistent severity levels
- **So that** I can trust the fail gates
- **Given:** bandit finding with severity HIGH
- **When:** I run the scan with `fail_on="high"`
- **Then:**
  - Severity mapped correctly (QS-6)
  - Exit code reflects severity (INV-SS-04)
  - SARIF report uses standard levels (CC-23)

---

## 10. Test Plan

### 10.1 Core vulnerability detection tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | Bandit finds hardcoded password | `app/config.py` contains `PASSWORD = "secret123"` | Run scan with default config | Bandit B105 finding at line with severity HIGH |
| T-02 | Semgrep finds missing Depends() | `app/main.py` has `@app.get("/admin")` without auth | Run scan with FastAPI rules | Semgrep `fastapi-missing-auth` finding with severity WARNING |
| T-03 | pip-audit finds CVE in dependencies | `requirements.txt` contains vulnerable package | Run scan with default config | pip-audit reports CVE with severity CRITICAL |
| T-04 | Semgrep finds raw SQL string | `app/db.py` has `session.execute("SELECT * FROM users")` | Run scan with FastAPI rules | Semgrep `fastapi-raw-sql` finding with severity ERROR |
| T-05 | Bandit finds unsafe YAML load | `app/utils.py` has `yaml.load(unsafe_input)` | Run scan with default config | Bandit B506 finding with severity HIGH |
| T-06 | Semgrep finds hardcoded JWT secret | `app/auth.py` has `SECRET_KEY = "changeme"` | Run scan with FastAPI rules | Semgrep custom rule finding with severity CRITICAL |

### 10.2 Configuration & exclusion tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-07 | File exclusion works | `.semgrepignore` contains `tests/` | Run scan on `tests/test_auth.py` | File excluded, no findings reported |
| T-08 | Rule suppression works | `app/config.py` has `# nosec: Justified in SEC-123` before secret | Run scan with default config | Bandit B105 suppressed but logged |
| T-09 | Rule disable works | `.bandit` has `skips = B101` | Run scan on code with `assert` | No B101 findings reported |
| T-10 | Custom rules are loaded | `.semgrep/fastapi/security.yml` exists | Run scan with `--validate` | Semgrep reports valid rules |
| T-11 | Empty project scans cleanly | Project dir with no Python files | Run scan with default config | Exit code 0, 0 findings |
| T-12 | Generated code excluded | `.semgrepignore` contains `alembic/` | Run scan on `alembic/versions/0001.py` | File excluded from findings |

### 10.3 CI & reporting tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-13 | SARIF report generated | Scan finds 1 high severity issue | Run scan with default config | `security-results.sarif` created with finding |
| T-14 | CI fails on high severity | Scan finds SQL injection (ERROR) | Run CI with `fail_on="high"` | CI job fails with exit code 1 |
| T-15 | PR annotations work | PR introduces hardcoded secret | CI runs security scan | PR shows inline annotation for B105 |
| T-16 | All findings persisted | 3 findings (1 high, 2 low) with `fail_on="high"` | Inspect SARIF report | All 3 findings included |
| T-17 | Severity mapping consistent | Bandit HIGH severity finding | Run scan and check SARIF | Mapped to SARIF "error" level |
| T-18 | Findings deduplicated | Same line flagged by bandit and semgrep | Run scan with both tools | Single entry in SARIF report |

### 10.4 Edge case & error handling tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-19 | Semgrep missing falls back | semgrep not installed | Run scan with default config | Bandit and pip-audit still run |
| T-20 | pip-audit offline mode | No internet connection | Run scan with default config | Uses local CVE database |
| T-21 | Invalid custom rule fails | `.semgrep/fastapi/broken.yml` has syntax error | Run scan with `--validate` | Exit code 1, error message |
| T-22 | Interrupted scan partial results | Kill process during bandit run | Inspect output directory | Partial SARIF report exists |
| T-23 | Tool idempotent across runs | Unchanged codebase | Run scan twice | Identical SARIF outputs |
| T-24 | Vendored code excluded | `.bandit` has `exclude_dirs = vendor` | Run scan on `vendor/lib.py` | No findings reported |

### 10.5 Performance & integration tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-25 | Small project fast scan | Project with 100 LOC | Time scan execution | Completes in < 4s |
| T-26 | Large project SLO | Project with 50K LOC | Time full scan | Completes in < 60s |
| T-27 | Memory usage limit | Project with 10K LOC | Monitor memory usage | < 50MB peak usage |
| T-28 | Report generation speed | Scan finds 50 issues | Time report generation | SARIF created in < 500ms |
| T-29 | Custom rule validation | `.semgrep/fastapi/new_rule.yml` added | Run `semgrep --validate` | Rules validated before scan |
| T-30 | Lockfile always checked | Project uses `poetry.lock` | Run pip-audit | Scans lockfile not freeze |

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| add_soft_delete | No | ✅ Compatible | Security scan runs independently of data model modifications |
| add_cursor_pagination | No | ✅ Compatible | Pagination implementation doesn't affect security scanning |
| add_search | No | ✅ Compatible | Search functionality is scanned like any other code |
| add_audit_log | No | ✅ Compatible | Audit logs are scanned but don't interfere with security checks |
| add_data_export | No | ✅ Compatible | Export endpoints are scanned for auth and injection risks |
| add_bulk_operations | No | ✅ Compatible | Bulk endpoints receive extra scrutiny for mass assignment risks |
| add_multi_tenancy | No | ✅ Compatible | Tenant checks run after security scan validates auth patterns |
| add_feature_flags | No | ✅ Compatible | Flags are scanned for hardcoded secrets in config |
| add_api_key_auth | Yes | ⚠️ Caveat | Must run after security scan to validate API key storage |
| add_oauth2_provider | Yes | ⚠️ Caveat | OAuth setup should be scanned after initial implementation |
| add_rbac | No | ✅ Compatible | RBAC rules are validated by custom semgrep patterns |
| add_mfa | No | ✅ Compatible | MFA implementation is scanned for crypto best practices |
| add_cache_layer | No | ✅ Compatible | Cache configuration checked for insecure storage patterns |
| add_outbox_pattern | No | ✅ Compatible | Outbox implementation scanned for serialization risks |
| add_sse | No | ✅ Compatible | SSE endpoints checked for proper auth and CORS |

**Conflicts:** None identified.

## 12. Rollback Procedure

### Code rollback (before deploy)
```bash
git checkout -- .bandit
git checkout -- .semgrep/fastapi/security.yml
git checkout -- scripts/security_scan.py
git checkout -- scripts/sarif_generator.py
git checkout -- .github/workflows/security-scan.yml
git checkout -- tests/test_security_scan.py
rm -f security-results.sarif
rm -f .semgrepignore
rm -f .bandit.yml
rm -f .pip-audit.cfg
```

### Database rollback (after deploy)
**N/A** — this tool is a code-only refactor. No database tables, columns, or
indexes are created. `alembic downgrade -1` would be a no-op. Skip this step.

### Data preservation rollback
**N/A** — no business data is created or migrated
by this tool. Nothing to archive.

### Failure mode: tool partially modified files
```bash
git status # Identify modified files
git checkout -- .bandit .semgrepignore # Restore config files
rm -f security-results.sarif # Remove generated reports
rm -rf .semgrep # Remove custom rules directory
```

### Emergency: Scan hangs during large codebase analysis
1. Identify scan process: `ps aux | grep security_scan`
2. Terminate process: `kill -9 <PID>`
3. Clean up partial results: `rm -f security-results.partial.json`

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | Project has no Python files | Tool exits with status 0 and empty report |
| EC-2 | Semgrep not installed | Tool warns "semgrep not found" and continues with bandit + pip-audit |
| EC-3 | pip-audit run without internet | Tool falls back to local CVE database with warning |
| EC-4 | Finding in generated code (alembic/versions/) | Finding is suppressed if path is in .semgrepignore |
| EC-5 | Custom rule has syntax error | Tool fails fast with "Invalid semgrep rule at line X" |
| EC-6 | Severity not mapped to fail_on | Tool uses default mapping (high=error, medium=warning, low=note) |
| EC-7 | False positive marked with # nosec | Finding is suppressed but still appears in full report |
| EC-8 | CI lacks SARIF upload permission | Report is generated locally but not uploaded to GitHub |
| EC-9 | Unfixed dependency CVE | Finding persists in report with "no fix available" note |
| EC-10 | Project uses poetry.lock | pip-audit automatically detects and scans lockfile |
| EC-11 | Scan interrupted mid-execution | Partial SARIF report is generated with "incomplete" flag |
| EC-12 | Multiple tools flag same line | Report deduplicates findings by rule ID and location |
| EC-13 | Tool re-run on unchanged code | Report is identical except for timestamp |
| EC-14 | Findings in vendor/ directory | Excluded if path is in .bandit exclude_dirs |
| EC-15 | New rule added after baseline | Baseline is automatically updated on next scan |

## 14. Acceptance Criteria (Final Sign-off)

✅ 1. All 30 Completeness Criteria verified via test suite  
✅ 2. SARIF report generated for all findings including suppressed ones  
✅ 3. CI workflow successfully uploads SARIF to GitHub Security tab  
✅ 4. Custom FastAPI rules validated and stored in .semgrep/fastapi  
✅ 5. Exclusions properly configured in .bandit and .semgrepignore  
✅ 6. All false positive suppressions include justification comments  
✅ 7. All 30 tests pass in tests/test_security_scan.py  
✅ 8. Severity levels consistently mapped to SARIF standard format  
✅ 9. Findings properly deduplicated across bandit, semgrep, and pip-audit  
✅ 10. Developer verifies end-to-end flow by:  
    a) Adding vulnerable test file with hardcoded secret  
    b) Running security scan locally  
    c) Checking GitHub Security tab after pushing to PR  
    d) Adding justified suppression and verifying scan passes  

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks
- [ ] Validate project_dir exists and is directory
- [ ] Verify Python files exist in project_dir/app
- [ ] Check bandit is installed and >=1.7.0
- [ ] Check semgrep is installed and >=0.110.0
- [ ] Check pip-audit is installed and >=2.4.0
- [ ] Validate .git exists for version tracking
- [ ] Verify no existing .bandit conflicts

### 15.2 Bandit configuration
- [ ] Create .bandit with default exclusions
- [ ] Set severity_level = medium
- [ ] Set confidence_level = high
- [ ] Configure skips for common false positives
- [ ] Set exclude_dirs = tests, migrations, .venv
- [ ] Set targets = app, scripts
- [ ] Validate config with bandit --validate

### 15.3 Semgrep setup
- [ ] Create .semgrep/fastapi/security.yml
- [ ] Add missing auth route rule
- [ ] Add raw SQL detection rule
- [ ] Add hardcoded JWT secret rule
- [ ] Add unsafe deserialization rule
- [ ] Add missing CORS rule
- [ ] Add rate limit bypass rule
- [ ] Validate rules with semgrep --validate

### 15.4 Scanner integration
- [ ] Implement bandit runner in security_scan.py
- [ ] Implement semgrep runner in security_scan.py
- [ ] Implement pip-audit runner in security_scan.py
- [ ] Add severity threshold enforcement
- [ ] Add checks parameter filtering
- [ ] Add exclude_paths handling
- [ ] Implement result aggregation

### 15.5 SARIF generation
- [ ] Implement SARIF 2.1.0 schema compliance
- [ ] Map bandit severities to SARIF levels
- [ ] Map semgrep severities to SARIF levels
- [ ] Map pip-audit severities to SARIF levels
- [ ] Include fix suggestions where available
- [ ] Add tool metadata and versions
- [ ] Write atomically with tempfile pattern

### 15.6 CI integration
- [ ] Create .github/workflows/security-scan.yml
- [ ] Set up Python 3.10 environment
- [ ] Install bandit, semgrep, pip-audit
- [ ] Configure fail_on=high threshold
- [ ] Add SARIF upload step
- [ ] Set cron schedule for nightly scans
- [ ] Add PR comment on findings

### 15.7 Test generation
- [ ] Create tests/test_security_scan.py
- [ ] Add test for hardcoded secret detection
- [ ] Add test for missing auth route
- [ ] Add test for raw SQL detection
- [ ] Add test for dependency CVE
- [ ] Add test for file exclusions
- [ ] Add test for rule suppressions
- [ ] Add test for severity mapping

### 15.8 Exclusion handling
- [ ] Create .semgrepignore with defaults
- [ ] Add alembic/versions exclusion
- [ ] Add generated code patterns
- [ ] Implement # nosec comment handling
- [ ] Implement # semgrep: ignore handling
- [ ] Validate exclusions work in tests
- [ ] Document exclusion patterns

### 15.9 Performance tuning
- [ ] Benchmark scan on 50K LOC project
- [ ] Optimize bandit recursive scan
- [ ] Configure semgrep file size limits
- [ ] Implement pip-audit cache
- [ ] Set memory limit to 50MB
- [ ] Add timeout handling
- [ ] Log performance metrics

### 15.10 Documentation
- [ ] Add to manifest.yaml tools list
- [ ] Update SKILL.md security section
- [ ] Document custom rule creation
- [ ] Add suppression guidelines
- [ ] Write SARIF integration docs
- [ ] Add CI setup instructions
- [ ] Create security findings playbook

### 15.11 Atomicity
- [ ] Use tempfiles for all writes
- [ ] Track all created files
- [ ] Implement rollback on failure
- [ ] Verify file permissions
- [ ] Check disk space before write
- [ ] Validate UTF-8 encoding
- [ ] Preserve original file modes

### 15.12 Verification
- [ ] Run ast.parse on all modified files
- [ ] Execute all 30 test cases
- [ ] Verify SARIF schema compliance
- [ ] Check idempotency on re-run
- [ ] Audit memory usage
- [ ] Validate exit codes
- [ ] Test offline mode

### 15.13 Reporting
- [ ] Implement console output formatter
- [ ] Add GitHub PR annotation format
- [ ] Create HTML report option
- [ ] Include scan duration metrics
- [ ] Add rule documentation links
- [ ] Implement --quiet mode
- [ ] Add --verbose debug output

## 16. Documentation Output

```json
{
  "status": "success",
  "files_created": [
    ".bandit",
    ".semgrep/fastapi/security.yml",
    "scripts/security_scan.py",
    "scripts/sarif_generator.py",
    ".github/workflows/security-scan.yml",
    "tests/test_security_scan.py",
    ".semgrepignore",
    ".pip-audit.cfg"
  ],
  "files_modified": [
    "pyproject.toml",
    ".gitignore",
    "README.md"
  ],
  "metrics": {
    "execution_time_ms": 3821,
    "files_changed": 11,
    "lines_added": 874,
    "lines_removed": 12,
    "rules_installed": 23,
    "default_exclusions": 8
  },
  "next_steps": [
    "Run: python scripts/security_scan.py --fail-on=high",
    "Check: security-results.sarif for initial findings",
    "Commit: .bandit and .semgrep to version control",
    "Push: Changes to trigger CI security scan",
    "Review: GitHub Security tab for findings"
  ],
  "warnings": [
    "5 high severity findings detected - review before merging",
    "Custom rules in .semgrep/fastapi require periodic updates"
  ],
  "notes": [
    "Security scan configured with fail_on=high threshold",
    "23 security rules installed (6 bandit, 12 semgrep, 5 pip-audit)",
    "SARIF reporting enabled for GitHub integration",
    "Nightly scans scheduled via GitHub Actions",
    "Test coverage includes 30 verification scenarios"
  ]
}
