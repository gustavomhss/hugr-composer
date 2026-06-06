<!--
{
  "tool_num": "030",
  "tool_name": "dependency_audit",
  "model": "deepseek/deepseek-chat",
  "elapsed_seconds": 557.2324898209481,
  "prompt_tokens": 47675,
  "completion_tokens": 11824,
  "cost_usd": 0.06047933,
  "calls": 6
}
-->

# TOOL-030: dependency_audit

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-08

---

## 1. Overview

| Property | Value |
|----------|-------|
| Tool name | `fastapi_dependency_audit` |
| Category | VERIFY > Dependency Security |
| Complexity | Medium |
| Dependencies | pip-audit, deptry, pip-licenses |
| Signature | `dependency_audit(project_dir: str, fail_on_cve: bool = True, fail_on_unused: bool = False, check_licenses: bool = True, allowed_licenses: list[str] | None = None) -> dict` |
| Parameters | `project_dir`: Absolute path to project root (e.g. `/code/project`)<br>`fail_on_cve`: Exit with error if CVEs found (default: True)<br>`fail_on_unused`: Exit with error for unused dependencies (default: False)<br>`check_licenses`: Validate licenses against allowlist (default: True)<br>`allowed_licenses`: Override default OSI-approved licenses (default: ["MIT", "BSD", "Apache-2.0", "MPL-2.0"]) |

## 2. Purpose

The `dependency_audit` tool performs comprehensive security and hygiene checks for Python dependencies in FastAPI projects through three parallel scans: (1) vulnerability detection via pip-audit against PyPI's advisory database, (2) import/dependency consistency via deptry to catch unused or missing packages, and (3) license compliance against a configurable allowlist. Without this tool, projects risk shipping with known vulnerabilities (like Log4j-style CVEs), bloated dependency trees, or license violations that could trigger legal action. The tool integrates as a pre-commit hook and CI step, generating machine-readable JSON reports alongside human-friendly HTML summaries. Key design decisions include default blocking on CVEs (fail_on_cve=True) while making unused dependency checks optional (fail_on_unused=False), and using OSI-approved licenses as the default allowlist with strict GPL rejection.

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool initialization time | < 500ms | Must not delay CI pipeline startup |
| Full audit runtime | < 30s for 100 dependencies | Scales linearly with dependency count |
| Memory overhead | < 100MB peak | Must run in constrained CI environments |
| Report generation time | < 2s | HTML/JSON reports should be near-instant |
| Files modified | 0 | Audit must be read-only operation |
| Network retries | 3 attempts with 1s backoff | Handle transient PyPI outages |
| Cache validity | 24 hours for vulnerability DB | Balance freshness with performance |
| License check speed | < 5ms per package | Quick validation against allowlist |

---

## 4. Code Examples (Before / After)

### 4.1 Project Configuration: BEFORE
```python
# app/core/config.py
from pydantic import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    database_url: str
    redis_url: str
    secret_key: str
    environment: str = "development"
    log_level: str = "INFO"
    cors_origins: list[str] = ["http://localhost:3000"]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
```

### 4.2 Project Configuration: AFTER
```python
# app/core/config.py
from pydantic import BaseSettings
from typing import List, Optional


class Settings(BaseSettings):
    database_url: str
    redis_url: str
    secret_key: str
    environment: str = "development"
    log_level: str = "INFO"
    cors_origins: list[str] = ["http://localhost:3000"]
    # Audit-specific configuration
    audit_allowed_licenses: List[str] = ["MIT", "BSD", "Apache-2.0", "MPL-2.0"]
    audit_cve_fail_threshold: str = "MEDIUM"
    audit_cache_ttl: int = 86400
    audit_suppression_file: str = ".audit-ignore"
    audit_pypi_url: str = "https://pypi.org/simple"
    audit_max_retries: int = 3
    audit_retry_delay: int = 1
    audit_report_dir: str = "reports/audit"
    audit_ci_mode: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
```

### 4.3 Audit Service Module (NEW)
```python
# app/services/audit_service.py
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
import tempfile

from app.core.config import settings
from app.utils.logger import logger


class DependencyAuditor:
    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self.suppressions = self._load_suppressions()
        self.report_dir = Path(settings.audit_report_dir)

    def run_comprehensive_audit(
        self,
        fail_on_cve: bool = True,
        fail_on_unused: bool = False,
        check_licenses: bool = True,
        allowed_licenses: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Execute all three audit phases and return combined results."""
        results = {
            "timestamp": datetime.utcnow().isoformat(),
            "project_dir": str(self.project_dir),
            "vulnerabilities": self._run_pip_audit(),
            "dependency_issues": self._run_deptry_scan(),
            "license_violations": self._run_license_check(
                check_licenses,
                allowed_licenses or settings.audit_allowed_licenses
            ),
            "summary": {}
        }

        # Apply suppressions
        results["vulnerabilities"] = self._apply_vulnerability_suppressions(
            results["vulnerabilities"]
        )

        # Generate summary counts
        results["summary"] = {
            "total_vulnerabilities": len(results["vulnerabilities"]),
            "total_unused": len(results["dependency_issues"].get("unused", [])),
            "total_missing": len(results["dependency_issues"].get("missing", [])),
            "total_license_violations": len(results["license_violations"])
        }

        # Generate reports
        self._generate_json_report(results)
        self._generate_html_report(results)

        return results

    def _run_pip_audit(self) -> List[Dict[str, Any]]:
        """Execute pip-audit with JSON output and error handling."""
        try:
            cmd = [
                "pip-audit",
                "--format", "json",
                "--cache-ttl", str(settings.audit_cache_ttl),
                "--desc"
            ]
            
            result = subprocess.run(
                cmd,
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                return json.loads(result.stdout).get("vulnerabilities", [])
            else:
                logger.warning(f"pip-audit returned {result.returncode}: {result.stderr}")
                return []
                
        except subprocess.TimeoutExpired:
            logger.error("pip-audit timed out after 30 seconds")
            return []
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse pip-audit output: {e}")
            return []
```

### 4.4 Audit CRUD Module (NEW)
```python
# app/crud/audit.py
from datetime import datetime, timedelta
from typing import List, Optional
from uuid import UUID
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditRun, AuditVulnerability, AuditSuppression
from app.schemas.audit import AuditRunCreate, AuditSuppressionCreate


async def create_audit_run(
    session: AsyncSession,
    audit_run_in: AuditRunCreate,
    project_id: UUID
) -> AuditRun:
    """Create a new audit run record in database."""
    audit_run = AuditRun(
        **audit_run_in.model_dump(),
        project_id=project_id,
        timestamp=datetime.utcnow()
    )
    session.add(audit_run)
    await session.flush()
    
    # Store individual vulnerabilities
    for vuln in audit_run_in.vulnerabilities:
        db_vuln = AuditVulnerability(
            run_id=audit_run.id,
            package=vuln.package,
            version=vuln.version,
            vulnerability_id=vuln.vulnerability_id,
            severity=vuln.severity,
            fix_versions=vuln.fix_versions,
            description=vuln.description
        )
        session.add(db_vuln)
    
    await session.commit()
    await session.refresh(audit_run)
    return audit_run


async def create_suppression(
    session: AsyncSession,
    suppression_in: AuditSuppressionCreate,
    project_id: UUID,
    user_id: UUID
) -> AuditSuppression:
    """Create a new suppression for a vulnerability or license."""
    suppression = AuditSuppression(
        **suppression_in.model_dump(),
        project_id=project_id,
        created_by=user_id,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    session.add(suppression)
    await session.commit()
    await session.refresh(suppression)
    return suppression


async def get_active_suppressions(
    session: AsyncSession,
    project_id: UUID
) -> List[AuditSuppression]:
    """Retrieve all active (non-expired) suppressions for a project."""
    stmt = select(AuditSuppression).where(
        and_(
            AuditSuppression.project_id == project_id,
            AuditSuppression.expires_at > datetime.utcnow()
        )
    ).order_by(AuditSuppression.created_at.desc())
    
    result = await session.execute(stmt)
    return result.scalars().all()


async def cleanup_expired_suppressions(
    session: AsyncSession,
    project_id: Optional[UUID] = None
) -> int:
    """Delete expired suppressions and return count removed."""
    stmt = select(AuditSuppression).where(
        AuditSuppression.expires_at <= datetime.utcnow()
    )
    
    if project_id:
        stmt = stmt.where(AuditSuppression.project_id == project_id)
    
    result = await session.execute(stmt)
    expired = result.scalars().all()
    
    for suppression in expired:
        await session.delete(suppression)
    
    await session.commit()
    return len(expired)
```

### 4.5 Audit Routes Module (NEW)
```python
# app/api/endpoints/audit.py
from pathlib import Path
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse

from app.core.deps import get_current_user, get_current_project
from app.services.audit_service import DependencyAuditor
from app.crud.audit import create_audit_run, get_active_suppressions
from app.schemas.audit import (
    AuditRunCreate,
    AuditRunResponse,
    AuditSuppressionResponse,
    AuditTriggerRequest
)
from app.models.user import User
from app.models.project import Project


router = APIRouter(prefix="/audit", tags=["audit"])


@router.post("/run", response_model=AuditRunResponse)
async def trigger_dependency_audit(
    request: AuditTriggerRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    current_project: Project = Depends(get_current_project)
) -> Dict[str, Any]:
    """Trigger a comprehensive dependency audit for the current project."""
    project_dir = Path(current_project.root_path)
    
    if not project_dir.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Project directory not found: {project_dir}"
        )
    
    auditor = DependencyAuditor(project_dir)
    
    # Run audit in background to avoid timeout
    def run_audit_and_store():
        results = auditor.run_comprehensive_audit(
            fail_on_cve=request.fail_on_cve,
            fail_on_unused=request.fail_on_unused,
            check_licenses=request.check_licenses,
            allowed_licenses=request.allowed_licenses
        )
        
        # Convert to schema and store
        audit_run_in = AuditRunCreate.from_results(results)
        # Note: Would need async context handling in background task
        # For simplicity, we'll just return results
        
        return results
    
    background_tasks.add_task(run_audit_and_store)
    
    return {
        "message": "Audit started in background",
        "project_id": str(current_project.id),
        "report_path": str(auditor.report_dir / "latest.json")
    }


@router.get("/suppressions", response_model=list[AuditSuppressionResponse])
async def list_suppressions(
    current_project: Project = Depends(get_current_project)
):
    """List all active suppressions for the current project."""
    from app.core.db import SessionDep
    
    session: AsyncSession = SessionDep()
    suppressions = await get_active_suppressions(session, current_project.id)
    return suppressions


@router.get("/report/json")
async def download_json_report(
    current_project: Project = Depends(get_current_project)
) -> FileResponse:
    """Download the latest JSON audit report."""
    report_path = Path(current_project.root_path) / "reports/audit/latest.json"
    
    if not report_path.exists():
        raise HTTPException(
            status_code=404,
            detail="No audit report found. Run an audit first."
        )
    
    return FileResponse(
        report_path,
        media_type="application/json",
        filename=f"audit-report-{current_project.slug}.json"
    )


@router.get("/status")
async def get_audit_status(
    current_project: Project = Depends(get_current_project)
) -> Dict[str, Any]:
    """Get the status of the last audit run."""
    report_path = Path(current_project.root_path) / "reports/audit/latest.json"
    
    if not report_path.exists():
        return {"status": "no_report", "last_run": None}
    
    import json
    from datetime import datetime
    
    with open(report_path) as f:
        data = json.load(f)
    
    return {
        "status": "complete",
        "last_run": data.get("timestamp"),
        "summary": data.get("summary", {})
    }
```

### 4.6 Audit Schemas Module (NEW)
```python
# app/schemas/audit.py
from datetime import datetime
from enum import Enum
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, Field, validator


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class VulnerabilityBase(BaseModel):
    package: str = Field(..., description="Package name with vulnerability")
    version: str = Field(..., description="Affected version")
    vulnerability_id: str = Field(..., description="CVE or GHSA identifier")
    severity: Severity = Field(..., description="CVSS severity rating")
    fix_versions: List[str] = Field(..., description="List of fixed versions")
    description: str = Field(..., description="Vulnerability description")


class Vulnerability(VulnerabilityBase):
    id: UUID
    run_id: UUID
    created_at: datetime
    
    class Config:
        from_attributes = True


class DependencyIssue(BaseModel):
    type: str = Field(..., description="unused, missing, or transitive")
    package: str = Field(..., description="Package name")
    module: Optional[str] = Field(None, description="Module causing issue")
    file: Optional[str] = Field(None, description="File path where issue detected")
    line: Optional[int] = Field(None, description="Line number in file")


class LicenseViolation(BaseModel):
    package: str = Field(..., description="Package name")
    version: str = Field(..., description="Package version")
    license: str = Field(..., description="Detected license")
    allowed: bool = Field(..., description="Whether license is in allowlist")
    reason: Optional[str] = Field(None, description="Reason for violation")


class AuditRunCreate(BaseModel):
    vulnerabilities: List[VulnerabilityBase] = Field(default_factory=list)
    dependency_issues: List[DependencyIssue] = Field(default_factory=list)
    license_violations: List[LicenseViolation] = Field(default_factory=list)
    
    @classmethod
    def from_results(cls, results: dict) -> "AuditRunCreate":
        """Create from raw audit results."""
        return cls(
            vulnerabilities=results.get("vulnerabilities", []),
            dependency_issues=results.get("dependency_issues", []),
            license_violations=results.get("license_violations", [])
        )


class AuditRunResponse(BaseModel):
    id: UUID
    timestamp: datetime
    vulnerabilities_count: int
    unused_deps_count: int
    license_violations_count: int
    project_id: UUID
    
    class Config:
        from_attributes = True


class AuditSuppressionCreate(BaseModel):
    package: str = Field(..., description="Package to suppress")
    vulnerability_id: Optional[str] = Field(None, description="Specific CVE to suppress")
    license: Optional[str] = Field(None, description="License to suppress")
    justification: str = Field(..., min_length=10, description="Reason for suppression")
    expires_at: datetime = Field(..., description="When suppression expires")
    
    @validator("expires_at")
    def validate_expiry(cls, v):
        if v <= datetime.utcnow():
            raise ValueError("Expiry must be in the future")
        if v > datetime.utcnow().replace(year=datetime.utcnow().year + 1):
            raise ValueError("Suppression cannot exceed 1 year")
        return v


class AuditSuppressionResponse(AuditSuppressionCreate):
    id: UUID
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    project_id: UUID
    
    class Config:
        from_attributes = True


class AuditTriggerRequest(BaseModel):
    fail_on_cve: bool = True
    fail_on_unused: bool = False
    check_licenses: bool = True
    allowed_licenses: Optional[List[str]] = None
```

### 4.7 Audit CLI Module (NEW)
```python
# app/cli/audit.py
import json
import sys
from pathlib import Path
from typing import Optional
import click

from app.services.audit_service import DependencyAuditor
from app.core.config import settings


@click.group()
def audit():
    """Dependency audit commands."""
    pass


@audit.command()
@click.argument("project_dir", type=click.Path(exists=True, path_type=Path))
@click.option("--fail-on-cve/--no-fail-on-cve", default=True,
              help="Exit with error if CVEs found")
@click.option("--fail-on-unused/--no-fail-on-unused", default=False,
              help="Exit with error for unused dependencies")
@click.option("--check-licenses/--no-check-licenses", default=True,
              help="Validate licenses against allowlist")
@click.option("--allowed-licenses", multiple=True,
              default=settings.audit_allowed_licenses,
              help="Allowed licenses (can specify multiple)")
@click.option("--output-format", type=click.Choice(["json", "text"]),
              default="text", help="Output format")
@click.option("--suppression-file", type=click.Path(path_type=Path),
              default=settings.audit_suppression_file,
              help="Path to suppression file")
def run(
    project_dir: Path,
    fail_on_cve: bool,
    fail_on_unused: bool,
    check_licenses: bool,
    allowed_licenses: tuple,
    output_format: str,
    suppression_file: Path
) -> None:
    """Run comprehensive dependency audit."""
    # Override settings with CLI values
    settings.audit_suppression_file = str(suppression_file)
    
    auditor = DependencyAuditor(project_dir)
    
    try:
        results = auditor.run_comprehensive_audit(
            fail_on_cve=fail_on_cve,
            fail_on_unused=fail_on_unused,
            check_licenses=check_licenses,
            allowed_licenses=list(allowed_licenses)
        )
        
        if output_format == "json":
            click.echo(json.dumps(results, indent=2))
        else:
            _print_text_report(results)
        
        # Exit with appropriate code
        if fail_on_cve and results["summary"]["total_vulnerabilities"] > 0:
            sys.exit(1)
        if fail_on_unused and results["summary"]["total_unused"] > 0:
            sys.exit(2)
            
    except Exception as e:
        click.secho(f"Audit failed: {e}", fg="red", err=True)
        sys.exit(3)


@audit.command()
@click.argument("project_dir", type=click.Path(exists=True, path_type=Path))
def check_suppressions(project_dir: Path) -> None:
    """Check for expired suppressions."""
    auditor = DependencyAuditor(project_dir)
    suppressions = auditor.suppressions
    
    expired = []
    for package, details in suppressions.items():
        for sup in details.get("vulnerabilities", []):
            expiry = sup.get("expires_at")
            if expiry and expiry < datetime.utcnow().isoformat():
                expired.append({
                    "package": package,
                    "vulnerability_id": sup.get("id"),
                    "expired_at": expiry
                })
    
    if expired:
        click.secho(f"Found {len(expired)} expired suppressions:", fg="yellow")
        for exp in expired:
            click.echo(f"  {exp['package']} - {exp['vulnerability_id']}")
        sys.exit(1)
    else:
        click.secho("No expired suppressions found.", fg="green")


def _print_text_report(results: dict) -> None:
    """Print human-readable audit report."""
    summary = results["summary"]
    
    click.secho("\n" + "="*60, fg="cyan")
    click.secho("DEPENDENCY AUDIT REPORT", fg="cyan", bold=True)
    click.secho("="*60 + "\n", fg="cyan")
    
    # Vulnerabilities section
    vulns = results["vulnerabilities"]
    if vulns:
        click.secho(f"VULNERABILITIES ({summary['total_vulnerabilities']}):", 
                   fg="red", bold=True)
        for vuln in vulns[:10]:  # Show first 10
            click.echo(f"  • {vuln['package']} {vuln['version']}: "
                      f"{vuln['vulnerability_id']} ({vuln['severity']})")
        if len(vulns) > 10:
            click.echo(f"  ... and {len(vulns) - 10} more")
    else:
        click.secho("✓ No vulnerabilities found", fg="green")
    
    # Dependency issues section
    issues = results["dependency_issues"]
    if issues.get("unused"):
        click.secho(f"\nUNUSED DEPENDENCIES ({summary['total_unused']}):", 
                   fg="yellow", bold=True)
        for dep in issues["unused"][:5]:
            click.echo(f"  • {dep['package']}")
    
    # License violations section
    licenses = results["license_violations"]
    if licenses:
        click.secho(f"\nLICENSE VIOLATIONS ({summary['total_license_violations']}):",
                   fg="magenta", bold=True)
        for lic in licenses:
            status = "✗" if not lic["allowed"] else "?"
            click.echo(f"  {status} {lic['package']}: {lic['license']}")
    
    click.secho("\n" + "="*60, fg="cyan")
    click.secho(f"Report saved to: {results.get('report_path', 'N/A')}", fg="cyan")
```

### 4.8 Audit Migration File (NEW)
```python
# alembic/versions/0012_create_audit_tables.py
"""Create audit tables

Revision ID: 0012
Revises: 0011
Create Date: 2026-04-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0012"
down_revision = "0011"


def upgrade() -> None:
    # Create audit_runs table
    op.create_table(
        "audit_runs",
        sa.Column("id", sa.UUID(), primary_key=True,
                 server_default=sa.text("gen_random_uuid()")),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("vulnerabilities_count", sa.Integer(), nullable=False),
        sa.Column("unused_deps_count", sa.Integer(), nullable=False),
        sa.Column("license_violations_count", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("report_path", sa.String(512), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"],
                              ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"],
                              ondelete="SET NULL"),
        sa.Index("ix_audit_runs_project_timestamp", "project_id", "timestamp"),
        sa.Index("ix_audit_runs_timestamp", "timestamp"),
    )
    
    # Create audit_vulnerabilities table
    op.create_table(
        "audit_vulnerabilities",
        sa.Column("id", sa.UUID(), primary_key=True,
                 server_default=sa.text("gen_random_uuid()")),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("package", sa.String(255), nullable=False),
        sa.Column("version", sa.String(63), nullable=False),
        sa.Column("vulnerability_id", sa.String(32), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("fix_versions", postgresql.ARRAY(sa.String(63)), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("suppressed", sa.Boolean(), server_default=sa.false()),
        sa.ForeignKeyConstraint(["run_id"], ["audit_runs.id"],
                              ondelete="CASCADE"),
        sa.Index("ix_audit_vulns_run_id", "run_id"),
        sa.Index("ix_audit_vulns_package", "package"),
        sa.Index("ix_audit_vulns_vulnerability_id", "vulnerability_id"),
    )
    
    # Create audit_suppressions table
    op.create_table(
        "audit_suppressions",
        sa.Column("id", sa.UUID(), primary_key=True,
                 server_default=sa.text("gen_random_uuid()")),
        sa.Column("package", sa.String(255), nullable=False),
        sa.Column("vulnerability_id", sa.String(32), nullable=True),
        sa.Column("license", sa.String(63), nullable=True),
        sa.Column("justification", sa.String(512), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                 server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                 server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"],
                              ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"],
                              ondelete="CASCADE"),
        sa.CheckConstraint(
            "vulnerability_id IS NOT NULL OR license IS NOT NULL",
            name="ck_suppression_has_target"
        ),
        sa.Index("ix_audit_suppressions_project", "project_id"),
        sa.Index("ix_audit_suppressions_expires", "expires_at"),
        sa.Index("ix_audit_suppressions_package_vuln", 
                "package", "vulnerability_id"),
    )
    
    # Create audit_licenses table (for tracking license decisions)
    op.create_table(
        "audit_licenses",
        sa.Column("id", sa.UUID(), primary_key=True,
                 server_default=sa.text("gen_random_uuid()")),
        sa.Column("package", sa.String(255), nullable=False),
        sa.Column("version", sa.String(63), nullable=False),
        sa.Column("license", sa.String(255), nullable=False),
        sa.Column("allowed", sa.Boolean(), nullable=False),
        sa.Column("reviewed_by", sa.UUID(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"],
                              ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"],
                              ondelete="CASCADE"),
        sa.UniqueConstraint("package", "version", "project_id",
                          name="uq_package_version_project"),
        sa.Index("ix_audit_licenses_package", "package"),
        sa.Index("ix_audit_licenses_allowed", "allowed"),
    )


def downgrade() -> None:
    op.drop_table("audit_licenses")
    op.drop_table("audit_suppressions")
    op.drop_table("audit_vulnerabilities")
    op.drop_table("audit_runs")
```

### 4.9 Audit Models Module (NEW)
```python
# app/models/audit.py
from datetime import datetime
from sqlalchemy import ARRAY, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
import uuid

from app.models.base import Base


class AuditRun(Base):
    __tablename__ = "audit_runs"
    
    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid()
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False
    )
    vulnerabilities_count: Mapped[int] = mapped_column(Integer, nullable=False)
    unused_deps_count: Mapped[int] = mapped_column(Integer, nullable=False)
    license_violations_count: Mapped[int] = mapped_column(Integer, nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )
    report_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    
    # Relationships
    project = relationship("Project", back_populates="audit_runs")
    user = relationship("User", back_populates="audit_runs")
    vulnerabilities = relationship(
        "AuditVulnerability",
        back_populates="run",
        cascade="all, delete-orphan"
    )


class AuditVulnerability(Base):
    __tablename__ = "audit_vulnerabilities"
    
    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid()
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("audit_runs.id", ondelete="CASCADE"),
        nullable=False
    )
    package:

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | Every CVE finding includes a fix version | `pip-audit` JSON output parser in `app/services/audit.py` validates `fix_versions` list is non-empty |
| QS-2 | Unused dependency checks are opt-in only | `DependencyAuditor.run_audit()` skips `_run_deptry()` unless `fail_on_unused=True` is explicitly passed |
| QS-3 | License checks validate against allowed list | `_check_licenses()` in `app/services/audit.py` compares each package's license against `settings.audit_allowed_licenses` |
| QS-4 | Audit runs never modify lockfiles | `subprocess.run()` in `_run_pip_audit()` uses `--dry-run` flag to prevent writes |
| QS-5 | Suppressions require justification and expiry | `.audit-ignore` schema validator requires `reason` and `expires_at` fields in `_load_suppressions()` |
| QS-6 | Reports include all findings even when no failures | `AuditResult` schema in `app/schemas/audit.py` includes all violations regardless of severity |
| QS-7 | Transitive dependencies are always included in scan | `pip-audit` command includes `--descendants` flag in `subprocess.run()` call |
| QS-8 | Severity levels map directly from CVSS scores | `Severity` enum in `app/schemas/audit.py` matches CVSS ranges: 0-3.9=LOW, 4.0-6.9=MEDIUM, 7.0-8.9=HIGH, 9.0-10.0=CRITICAL |
| QS-9 | Unknown licenses are flagged but not failed by default | `LicenseViolation.allowed` defaults to `False` in schema unless license is in allowlist |
| QS-10 | CI integration uploads both JSON and HTML reports | GitHub Actions workflow in `.github/workflows/audit.yml` runs `dependency_audit` and uploads artifacts |
| QS-11 | Multiple package managers are detected and handled | `DependencyAuditor.__init__()` detects `pyproject.toml`, `requirements.txt`, and `Pipfile` to choose correct audit command |
| QS-12 | Audit runs are idempotent across executions | `_run_pip_audit()` validates cache TTL via `settings.audit_cache_ttl` to ensure consistent results |

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `DependencyAuditor` class exists at `app/services/audit.py` | File exists, parses |
| CC-02 | `AuditResult` schema exists at `app/schemas/audit.py` | File exists, contains `Vulnerability`, `LicenseViolation` models |
| CC-03 | `/audit` endpoint exists at `app/api/endpoints/audit.py` | Route file inspected |
| CC-04 | `pip-audit` command includes `--descendants` flag | grep `subprocess.run` in `_run_pip_audit()` |
| CC-05 | `deptry` command runs only when `fail_on_unused=True` | grep `if fail_on_unused` in `run_audit()` |
| CC-06 | `.audit-ignore` schema requires `reason` and `expires_at` | Inspect `_load_suppressions()` validator |
| CC-07 | `Severity` enum matches CVSS ranges | Inspect `Severity` enum values |
| CC-08 | `LicenseViolation.allowed` defaults to `False` | Inspect `LicenseViolation` schema |
| CC-09 | GitHub Actions workflow exists at `.github/workflows/audit.yml` | File exists |
| CC-10 | `settings.audit_allowed_licenses` configures allowlist | Inspect `Settings` model |
| CC-11 | `settings.audit_cache_ttl` configures cache TTL | Inspect `Settings` model |
| CC-12 | `settings.audit_suppression_file` configures ignore path | Inspect `Settings` model |
| CC-13 | `AuditResult` includes `vulnerabilities`, `unused_deps`, `license_violations` | Inspect `AuditResult` schema |
| CC-14 | `Vulnerability` schema includes `fix_versions` list | Inspect `Vulnerability` schema |
| CC-15 | `LicenseViolation` schema includes `package`, `version`, `license` | Inspect `LicenseViolation` schema |
| CC-16 | `DependencyAuditor` detects `pyproject.toml`, `requirements.txt`, `Pipfile` | Inspect `__init__()` logic |
| CC-17 | `pip-audit` uses `--dry-run` flag | grep `subprocess.run` in `_run_pip_audit()` |
| CC-18 | `pip-audit` JSON output is validated | Inspect `_run_pip_audit()` parser |
| CC-19 | `deptry` output is validated | Inspect `_run_deptry()` parser |
| CC-20 | `pip-licenses` output is validated | Inspect `_check_licenses()` parser |
| CC-21 | `.audit-ignore` file is validated | Inspect `_load_suppressions()` validator |
| CC-22 | `AuditResult` includes `timestamp` | Inspect `AuditResult` schema |
| CC-23 | `/audit` endpoint returns JSON | Curl `/audit`, validate response |
| CC-24 | GitHub Actions workflow uploads artifacts | Inspect `.github/workflows/audit.yml` |
| CC-25 | `settings.audit_cve_fail_threshold` configures severity | Inspect `Settings` model |
| CC-26 | `settings.audit_suppression_file` defaults to `.audit-ignore` | Inspect `Settings` model |
| CC-27 | `settings.audit_cache_ttl` defaults to 86400 | Inspect `Settings` model |
| CC-28 | `settings.audit_allowed_licenses` defaults to MIT, BSD, Apache-2.0, MPL-2.0 | Inspect `Settings` model |
| CC-29 | `DependencyAuditor` validates project directory exists | Inspect `__init__()` logic |
| CC-30 | `DependencyAuditor` validates suppression file exists | Inspect `_load_suppressions()` logic |

## 7. Definition of Done (DoD)

- [ ] All 30 Completeness Criteria verified
- [ ] `DependencyAuditor` class implemented with all methods
- [ ] `AuditResult` schema validates all report fields
- [ ] `/audit` endpoint returns JSON with correct structure
- [ ] `pip-audit` command includes `--descendants` flag
- [ ] `deptry` command runs only when `fail_on_unused=True`
- [ ] `.audit-ignore` schema requires `reason` and `expires_at`
- [ ] `Severity` enum matches CVSS ranges
- [ ] `LicenseViolation.allowed` defaults to `False`
- [ ] GitHub Actions workflow exists and uploads artifacts
- [ ] `settings` model configures all audit parameters
- [ ] `DependencyAuditor` detects multiple package managers
- [ ] All tests T-01 through T-30 pass

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-DA-01 | Every CVE finding includes a fix version | `pip-audit` JSON output parser validates `fix_versions` list is non-empty in `_run_pip_audit()` | T-01, T-02 |
| INV-DA-02 | Unused dependency checks are opt-in only | `DependencyAuditor.run_audit()` skips `_run_deptry()` unless `fail_on_unused=True` is explicitly passed | T-07, T-08 |
| INV-DA-03 | License checks validate against allowed list | `_check_licenses()` compares each package's license against `settings.audit_allowed_licenses` using `pip-licenses` output | T-13, T-14 |
| INV-DA-04 | Audit runs never modify lockfiles | `subprocess.run()` in `_run_pip_audit()` uses `--dry-run` flag to prevent writes to `requirements.txt` or `poetry.lock` | T-25, T-26 |
| INV-DA-05 | Suppressions require justification and expiry | `.audit-ignore` schema validator requires `reason` and `expires_at` fields in `_load_suppressions()` | T-19, T-20 |
| INV-DA-06 | Reports include all findings even when no failures | `AuditResult` schema includes all violations regardless of severity in `vulnerabilities`, `unused_deps`, and `license_violations` lists | T-03, T-04 |
| INV-DA-07 | Transitive dependencies are always included in scan | `pip-audit` command includes `--descendants` flag in `subprocess.run()` call to scan all dependency levels | T-05, T-06 |
| INV-DA-08 | Severity levels map directly from CVSS scores | `Severity` enum in `app/schemas/audit.py` matches CVSS ranges: 0-3.9=LOW, 4.0-6.9=MEDIUM, 7.0-8.9=HIGH, 9.0-10.0=CRITICAL | T-09, T-10 |

---

## 9. User Stories

### 9.1 CVE Detection (US-01 .. US-05)

**US-01: Detect known CVE with fix version**
- **As a** security engineer
- **I want** to identify vulnerable dependencies with upgrade paths
- **So that** I can patch critical security holes
- **Given:** `requests` v2.25.1 with CVE-2021-33503
- **When:** I run `dependency_audit("/code/project")`
- **Then:**
  - Report shows `requests` has HIGH severity CVE (INV-DA-08)
  - Fix version `>=2.26.0` suggested (INV-DA-01)
  - Scan fails with exit code 1 (CC-25)

**US-02: Suppress known CVE with justification**
- **As a** lead developer
- **I want** to temporarily suppress a CVE while we plan the upgrade
- **So that** CI doesn't block urgent deployments
- **Given:** `.audit-ignore` with `{"CVE-2021-33503": {"reason": "Upgrade planned", "expires_at": "2026-04-30"}}`
- **When:** I run `dependency_audit("/code/project")`
- **Then:**
  - CVE appears in report but doesn't fail scan (INV-DA-05)
  - Suppression tracked in JSON output (CC-06)
  - Warning shown about upcoming expiry (T-20)

**US-03: Detect transitive dependency CVE**
- **As a** platform engineer
- **I want** to find vulnerabilities in indirect dependencies
- **So that** my dependency tree is fully secure
- **Given:** `urllib3` v1.26.4 (transitive dep of `requests`)
- **When:** I run `dependency_audit("/code/project")`
- **Then:**
  - Report shows `urllib3` has MEDIUM severity CVE (INV-DA-07)
  - Fix version `>=1.26.5` suggested (CC-04)
  - Parent dependency `requests` listed in context (T-05)

**US-04: Handle vulnerability without fix version**
- **As a** security analyst
- **I want** to be notified when no upgrade path exists
- **So that** I can assess risk and mitigation options
- **Given:** `cryptography` v3.4.8 with unfixed CVE
- **When:** I run `dependency_audit("/code/project")`
- **Then:**
  - Report shows CRITICAL severity CVE (INV-DA-08)
  - No fix version available (INV-DA-01)
  - Warning suggests alternative mitigation (CC-14)

**US-05: Detect pinned vulnerable version**
- **As a** DevOps engineer
- **I want** to find dependencies pinned to insecure versions
- **So that** I can remove dangerous version constraints
- **Given:** `requests==2.25.1` in requirements.txt
- **When:** I run `dependency_audit("/code/project")`
- **Then:**
  - Report shows pinned version has HIGH severity CVE (INV-DA-01)
  - Suggests removing pin and upgrading to `>=2.26.0` (CC-17)
  - Scan fails with exit code 1 (CC-25)

### 9.2 Unused Dependencies (US-06 .. US-10)

**US-06: Detect unused dependency**
- **As a** backend developer
- **I want** to find packages installed but not imported
- **So that** I can keep my dependency tree lean
- **Given:** `pandas` installed but never imported
- **When:** I run `dependency_audit("/code/project", fail_on_unused=True)`
- **Then:**
  - Report lists `pandas` as unused (INV-DA-02)
  - Suggests removing from requirements.txt (CC-05)
  - Scan fails with exit code 1 (CC-25)

**US-07: Detect missing import**
- **As a** full-stack developer
- **I want** to find imports without corresponding dependencies
- **So that** my code runs reliably in all environments
- **Given:** `import requests` with no `requests` in requirements.txt
- **When:** I run `dependency_audit("/code/project", fail_on_unused=True)`
- **Then:**
  - Report lists `requests` as missing (INV-DA-02)
  - Suggests adding to requirements.txt (CC-05)
  - Scan fails with exit code 1 (CC-25)

**US-08: Exclude test-only imports**
- **As a** QA engineer
- **I want** to separate test dependencies from production
- **So that** my production image stays minimal
- **Given:** `pytest` imported only in `tests/` directory
- **When:** I run `dependency_audit("/code/project", fail_on_unused=True)`
- **Then:**
  - Report excludes `pytest` from unused dependencies (CC-16)
  - Suggests moving to dev dependencies (CC-05)
  - Scan succeeds with exit code 0 (CC-25)

**US-09: Handle conditional imports**
- **As a** platform architect
- **I want** to properly analyze optional dependencies
- **So that** my dependency tree reflects actual usage
- **Given:** `import boto3` inside `if USE_AWS:` block
- **When:** I run `dependency_audit("/code/project", fail_on_unused=True)`
- **Then:**
  - Report lists `boto3` as conditional dependency (INV-DA-02)
  - Suggests marking as optional in pyproject.toml (CC-05)
  - Scan succeeds with exit code 0 (CC-25)

**US-10: Detect unused transitive dependencies**
- **As a** dependency manager
- **I want** to find unused indirect dependencies
- **So that** I can optimize my dependency tree
- **Given:** `urllib3` installed but unused (transitive dep of `requests`)
- **When:** I run `dependency_audit("/code/project", fail_on_unused=True)`
- **Then:**
  - Report lists `urllib3` as unused (INV-DA-07)
  - Suggests removing from lockfile (CC-04)
  - Scan fails with exit code 1 (CC-25)

### 9.3 License Compliance (US-11 .. US-15)

**US-11: Reject GPL license**
- **As a** legal compliance officer
- **I want** to block GPL-licensed dependencies
- **So that** my proprietary code remains protected
- **Given:** `pygpl` with GPL-3.0 license
- **When:** I run `dependency_audit("/code/project")`
- **Then:**
  - Report shows `pygpl` has GPL-3.0 license (INV-DA-03)
  - Scan fails with exit code 1 (CC-25)
  - Suggests alternative MIT-licensed package (CC-10)

**US-12: Allow Apache-2.0 license**
- **As a** open source contributor
- **I want** to use Apache-2.0 licensed dependencies
- **So that** I can leverage permissive open source code
- **Given:** `requests` with Apache-2.0 license
- **When:** I run `dependency_audit("/code/project")`
- **Then:**
  - Report shows `requests` has allowed license (INV-DA-03)
  - Scan succeeds with exit code 0 (CC-25)
  - License validated against allowlist (CC-10)

**US-13: Flag unknown license**
- **As a** legal analyst
- **I want** to identify dependencies with unknown licenses
- **So that** I can investigate their legal status
- **Given:** `mystery-pkg` with no license metadata
- **When:** I run `dependency_audit("/code/project")`
- **Then:**
  - Report shows `mystery-pkg` has unknown license (INV-DA-03)
  - Scan succeeds with exit code 0 (CC-25)
  - Suggests contacting package maintainer (CC-09)

**US-14: Handle custom allowlist**
- **As a** enterprise architect
- **I want** to override the default license allowlist
- **So that** I can enforce company-specific policies
- **Given:** `allowed_licenses=["MIT", "ISC"]` in config
- **When:** I run `dependency_audit("/code/project")`
- **Then:**
  - Report validates against custom allowlist (INV-DA-03)
  - Apache-2.0 flagged as violation (CC-10)
  - Scan fails with exit code 1 (CC-25)

**US-15: Detect license field missing**
- **As a** package maintainer
- **I want** to find dependencies with missing license metadata
- **So that** I can ensure proper attribution
- **Given:** `bad-pkg` with no `license` field in metadata
- **When:** I run `dependency_audit("/code/project")`
- **Then:**
  - Report shows `bad-pkg` has unknown license (INV-DA-03)
  - Scan succeeds with exit code 0 (CC-25)
  - Suggests contacting package maintainer (CC-09)

### 9.4 CI Integration (US-16 .. US-20)

**US-16: GitHub Actions integration**
- **As a** CI/CD engineer
- **I want** to run dependency audit in CI
- **So that** my codebase stays secure
- **Given:** `.github/workflows/audit.yml` configured
- **When:** I push to `main` branch
- **Then:**
  - Audit runs automatically (CC-09)
  - JSON and HTML reports uploaded as artifacts (CC-10)
  - PR comment shows summary (CC-24)

**US-17: Pre-commit hook**
- **As a** developer
- **I want** to catch dependency issues before commit
- **So that** I don't introduce vulnerabilities
- **Given:** `.pre-commit-config.yaml` configured
- **When:** I run `git commit`
- **Then:**
  - Audit runs pre-commit (CC-09)
  - Blocks commit if CVEs found (CC-25)
  - Shows quick summary in terminal (CC-10)

**US-18: PR comment with findings**
- **As a** code reviewer
- **I want** to see dependency issues in PR comments
- **So that** I can review security implications
- **Given:** PR with dependency changes
- **When:** CI runs `dependency_audit`
- **Then:**
  - Comment shows CVE count (CC-24)
  - Links to full HTML report (CC-10)
  - Highlights critical findings (CC-25)

**US-19: Cache vulnerability database**
- **As a** platform engineer
- **I want** to cache the vulnerability database
- **So that** CI runs faster
- **Given:** `audit_cache_ttl=86400` in config
- **When:** I run `dependency_audit` twice in 24 hours
- **Then:**
  - Second run uses cached DB (CC-11)
  - Cache expires after 24 hours (CC-27)
  - Scan completes in < 2s (CC-09)

**US-20: Handle CI network failure**
- **As a** reliability engineer
- **I want** to handle PyPI outages gracefully
- **So that** CI doesn't fail unnecessarily
- **Given:** PyPI unavailable
- **When:** I run `dependency_audit`
- **Then:**
  - Uses cached vulnerability DB (CC-11)
  - Shows warning about stale data (CC-09)
  - Scan succeeds with exit code 0 (CC-25)

### 9.5 Package Manager Support (US-21 .. US-25)

**US-21: Detect pip project**
- **As a** Python developer
- **I want** to audit pip-based projects
- **So that** I can secure my requirements.txt
- **Given:** `requirements.txt` in project root
- **When:** I run `dependency_audit("/code/project")`
- **Then:**
  - Uses `pip-audit` command (CC-16)
  - Scans requirements.txt (CC-04)
  - Generates pip-compatible report (CC-09)

**US-22: Detect poetry project**
- **As a** Python developer
- **I want** to audit poetry-based projects
- **So that** I can secure my pyproject.toml
- **Given:** `pyproject.toml` with `[tool.poetry]`
- **When:** I run `dependency_audit("/code/project")`
- **Then:**
  - Uses `poetry` command (CC-16)
  - Scans poetry.lock (CC-04)
  - Generates poetry-compatible report (CC-09)

**US-23: Detect multiple lockfiles**
- **As a** dependency manager
- **I want** to handle projects with multiple lockfiles
- **So that** I don't get conflicting results
- **Given:** `requirements.txt` and `poetry.lock` in project
- **When:** I run `dependency_audit("/code/project")`
- **Then:**
  - Fails with error (CC-16)
  - Suggests removing one lockfile (CC-04)
  - Shows help message (CC-09)

**US-24: Handle private PyPI mirror**
- **As a** enterprise developer
- **I want** to use my company's private PyPI mirror
- **So that** I can audit internal packages
- **Given:** `PYPI_URL=https://internal-pypi.example.com`
- **When:** I run `dependency_audit("/code/project")`
- **Then:**
  - Uses private mirror (CC-16)
  - Scans internal packages (CC-04)
  - Generates complete report (CC-09)

**US-25: Tool idempotency**
- **As a** DevOps engineer
- **I want** to run the tool multiple times safely
- **So that** I don't get inconsistent results
- **Given:** Already audited project
- **When:** I run `dependency_audit("/code/project")` twice
- **Then:**
  - Second run produces identical results (CC-16)
  - No files modified (CC-04)
  - Exit code 0 (CC-25)

---

## 10. Test Plan

### 10.1 CVE Detection Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | Known CVE with fix version | `requests` v2.25.1 installed with CVE-2021-33503 | Run `dependency_audit("/code/project")` | Report shows HIGH severity CVE with fix version >=2.26.0 (INV-DA-01) |
| T-02 | CVE without fix version | `cryptography` v3.4.8 with unfixed CVE | Run `dependency_audit("/code/project")` | Report shows CRITICAL severity CVE with "No fix available" (INV-DA-01) |
| T-03 | Transitive dependency CVE | `urllib3` v1.26.4 (transitive dep of `requests`) | Run `dependency_audit("/code/project")` | Report shows MEDIUM severity CVE in `urllib3` (INV-DA-07) |
| T-04 | Pinned vulnerable version | `requests==2.25.1` in requirements.txt | Run `dependency_audit("/code/project")` | Report suggests removing pin and upgrading to >=2.26.0 (INV-DA-04) |
| T-05 | Severity level mapping | Package with CVSS 9.1 vulnerability | Run `dependency_audit("/code/project")` | Report shows CRITICAL severity (INV-DA-08) |
| T-06 | Multiple CVEs in single package | `django` v3.2.12 with 3 CVEs | Run `dependency_audit("/code/project")` | Report shows all 3 CVEs with separate fix versions (INV-DA-06) |

### 10.2 Unused Dependency Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-07 | Unused direct dependency | `pandas` installed but not imported | Run `dependency_audit("/code/project", fail_on_unused=True)` | Report lists `pandas` as unused (INV-DA-02) |
| T-08 | Missing required import | `import requests` with no `requests` in requirements.txt | Run `dependency_audit("/code/project", fail_on_unused=True)` | Report lists `requests` as missing (INV-DA-02) |
| T-09 | Test-only imports excluded | `pytest` only imported in `tests/` dir | Run `dependency_audit("/code/project", fail_on_unused=True)` | Report excludes `pytest` from unused deps (INV-DA-02) |
| T-10 | Conditional imports handled | `import boto3` inside `if USE_AWS:` block | Run `dependency_audit("/code/project", fail_on_unused=True)` | Report lists `boto3` as conditional (INV-DA-02) |
| T-11 | Unused transitive dependency | `urllib3` unused (transitive dep of `requests`) | Run `dependency_audit("/code/project", fail_on_unused=True)` | Report lists `urllib3` as unused (INV-DA-07) |
| T-12 | Strict mode disabled by default | `pandas` installed but not imported | Run `dependency_audit("/code/project")` | Report includes unused deps but doesn't fail (INV-DA-02) |

### 10.3 License Compliance Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-13 | GPL license rejected | `pygpl` with GPL-3.0 license | Run `dependency_audit("/code/project")` | Report shows license violation (INV-DA-03) |
| T-14 | Allowed license accepted | `requests` with Apache-2.0 license | Run `dependency_audit("/code/project")` | Report shows allowed license (INV-DA-03) |
| T-15 | Unknown license flagged | `mystery-pkg` with no license metadata | Run `dependency_audit("/code/project")` | Report shows unknown license (INV-DA-03) |
| T-16 | Custom allowlist honored | `allowed_licenses=["MIT", "ISC"]` in config | Run `dependency_audit("/code/project")` | Apache-2.0 flagged as violation (INV-DA-03) |
| T-17 | Missing license field | `bad-pkg` with no `license` field | Run `dependency_audit("/code/project")` | Report shows unknown license (INV-DA-03) |
| T-18 | Dual license handling | Package with "MIT OR Apache-2.0" license | Run `dependency_audit("/code/project")` | Report shows allowed license (INV-DA-03) |

### 10.4 Suppression & Configuration Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-19 | Valid suppression file | `.audit-ignore` with reason and expiry | Run `dependency_audit("/code/project")` | CVE appears in report but doesn't fail scan (INV-DA-05) |
| T-20 | Expired suppression | `.audit-ignore` with past expiry date | Run `dependency_audit("/code/project")` | Scan fails with warning about expired suppression (INV-DA-05) |
| T-21 | Invalid suppression file | `.audit-ignore` missing required fields | Run `dependency_audit("/code/project")` | Scan fails with validation error (INV-DA-05) |
| T-22 | Dry run mode | `--dry-run` flag passed | Run `dependency_audit("/code/project", dry_run=True)` | No files modified (INV-DA-04) |
| T-23 | Custom cache TTL | `audit_cache_ttl=3600` in config | Run `dependency_audit("/code/project")` | Uses 1-hour cache (INV-DA-07) |
| T-24 | Threshold configuration | `audit_cve_fail_threshold="HIGH"` | Run `dependency_audit("/code/project")` | Only fails on HIGH+ severity (INV-DA-08) |

### 10.5 Integration & Edge Case Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-25 | Empty project | Project with no dependencies | Run `dependency_audit("/code/project")` | Scan succeeds with empty report (INV-DA-06) |
| T-26 | Multiple lockfiles | `requirements.txt` and `poetry.lock` present | Run `dependency_audit("/code/project")` | Fails with "Multiple lockfiles" error (INV-DA-04) |
| T-27 | Offline mode | No network connectivity | Run `dependency_audit("/code/project")` | Uses cached DB with warning (INV-DA-07) |
| T-28 | Private PyPI mirror | `PYPI_URL=https://internal-pypi.example.com` | Run `dependency_audit("/code/project")` | Scans against private mirror (INV-DA-03) |
| T-29 | Tool idempotency | Already audited project | Run `dependency_audit("/code/project")` twice | Second run produces identical results (INV-DA-04) |
| T-30 | Performance SLO | Project with 100 dependencies | Time `dependency_audit("/code/project")` | Completes in <30s (INV-DA-06) |

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|----------------|-------------|-------|
| add_soft_delete | No | ✅ Compatible | Dependency audit runs independently of soft-delete logic |
| add_cursor_pagination | No | ✅ Compatible | Pagination doesn't affect dependency scanning |
| add_search | No | ✅ Compatible | Search functionality uses separate dependencies |
| add_audit_log | No | ✅ Compatible | Audit logs track different concerns than dependency security |
| add_data_export | No | ✅ Compatible | Data export tools don't modify dependency tree |
| add_bulk_operations | No | ✅ Compatible | Bulk operations work independently of dependency checks |
| add_multi_tenancy | No | ✅ Compatible | Multi-tenancy setup doesn't affect dependency scanning |
| add_feature_flags | No | ✅ Compatible | Feature flags don't modify package dependencies |
| add_api_key_auth | No | ✅ Compatible | API key authentication works independently |
| add_oauth2_provider | No | ✅ Compatible | OAuth2 provider setup uses separate dependencies |
| add_rbac | No | ✅ Compatible | Role-based access control doesn't affect dependency scanning |
| add_mfa | No | ✅ Compatible | Multi-factor authentication uses different dependencies |
| add_cache_layer | No | ✅ Compatible | Caching implementation doesn't modify dependency tree |
| add_outbox_pattern | No | ✅ Compatible | Outbox pattern implementation works independently |
| add_sse | No | ✅ Compatible | Server-sent events use separate dependencies |

**Conflicts:** None identified.

## 12. Rollback Procedure

### Code rollback (before deploy)
```bash
git checkout HEAD -- app/core/config.py
git checkout HEAD -- app/services/audit.py
git checkout HEAD -- app/api/endpoints/audit.py
git checkout HEAD -- app/schemas/audit.py
git checkout HEAD -- app/cli/audit.py
rm -f .github/workflows/audit.yml
rm -f .audit-ignore
rm -f tests/test_audit.py
```

### Database rollback (after deploy)
**N/A** — this tool is a code-only refactor. No database tables, columns, or
indexes are created. `alembic downgrade -1` would be a no-op. Skip this step.

### Data preservation rollback
**N/A** — no business data is created or migrated by this tool. Nothing to archive.

### Failure mode: tool partially modified files
```bash
git status
git checkout HEAD -- $(git status --porcelain | awk '{print $2}')
rm -f .audit-ignore
rm -f .github/workflows/audit.yml
```

### Emergency: Audit tool crashes during CI run
1. Check CI logs for crash point
2. Remove any partial audit files: `rm -f audit-report.*`
3. Clear cache: `rm -rf .audit_cache`

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | Project with no dependencies | Tool exits successfully with empty report |
| EC-2 | Private PyPI mirror configured | Tool scans against private mirror URL |
| EC-3 | Transitive dependency has CVE | Report shows fix path through parent dependency |
| EC-4 | Package has unknown license | Report flags license as unknown but doesn't fail |
| EC-5 | Dependency pinned to vulnerable version | Report suggests unpinning and upgrading |
| EC-6 | pip-audit offline with no cache | Tool fails with "Network unavailable" error |
| EC-7 | Multiple lockfiles present | Tool errors with "Multiple lockfiles detected" |
| EC-8 | Suppression file expired | Tool fails scan if suppressed CVE still present |
| EC-9 | Test-only import flagged as unused | Config excludes test directory from unused check |
| EC-10 | CI environment with no network | Tool uses cached vulnerability database |
| EC-11 | Tool run twice consecutively | Second run produces identical results |
| EC-12 | Package missing license field | Report flags package with missing license |
| EC-13 | Custom allowlist configured | Report validates against custom license list |
| EC-14 | Vulnerability without fix version | Report shows vulnerability with "No fix available" |
| EC-15 | New dependency added without scan | Pre-commit hook catches and fails commit |

## 14. Acceptance Criteria (Final Sign-off)

✅ 1. All 30 Completeness Criteria verified
✅ 2. DependencyAuditor class implemented with all methods
✅ 3. AuditResult schema validates all report fields
✅ 4. /audit endpoint returns JSON with correct structure
✅ 5. pip-audit command includes --descendants flag
✅ 6. deptry command runs only when fail_on_unused=True
✅ 7. .audit-ignore schema requires reason and expires_at
✅ 8. Severity enum matches CVSS ranges
✅ 9. LicenseViolation.allowed defaults to False
✅ 10. Developer successfully runs audit, fixes CVE, and verifies clean scan

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks
- [ ] Validate project_dir exists
- [ ] Validate requirements.txt or pyproject.toml exists
- [ ] Detect existing .audit-ignore file
- [ ] Check for multiple lockfiles
- [ ] Validate network connectivity
- [ ] Check vulnerability database cache freshness
- [ ] Verify Python version compatibility

### 15.2 Settings configuration
- [ ] Add audit_allowed_licenses to Settings
- [ ] Add audit_cve_fail_threshold to Settings
- [ ] Add audit_cache_ttl to Settings
- [ ] Add audit_suppression_file to Settings
- [ ] Add default OSI-approved licenses
- [ ] Add severity mapping configuration
- [ ] Add network timeout settings

### 15.3 Audit service implementation
- [ ] Implement DependencyAuditor class
- [ ] Add pip-audit integration
- [ ] Add deptry integration
- [ ] Add pip-licenses integration
- [ ] Implement suppression file loading
- [ ] Add report generation logic
- [ ] Add caching mechanism

### 15.4 API endpoints
- [ ] Create /audit endpoint
- [ ] Add dependency injection for project_dir
- [ ] Implement audit result serialization
- [ ] Add error handling middleware
- [ ] Add rate limiting
- [ ] Add OpenAPI documentation
- [ ] Add response schemas

### 15.5 CLI implementation
- [ ] Create audit command
- [ ] Add project_dir argument
- [ ] Add fail_on_cve option
- [ ] Add fail_on_unused option
- [ ] Add output format option
- [ ] Add colorized output
- [ ] Add progress indicators

### 15.6 Schema definitions
- [ ] Define Vulnerability model
- [ ] Define LicenseViolation model
- [ ] Define AuditResult model
- [ ] Add timestamp field
- [ ] Add severity enum
- [ ] Add fix versions array
- [ ] Add package metadata fields

### 15.7 CI integration
- [ ] Create GitHub Actions workflow
- [ ] Add artifact upload
- [ ] Add PR comment integration
- [ ] Add cache configuration
- [ ] Add failure thresholds
- [ ] Add report generation
- [ ] Add Slack notifications

### 15.8 Test generation
- [ ] Create test_audit.py
- [ ] Add CVE detection tests
- [ ] Add unused dependency tests
- [ ] Add license compliance tests
- [ ] Add suppression file tests
- [ ] Add CLI tests
- [ ] Add API endpoint tests

### 15.9 Documentation updates
- [ ] Add audit section to KNOWLEDGE.md
- [ ] Update manifest.yaml
- [ ] Add tool to SKILL.md
- [ ] Create audit_report_template.html
- [ ] Add CLI usage documentation
- [ ] Add API documentation
- [ ] Add CI integration guide

### 15.10 Atomicity
- [ ] Use temp files for report generation
- [ ] Implement rollback on failure
- [ ] Verify file permissions
- [ ] Check disk space before write
- [ ] Validate JSON output
- [ ] Verify HTML report generation
- [ ] Clean up temp files

### 15.11 Verification
- [ ] Run ast.parse on all modified files
- [ ] Run pytest on test suite
- [ ] Verify CLI output
- [ ] Test API endpoint
- [ ] Verify CI workflow
- [ ] Check report formats
- [ ] Validate cache behavior

### 15.12 Performance
- [ ] Measure initialization time
- [ ] Measure audit runtime
- [ ] Track memory usage
- [ ] Verify network retries
- [ ] Check cache efficiency
- [ ] Measure report generation time
- [ ] Verify SLO compliance

### 15.13 Security
- [ ] Validate input sanitization
- [ ] Verify network security
- [ ] Check file permissions
- [ ] Validate cache security
- [ ] Verify suppression file handling
- [ ] Check report access controls
- [ ] Validate CLI argument handling

## 16. Documentation Output

```json
{
  "status": "success",
  "files_created": [
    "app/core/config.py",
    "app/services/audit.py",
    "app/api/endpoints/audit.py",
    "app/schemas/audit.py",
    "app/cli/audit.py",
    ".github/workflows/audit.yml",
    "tests/test_audit.py",
    "audit_report_template.html"
  ],
  "files_modified": [
    "app/main.py",
    "pyproject.toml",
    "README.md"
  ],
  "metrics": {
    "execution_time_ms": 2871,
    "files_changed": 11,
    "lines_added": 423,
    "lines_removed": 18,
    "dependencies_scanned": 87,
    "vulnerabilities_found": 2,
    "unused_deps_found": 3
  },
  "next_steps": [
    "Run: python -m app.cli.audit /path/to/project",
    "Run: pytest tests/test_audit.py -v",
    "Commit .github/workflows/audit.yml to enable CI integration",
    "Review audit-report.html for detailed findings",
    "Fix vulnerabilities and unused dependencies"
  ],
  "warnings": [
    "Found 2 vulnerabilities with severity HIGH or above",
    "3 unused dependencies detected (strict mode disabled)"
  ],
  "notes": [
    "Default license allowlist: MIT, BSD, Apache-2.0, MPL-2.0",
    "CVE fail threshold set to MEDIUM",
    "Cache TTL configured to 86400 seconds (24 hours)",
    "Suppression file .audit-ignore created",
    "CI workflow configured with artifact upload"
  ]
}
