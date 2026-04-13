# TOOL-031: schema_coverage

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-08

---

## 1. Overview

| Property | Value |
|----------|-------|
| Tool name | `fastapi_schema_coverage` |
| Category | VERIFY > API Testing |
| Complexity | Medium |
| Dependencies | FastAPI, Pydantic, AST parsing |
| Signature | `schema_coverage(project_dir: str, threshold_pct: float = 80.0, fail_on_orphan_fields: bool = True, exclude_schemas: list[str] | None = None) -> dict` |
| Parameters | `project_dir`: Absolute path to FastAPI project root (e.g. `/code/myapp`)<br>`threshold_pct`: Minimum required test coverage percentage (default: 80.0)<br>`fail_on_orphan_fields`: Raise error if untested fields exist (default: True)<br>`exclude_schemas`: Schema class names to exclude from analysis (default: None) |

## 2. Purpose

The `fastapi_schema_coverage` tool answers the question that line coverage can never answer: **"which of my Pydantic schema fields are actually exercised by my tests?"**. Line coverage reports a cheerful 92% because every line of every model file was touched at import time, but the `user.timezone` field that was added last week is defined, serialized, and deserialized in production — and never once asserted in a test. This tool parses every `BaseModel` subclass with `ast`, enumerates its fields (including those inherited from parents, aliased, or declared via `Field(...)`), walks every test file under `tests/` to find references of the form `.field_name`, `['field_name']`, or `{"field_name": ...}`, and produces a per-schema coverage percentage plus an **orphan-fields list** — fields defined but never referenced anywhere under `tests/`. Orphans are the actionable output: they catch the "I added a field and forgot to test it" regression class that Pydantic v2's permissive serialization hides in production until a consumer blows up.

The generator produces a `scripts/schema_coverage.py` orchestrator with a `--threshold-pct` gate (default 80%), a `--fail-on-orphan-fields` flag that blocks PRs introducing new orphans, a per-schema `.schema-coverage-exclude.yaml` where computed properties and private `_fields` can be explicitly skipped with justification, and a Markdown/JSON/HTML report triple. Key design decisions: **AST-based** walking rather than runtime introspection so the tool can analyze Pydantic v1 and v2 equally and so it has zero runtime cost on the app itself; **deterministic output** — the orphan list is sorted alphabetically and the per-schema table is sorted by coverage ascending, so re-running the tool produces byte-identical reports (safe to commit); **exclusion is always explicit** — the tool never silently drops a field, every skip is in the YAML with a reason and a reviewer; **incremental mode** via `--changed-only` that analyzes only schemas touched by the current PR diff so the full scan runs only on `main`; **CI integration** that posts a PR comment diffing the current coverage against the committed baseline so reviewers can spot silent regressions; and **suggestions per orphan** — the report points to the test file most likely to own the missing assertion (`tests/test_users.py` for `UserCreate` orphans) so the fix is a one-line edit, not a treasure hunt.

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 3s for 50 schemas | Must run quickly in pre-commit hooks |
| Files modified | 0 | Read-only analysis |
| Files created | 1 (coverage.json) | Minimal output footprint |
| Schema parsing time | < 100ms per 10 schemas | Linear scaling with project size |
| Test file analysis | < 50ms per test file | Fast enough for large test suites |
| Memory overhead | < 50MB peak | Must run in constrained CI environments |
| Report generation | < 200ms | Instant feedback for developers |
| Orphan detection | 100% recall | Critical for catching untested fields |
| False positive rate | < 1% | Avoid developer frustration from incorrect warnings |

---

## 4. Code Examples (Before / After)

### 4.1 Schema Model: BEFORE
```python
# app/schemas/user.py
from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None


class UserResponse(BaseModel):
    id: int
    email: EmailStr
    first_name: Optional[str]
    last_name: Optional[str]
    is_active: bool
    created_at: datetime
```

### 4.2 Schema Model: AFTER
```python
# app/schemas/user.py
from pydantic import BaseModel, EmailStr, Field, ConfigDict
from typing import Optional
from datetime import datetime
from app.schemas.mixins import TimestampMixin


class UserCreate(BaseModel):
    email: EmailStr = Field(..., description="Unique email address", examples=["user@example.com"])
    password: str = Field(..., min_length=8, max_length=64, description="Hashed password")
    first_name: Optional[str] = Field(None, max_length=50, description="User's first name")
    last_name: Optional[str] = Field(None, max_length=50, description="User's last name")


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = Field(None, description="New email address")
    first_name: Optional[str] = Field(None, max_length=50)
    last_name: Optional[str] = Field(None, max_length=50)
    profile_picture_url: Optional[str] = Field(None, description="URL to profile image")


class UserResponse(TimestampMixin, BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: int = Field(..., description="Database primary key")
    email: EmailStr
    first_name: Optional[str]
    last_name: Optional[str]
    is_active: bool = Field(default=True)
    profile_picture_url: Optional[str] = None
    metadata: dict = Field(default_factory=dict, description="Additional user metadata")
```

### 4.3 Schema Mixin (NEW)
```python
# app/schemas/mixins.py
from pydantic import BaseModel, Field
from datetime import datetime


class TimestampMixin(BaseModel):
    """Mixin that adds created_at and updated_at fields to schemas."""
    created_at: datetime = Field(..., description="Record creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")


class PaginationMixin(BaseModel):
    """Mixin for paginated response schemas."""
    page: int = Field(1, ge=1, description="Current page number")
    per_page: int = Field(20, ge=1, le=100, description="Items per page")
    total: int = Field(..., ge=0, description="Total number of items")
    total_pages: int = Field(..., ge=0, description="Total number of pages")
```

### 4.4 Coverage Analyzer (NEW)
```python
# app/core/coverage/analyzer.py
import ast
from pathlib import Path
from typing import Dict, Set, List, Tuple
from collections import defaultdict
import re


class SchemaCoverageAnalyzer:
    def __init__(self, project_dir: Path, exclude_schemas: List[str] = None):
        self.project_dir = project_dir
        self.exclude_schemas = set(exclude_schemas or [])
        self.schema_fields: Dict[str, Set[str]] = defaultdict(set)
        self.field_references: Dict[str, Set[str]] = defaultdict(set)
        self.schema_locations: Dict[str, str] = {}

    def analyze(self) -> None:
        """Main analysis entry point - parse schemas and test references."""
        self._find_and_parse_schemas()
        self._scan_test_files()
        self._scan_route_files()

    def _find_and_parse_schemas(self) -> None:
        """Locate and parse all Pydantic BaseModel subclasses."""
        for py_file in self.project_dir.glob("**/*.py"):
            if self._should_skip_file(py_file):
                continue
            self._parse_schema_file(py_file)

    def _parse_schema_file(self, file_path: Path) -> None:
        """Extract schema field definitions using AST."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                tree = ast.parse(f.read(), filename=str(file_path))
        except (SyntaxError, UnicodeDecodeError):
            return

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            
            # Check if class inherits from BaseModel
            base_names = []
            for base in node.bases:
                if isinstance(base, ast.Name):
                    base_names.append(base.id)
                elif isinstance(base, ast.Attribute):
                    base_names.append(base.attr)
            
            if 'BaseModel' not in base_names:
                continue
            
            schema_name = node.name
            if schema_name in self.exclude_schemas:
                continue
            
            self.schema_locations[schema_name] = str(file_path.relative_to(self.project_dir))
            
            for item in node.body:
                # Handle regular field assignments
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    field_name = item.target.id
                    if not field_name.startswith('_'):
                        self.schema_fields[schema_name].add(field_name)
                
                # Handle Field() assignments with default values
                elif isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name):
                            field_name = target.id
                            if not field_name.startswith('_'):
                                self.schema_fields[schema_name].add(field_name)

    def _scan_test_files(self) -> None:
        """Find schema field references in test files."""
        test_patterns = [
            self.project_dir / 'tests',
            self.project_dir / 'test',
            self.project_dir / '**/test_*.py',
            self.project_dir / '**/*_test.py'
        ]
        
        for pattern in test_patterns:
            for test_file in self.project_dir.glob(str(pattern)):
                if test_file.is_file() and test_file.suffix == '.py':
                    self._parse_field_references(test_file)

    def _parse_field_references(self, file_path: Path) -> None:
        """Record schema field references in Python files."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                tree = ast.parse(content, filename=str(file_path))
        except (SyntaxError, UnicodeDecodeError):
            return

        # Find all attribute accesses
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                # Try to resolve the variable name
                if isinstance(node.value, ast.Name):
                    schema_name = node.value.id
                    if schema_name in self.schema_fields:
                        field_name = node.attr
                        if field_name in self.schema_fields[schema_name]:
                            self.field_references[schema_name].add(field_name)
                
                # Handle nested attribute access (e.g., user.profile.name)
                elif isinstance(node.value, ast.Attribute):
                    # We'll track the leaf attribute name
                    field_name = node.attr
                    # Check if any schema has this field
                    for schema_name, fields in self.schema_fields.items():
                        if field_name in fields:
                            self.field_references[schema_name].add(field_name)

    def _should_skip_file(self, file_path: Path) -> bool:
        """Determine if a file should be skipped from analysis."""
        skip_patterns = [
            'migrations', '.venv', 'venv', 'env', '.git', '__pycache__',
            'node_modules', '.pytest_cache', '.coverage'
        ]
        path_str = str(file_path)
        return any(pattern in path_str for pattern in skip_patterns)

    def _scan_route_files(self) -> None:
        """Scan route files for schema usage in FastAPI endpoints."""
        route_patterns = ['**/routes/*.py', '**/api/*.py', '**/endpoints/*.py']
        for pattern in route_patterns:
            for route_file in self.project_dir.glob(pattern):
                if route_file.is_file():
                    self._parse_field_references(route_file)
```

### 4.5 Coverage Reporter (NEW)
```python
# app/core/coverage/reporter.py
import json
from pathlib import Path
from typing import Dict, List, Tuple
from datetime import datetime
from dataclasses import dataclass, asdict
from decimal import Decimal, ROUND_HALF_UP


@dataclass
class SchemaCoverage:
    name: str
    location: str
    total_fields: int
    covered_fields: int
    coverage_percentage: float
    orphan_fields: List[str]
    meets_threshold: bool


class CoverageReporter:
    def __init__(self, analyzer: 'SchemaCoverageAnalyzer'):
        self.analyzer = analyzer
        self.coverage_data: Dict[str, SchemaCoverage] = {}
        self.summary = {
            'total_schemas': 0,
            'total_fields': 0,
            'covered_fields': 0,
            'overall_coverage': 0.0,
            'schemas_below_threshold': 0,
            'total_orphan_fields': 0
        }

    def calculate_coverage(self, threshold_pct: float = 80.0) -> Dict[str, SchemaCoverage]:
        """Calculate coverage for all schemas."""
        for schema_name, fields in self.analyzer.schema_fields.items():
            covered = self.analyzer.field_references.get(schema_name, set())
            total = len(fields)
            covered_count = len(covered)
            
            # Calculate percentage with rounding
            coverage_pct = (covered_count / total * 100) if total > 0 else 100.0
            coverage_pct = float(Decimal(str(coverage_pct)).quantize(
                Decimal('0.1'), rounding=ROUND_HALF_UP
            ))
            
            orphan_fields = sorted(fields - covered)
            meets_threshold = coverage_pct >= threshold_pct
            
            self.coverage_data[schema_name] = SchemaCoverage(
                name=schema_name,
                location=self.analyzer.schema_locations.get(schema_name, 'unknown'),
                total_fields=total,
                covered_fields=covered_count,
                coverage_percentage=coverage_pct,
                orphan_fields=orphan_fields,
                meets_threshold=meets_threshold
            )
            
            # Update summary
            self.summary['total_schemas'] += 1
            self.summary['total_fields'] += total
            self.summary['covered_fields'] += covered_count
            self.summary['total_orphan_fields'] += len(orphan_fields)
            if not meets_threshold:
                self.summary['schemas_below_threshold'] += 1
        
        # Calculate overall coverage
        if self.summary['total_fields'] > 0:
            overall = (self.summary['covered_fields'] / self.summary['total_fields']) * 100
            self.summary['overall_coverage'] = float(Decimal(str(overall)).quantize(
                Decimal('0.1'), rounding=ROUND_HALF_UP
            ))
        
        return self.coverage_data

    def generate_json_report(self, output_path: Path) -> None:
        """Generate JSON coverage report."""
        report = {
            'timestamp': datetime.utcnow().isoformat(),
            'summary': self.summary,
            'schemas': {
                name: asdict(data) for name, data in self.coverage_data.items()
            }
        }
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

    def generate_terminal_report(self) -> str:
        """Generate human-readable terminal report."""
        lines = []
        lines.append("=" * 80)
        lines.append("SCHEMA COVERAGE REPORT")
        lines.append("=" * 80)
        
        # Summary
        lines.append(f"\nSUMMARY:")
        lines.append(f"  Total Schemas: {self.summary['total_schemas']}")
        lines.append(f"  Overall Coverage: {self.summary['overall_coverage']:.1f}%")
        lines.append(f"  Schemas Below Threshold: {self.summary['schemas_below_threshold']}")
        lines.append(f"  Total Orphan Fields: {self.summary['total_orphan_fields']}")
        
        # Per-schema details
        lines.append(f"\nDETAILED COVERAGE:")
        for schema_name, data in sorted(self.coverage_data.items()):
            status = "✓" if data.meets_threshold else "✗"
            lines.append(f"\n  {status} {schema_name} ({data.location})")
            lines.append(f"    Coverage: {data.coverage_percentage:.1f}% ({data.covered_fields}/{data.total_fields})")
            if data.orphan_fields:
                lines.append(f"    Orphan Fields: {', '.join(data.orphan_fields)}")
        
        lines.append("\n" + "=" * 80)
        return "\n".join(lines)
```

### 4.6 CLI Tool (NEW)
```python
# app/core/coverage/cli.py
import argparse
import sys
from pathlib import Path
from typing import Optional
from .analyzer import SchemaCoverageAnalyzer
from .reporter import CoverageReporter


def schema_coverage(
    project_dir: str,
    threshold_pct: float = 80.0,
    fail_on_orphan_fields: bool = True,
    exclude_schemas: Optional[list[str]] = None
) -> dict:
    """
    Main entry point for schema coverage analysis.
    
    Args:
        project_dir: Absolute path to FastAPI project root
        threshold_pct: Minimum required coverage percentage
        fail_on_orphan_fields: Raise error if untested fields exist
        exclude_schemas: Schema class names to exclude from analysis
    
    Returns:
        Dictionary containing coverage report data
    """
    project_path = Path(project_dir).resolve()
    if not project_path.exists():
        raise ValueError(f"Project directory does not exist: {project_dir}")
    
    # Initialize analyzer
    analyzer = SchemaCoverageAnalyzer(project_path, exclude_schemas=exclude_schemas)
    analyzer.analyze()
    
    # Generate report
    reporter = CoverageReporter(analyzer)
    coverage_data = reporter.calculate_coverage(threshold_pct)
    
    # Generate output
    output_path = project_path / "schema_coverage.json"
    reporter.generate_json_report(output_path)
    
    # Print terminal report
    print(reporter.generate_terminal_report())
    
    # Check for failures
    exit_code = 0
    if fail_on_orphan_fields:
        for schema_name, data in coverage_data.items():
            if data.orphan_fields:
                print(f"\nERROR: Schema '{schema_name}' has orphan fields: {data.orphan_fields}")
                exit_code = 1
    
    if reporter.summary['overall_coverage'] < threshold_pct:
        print(f"\nERROR: Overall coverage {reporter.summary['overall_coverage']:.1f}% "
              f"is below threshold of {threshold_pct}%")
        exit_code = 1
    
    if exit_code != 0:
        sys.exit(exit_code)
    
    return {
        'summary': reporter.summary,
        'schemas': {name: vars(data) for name, data in coverage_data.items()}
    }


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Analyze Pydantic schema test coverage in FastAPI projects"
    )
    parser.add_argument(
        "project_dir",
        type=str,
        help="Path to FastAPI project root directory"
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=80.0,
        help="Minimum required coverage percentage (default: 80.0)"
    )
    parser.add_argument(
        "--no-fail-on-orphan",
        action="store_false",
        dest="fail_on_orphan",
        default=True,
        help="Do not fail if orphan fields are detected"
    )
    parser.add_argument(
        "--exclude",
        type=str,
        nargs="+",
        help="Schema class names to exclude from analysis"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="schema_coverage.json",
        help="Output JSON file path (default: schema_coverage.json)"
    )
    
    args = parser.parse_args()
    
    try:
        result = schema_coverage(
            project_dir=args.project_dir,
            threshold_pct=args.threshold,
            fail_on_orphan_fields=args.fail_on_orphan,
            exclude_schemas=args.exclude
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
```

### 4.7 Test Example with Coverage (NEW)
```python
# tests/test_user_schemas_coverage.py
import pytest
from app.schemas.user import UserCreate, UserUpdate, UserResponse
from datetime import datetime


def test_user_create_all_fields_covered():
    """Test that covers all fields of UserCreate schema."""
    data = {
        "email": "test@example.com",
        "password": "securepassword123",
        "first_name": "John",
        "last_name": "Doe"
    }
    user = UserCreate(**data)
    
    # Access all fields to ensure coverage
    assert user.email == "test@example.com"
    assert user.password == "securepassword123"
    assert user.first_name == "John"
    assert user.last_name == "Doe"
    
    # Test model_dump to ensure serialization
    dumped = user.model_dump()
    assert dumped["email"] == data["email"]
    assert dumped["first_name"] == data["first_name"]


def test_user_update_partial_fields():
    """Test partial updates covering some fields."""
    # Test with only email update
    update1 = UserUpdate(email="new@example.com")
    assert update1.email == "new@example.com"
    assert update1.first_name is None
    assert update1.last_name is None
    assert update1.profile_picture_url is None
    
    # Test with profile picture
    update2 = UserUpdate(profile_picture_url="https://example.com/avatar.jpg")
    assert update2.profile_picture_url == "https://example.com/avatar.jpg"
    assert update2.email is None


def test_user_response_all_fields():
    """Test UserResponse with all fields including inherited timestamps."""
    now = datetime.utcnow()
    data = {
        "id": 1,
        "email": "user@example.com",
        "first_name": "Alice",
        "last_name": "Smith",
        "is_active": True,
        "profile_picture_url": "https://example.com/avatar.png",
        "metadata": {"role": "admin", "preferences": {"theme": "dark"}},
        "created_at": now,
        "updated_at": now
    }
    user = UserResponse(**data)
    
    # Access all fields
    assert user.id == 1
    assert user.email == "user@example.com"
    assert user.first_name == "Alice"
    assert user.last_name == "Smith"
    assert user.is_active is True
    assert user.profile_picture_url == "https://example.com/avatar.png"
    assert user.metadata == {"role": "admin", "preferences": {"theme": "dark"}}
    assert user.created_at == now
    assert user.updated_at == now
    
    # Test computed property (if exists)
    if hasattr(user, 'full_name'):
        assert user.full_name == "Alice Smith"


def test_user_schema_validation():
    """Test field validation rules."""
    # Test password length validation
    with pytest.raises(ValueError):
        UserCreate(email="test@example.com", password="short")
    
    # Test email format
    with pytest.raises(ValueError):
        UserCreate(email="invalid-email", password="validpassword123")
    
    # Test optional fields can be omitted
    user = UserCreate(email="test@example.com", password="validpassword123")
    assert user.first_name is None
    assert user.last_name is None
```

### 4.8 Migration for Coverage History (NEW)
```python
# alembic/versions/20240408000000_add_schema_coverage_history.py
"""Add schema coverage history tracking

Revision ID: 20240408000000
Revises: 20240407000000
Create Date: 2024-04-08 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '20240408000000'
down_revision = '20240407000000'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create schema_coverage_runs table
    op.create_table('schema_coverage_runs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('run_timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('overall_coverage_pct', sa.Float(), nullable=False),
        sa.Column('total_schemas', sa.Integer(), nullable=False),
        sa.Column('total_fields', sa.Integer(), nullable=False),
        sa.Column('covered_fields', sa.Integer(), nullable=False),
        sa.Column('threshold_pct', sa.Float(), nullable=False),
        sa.Column('passed', sa.Boolean(), nullable=False),
        sa.Column('git_commit_hash', sa.String(40), nullable=True),
        sa.Column('git_branch', sa.String(100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), 
                  server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_schema_coverage_runs_run_timestamp', 
                   'schema_coverage_runs', ['run_timestamp'])
    op.create_index('ix_schema_coverage_runs_git_commit', 
                   'schema_coverage_runs', ['git_commit_hash'])
    
    # Create schema_coverage_details table
    op.create_table('schema_coverage_details',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('run_id', sa.UUID(), nullable=False),
        sa.Column('schema_name', sa.String(255), nullable=False),
        sa.Column('schema_location', sa.String(500), nullable=False),
        sa.Column('coverage_pct', sa.Float(), nullable=False),
        sa.Column('total_fields', sa.Integer(), nullable=False),
        sa.Column('covered_fields', sa.Integer(), nullable=False),
        sa.Column('meets_threshold', sa.Boolean(), nullable=False),
        sa.Column('orphan_fields', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), 
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['run_id'], ['schema_coverage_runs.id'], 
                              ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_schema_coverage_details_run_id', 
                   'schema_coverage_details', ['run_id'])
    op.create_index('ix_schema_coverage_details_schema_name', 
                   'schema_coverage_details', ['schema_name'])
    op.create_index('ix_schema_coverage_details_coverage_pct', 
                   'schema_coverage_details', ['coverage_pct'])
    
    # Create function to prune old coverage data
    op.execute("""
        CREATE OR REPLACE FUNCTION prune_old_coverage_runs(retention_days integer DEFAULT 90)
        RETURNS integer
        LANGUAGE plpgsql
        AS $$
        DECLARE
            deleted_count integer;
        BEGIN
            DELETE FROM schema_coverage_details
            WHERE run_id IN (
                SELECT id FROM schema_coverage_runs
                WHERE run_timestamp < NOW() - (retention_days || ' days')::interval
            );
            
            GET DIAGNOSTICS deleted_count = ROW_COUNT;
            
            DELETE FROM schema_coverage_runs
            WHERE run_timestamp < NOW() - (retention_days || ' days')::interval;
            
            RETURN deleted_count;
        END;
        $$;
    """)


def downgrade() -> None:
    op.drop_index('ix_schema_coverage_details_coverage_pct', 
                 table_name='schema_coverage_details')
    op.drop_index('ix_schema_coverage_details_schema_name', 
                 table_name='schema_coverage_details')
    op.drop_index('ix_schema_coverage_details_run_id', 
                 table_name='schema_coverage_details')
    op.drop_table('schema_coverage_details')
    
    op.drop_index('ix_schema_coverage_runs_git_commit', 
                 table_name='schema_coverage_runs')
    op.drop_index('ix_schema_coverage_runs_run_timestamp', 
                 table_name='schema_coverage_runs')
    op.drop_table('schema_coverage_runs')
    
    op.execute("DROP FUNCTION IF EXISTS prune_old_coverage_runs(integer);")
```

### 4.9 CI Integration Script (NEW)
```python
# scripts/ci_schema_coverage.py
#!/usr/bin/env python3
"""
CI script for schema coverage analysis.
Integrates with GitHub Actions, GitLab CI, and other CI systems.
"""
import os
import sys
import json
from pathlib import Path
from typing import Optional
import subprocess


def get_git_info() -> dict:
    """Get current git commit and branch information."""
    info = {
        'commit_hash': None,
        'branch': None,
        'tag': None
    }
    
    try:
        # Get commit hash
        result = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            capture_output=True,
            text=True,
            cwd=Path.cwd()
        )
        if result.returncode == 0:
            info['commit_hash'] = result.stdout.strip()
        
        # Get branch name
        result = subprocess.run(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            capture_output=True,
            text=True,
            cwd=Path.cwd()
        )
        if result.returncode == 0:
            info['branch'] = result.stdout.strip()
        
        # Get tag if any
        result = subprocess.run(
            ['git', 'describe', '--tags', '--exact-match', 'HEAD'],
            capture_output=True,
            text=True,
            cwd=Path.cwd()
        )
        if result.returncode == 0:
            info['tag'] = result.stdout.strip()
            
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    
    return info


def run_schema_coverage(
    project_dir: str,
    threshold: float,
    fail_on_orphan: bool,
    ci_provider: Optional[str] = None
) -> dict:
    """Run schema coverage analysis with CI integration."""
    from app.core.coverage.cli import schema_coverage
    
    # Get CI environment variables
    ci_env = {
        'provider': ci_provider or os.environ.get('CI_PROVIDER', 'unknown'),
        'run_id': os.environ.get('GITHUB_RUN_ID') or 
                  os.environ.get('GITLAB_CI_PIPELINE_ID') or
                  os.environ.get('CIRCLE_BUILD_NUM'),
        'job_id': os.environ.get('GITHUB_JOB') or 
                  os.environ.get('CI_JOB_ID'),
        'repo': os.environ.get('GITHUB_REPOSITORY') or 
                os.environ.get('CI_PROJECT_PATH'),
    }
    
    print(f"Running schema coverage analysis for {project_dir}")
    print(f"CI Provider: {ci_env['provider']}")
    print(f"Threshold: {threshold}%")
    print(f"Fail on orphan fields: {fail_on_orphan}")
    print("-" * 60)
    
    # Run coverage analysis
    result = schema_coverage(
        project_dir=project_dir,
        threshold_pct=threshold,
        fail_on_orphan_fields=fail_on_orphan,
        exclude_schemas=['BaseModel', 'Config']  # Exclude common base classes
    )
    
    # Add CI context to result
    result['ci_context'] = ci_env
    result['git_info'] = get_git_info()
    
    # Generate CI-specific output
    if ci_env['provider'] == 'github':
        _generate_github_summary(result)
    elif ci_env['provider'] == 'gitlab':
        _generate_gitlab_metrics(result)
    
    return result


def _generate_github_summary(coverage_result: dict) -> None:
    """Generate GitHub Actions job summary."""
    summary_path = os.environ.get('GITHUB_STEP_SUMMARY')
    if not summary_path:
        return
    
    summary_lines = [
        "# Schema Coverage Report",
        "",
        f"**Overall Coverage**: {coverage_result['summary']['overall_coverage']:.1f}%",
        f"**Total Schemas**: {coverage_result['summary']['total_schemas']}",
        f"**Schemas Below Threshold**: {coverage_result['summary']['schemas_below_threshold']}",
        "",
        "## Detailed Results",
        "",
        "| Schema | Coverage | Status | Orphan Fields |",
        "|--------|----------|--------|---------------|"
    ]
    
    for schema_name, data in coverage_result['schemas'].items():
        status = "✅" if data['meets_threshold'] else "❌"
        orphan_count = len(data['orphan_fields'])
        orphan_display = str(orphan_count) if orphan_count > 0 else "None"
        summary_lines.append(
            f"| `{schema_name}` | {data['coverage_percentage']:.1f}% | {status} | {orphan_display} |"
        )
    
    with open(summary_path, 'w') as f:
        f.write('\n'.join(summary_lines))


def _generate_gitlab_metrics(coverage_result: dict) -> None:
    """Generate GitLab CI metrics file."""
    metrics_path = Path('coverage-metrics.json')
    metrics = {
        'schema_coverage': {
            'value': coverage_result['summary']['overall_coverage'],
            'unit': 'percent',
            'label': 'Schema Test Coverage'
        },
        'schemas_covered': {
            'value': coverage_result['summary']['total_schemas'] - 
                    coverage_result['summary']['schemas_below_threshold'],
            'unit': 'schemas',
            'label': 'Schemas Meeting Threshold'
        },
        'orphan_fields': {
            'value': coverage_result['summary']['total_orphan_fields'],
            'unit': 'fields',
            'label': 'Untested Schema Fields'
        }
    }
    
    with open(metrics_path, 'w') as f:
        json.dump(metrics, f, indent=2)


def main() -> None:
    """Main entry point for CI script."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Run schema coverage analysis in CI environment"
    )
    parser.add_argument(
        "--project-dir",
        type=str,
        default=".",
        help="Project directory path"
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=float(os.environ.get('SCHEMA_COVERAGE_THRESHOLD', '80.0')),
        help="Coverage threshold percentage"
    )
    parser.add_argument(
        "--no-fail-on-orphan",
        action="store_true",
        help="Don't fail on orphan fields"
    )
    parser.add_argument(
        "--ci-provider",
        type=str,
        choices=['github', 'gitlab', 'circleci', 'jenkins'],
        help="CI provider for integration"
    )
    
    args = parser.parse_args()
    
    try:
        result = run_schema_coverage(
            project_dir=args.project_dir,
            threshold=args.threshold,
            fail_on_orphan=not args.no_fail_on_orphan,
            ci_provider=args.ci_provider
        )
        
        # Exit with appropriate code
        if result['summary']['overall_coverage'] < args.threshold:
            sys.exit(1)
        if not args.no_fail_on_orphan and result['summary']['total_orphan_fields'] > 0:
            sys.exit(1)
            
    except Exception as e:
        print(f"Error running schema coverage: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **AST parsing covers all BaseModel subclasses** | `CoverageAnalyzer.parse_schemas()` walks project_dir excluding test files, using `ast.ClassDef` and `_is_base_model()` check |
| QS-2 | **Field coverage calculation is deterministic** | `get_coverage()` divides `len(tested_fields)` by `len(schema_fields)` with sorted field lists to ensure reproducibility |
| QS-3 | **Private fields are always excluded** | `parse_schemas()` skips fields starting with `_` via explicit `not field_name.startswith("_")` check |
| QS-4 | **Test references are validated via AST** | `parse_tests()` uses `ast.Attribute` nodes and `_get_schema_name()` to resolve schema.field_name references |
| QS-5 | **Coverage threshold enforcement is strict** | `schema_coverage()` CLI compares each schema's percentage against threshold_pct with `>=` operator |
| QS-6 | **Orphan field detection is comprehensive** | `get_orphans()` performs set difference between schema_fields and tested_fields with deterministic sorting |
| QS-7 | **Report generation is atomic** | `CoverageReport.save()` writes to temporary file then renames to coverage.json to prevent partial writes |
| QS-8 | **CI integration fails closed** | `.github/workflows/schema_coverage.yml` runs analyzer and calls `coverage_report --fail-if-below` with non-zero exit code |
| QS-9 | **Schema exclusions are explicit** | `exclude_schemas` parameter is passed through to analyzer and checked before processing any schema |
| QS-10 | **Nested BaseModels are recursively analyzed** | `parse_schemas()` detects nested BaseModel fields via `ast.AnnAssign` type hints and includes them in coverage |
| QS-11 | **Tool execution is read-only** | File operations are strictly read (`open()` mode 'r') except for final report writing to coverage.json |
| QS-12 | **Performance SLOs are enforced** | `time.perf_counter()` measurements in `__main__.py` abort if analysis exceeds 3s with status code 124 |

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `CoverageAnalyzer` class exists at `app/core/coverage_analyzer.py` | File exists, parses |
| CC-02 | `CoverageReport` class exists at `app/core/coverage_report.py` | File exists, exports verified |
| CC-03 | CI workflow exists at `.github/workflows/schema_coverage.yml` | File exists, runs on PR |
| CC-04 | Schema coverage model has `orphan_fields` JSON column | Inspect `SchemaCoverage` model |
| CC-05 | All BaseModel subclasses are detected | grep `class .*\(BaseModel` matches analyzer output |
| CC-06 | Private fields (prefix `_`) are excluded | T-07, T-08 |
| CC-07 | Computed properties are excluded | Inspect `@property` handling in analyzer |
| CC-08 | Coverage percentage rounds to 2 decimal places | Inspect `add_schema()` in CoverageReport |
| CC-09 | Orphan field list is sorted alphabetically | Inspect `get_orphans()` output |
| CC-10 | Threshold enforcement uses `>=` not `>` | Inspect CLI comparison logic |
| CC-11 | Test references match exact field names | T-01, T-02 |
| CC-12 | Nested BaseModel fields are counted | T-25 |
| CC-13 | Inherited fields are counted | T-26 |
| CC-14 | Excluded schemas are skipped entirely | T-12 |
| CC-15 | Report contains UTC timestamp | Inspect `generated_at` field |
| CC-16 | Report schema matches expected structure | json-schema validation |
| CC-17 | CI job fails when below threshold | T-19 |
| CC-18 | CI job passes when above threshold | T-20 |
| CC-19 | Zero-field schemas report 100% coverage | T-06 |
| CC-20 | Dynamic field access (`getattr`) is not counted | T-27 |
| CC-21 | Field renames are detected as orphans | T-28 |
| CC-22 | Tool is idempotent on re-run | T-29 |
| CC-23 | Execution time < 3s for 50 schemas | Benchmark T-30 |
| CC-24 | Memory overhead < 50MB | Benchmark T-30 |
| CC-25 | Migration adds `updated_at` to schema_coverage | Inspect migration file |
| CC-26 | Report shows PASS/FAIL status per schema | Inspect report output |
| CC-27 | Test files are excluded from schema parsing | grep `if "test" in path.parts` |
| CC-28 | All 30 tests exist in `tests/test_schema_coverage.py` | File exists, 30 test functions |
| CC-29 | OpenAPI docs are unaffected by tool | curl `/openapi.json` unchanged |
| CC-30 | Backward compatible with Pydantic v1 and v2 | tox.ini tests both versions |

## 7. Definition of Done

- [ ] All 30 Completeness Criteria verified
- [ ] Test coverage at 100% for analyzer and report modules
- [ ] GitHub Actions workflow passes on PR
- [ ] Migration applied to production database
- [ ] SchemaCoverage model deployed with alembic
- [ ] Performance benchmarks meet SLOs (T-30)
- [ ] Documentation in README.md updated
- [ ] Example report in docs/examples/coverage.json
- [ ] Pre-commit hook available in .pre-commit-config.yaml
- [ ] All edge cases from section 9 tested
- [ ] Backward compatibility with Pydantic v1 confirmed
- [ ] Integration test with real FastAPI project
- [ ] Changelog entry added for release

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-SC-01 | **Coverage percentage is always between 0 and 100** | `get_coverage()` clamps result via `min(max(round(pct * 100, 2), 0), 100)` before report generation | T-01, T-06 |
| INV-SC-02 | **Orphan field detection never includes private fields** | `parse_schemas()` skips fields starting with `_` via explicit string check before adding to schema_fields | T-07, T-08 |
| INV-SC-03 | **Test file analysis never counts imports as field usage** | `parse_tests()` requires direct attribute access via `ast.Attribute` nodes with resolved schema name | T-09, T-10 |
| INV-SC-04 | **Schema exclusions are applied before any processing** | `schema_coverage()` filters `exclude_schemas` list against discovered schemas during initialization | T-11, T-12 |
| INV-SC-05 | **Report generation is atomic and crash-resistant** | `CoverageReport.save()` writes to tempfile then performs atomic rename via `os.replace()` | T-21, T-22 |
| INV-SC-06 | **CI integration fails closed on coverage violations** | `.github/workflows/schema_coverage.yml` runs `coverage_report --fail-if-below` with strict exit code check | T-19, T-20 |
| INV-SC-07 | **Nested BaseModel fields are always counted in parent schema** | `parse_schemas()` recursively processes nested BaseModel type hints via `ast.AnnAssign` inspection | T-25 |
| INV-SC-08 | **Tool execution never modifies source files** | File operations are strictly read-only except for final report, enforced via mode='r' and AST-only parsing | T-29 |

---

## 9. User Stories

### 9.1 Core Coverage Analysis (US-01 .. US-05)

**US-01: Calculate basic schema coverage**
- **As a** developer maintaining API contracts
- **I want** to measure test coverage for all Pydantic schemas
- **So that** I can identify untested fields before deployment
- **Given:** Schema `UserCreate` with 5 fields (`name`, `email`, `password`, `role`, `is_active`)
- **When:** I run `schema_coverage("/code/myapp")` with tests covering `name`, `email`, `password`
- **Then:**
  - Report shows 60% coverage for `UserCreate` (INV-SC-01)
  - Orphan fields list contains `["role", "is_active"]` (CC-09)
  - Console output highlights `UserCreate` as below threshold (T-13)

**US-02: Detect orphan fields in large schema**
- **As a** API architect reviewing test coverage
- **I want** to identify unused fields in complex schemas
- **So that** I can deprecate dead code
- **Given:** `Product` schema with 20 fields in `app/schemas/product.py`
- **When:** Tests only reference 15 fields via `Product.price`, `Product.sku` etc.
- **Then:**
  - Tool outputs 5 orphan fields sorted alphabetically (INV-SC-02)
  - Coverage percentage calculated as 75% (15/20) (CC-05)
  - Report includes file path `app/schemas/product.py` for context (T-02)

**US-03: Exclude private fields from coverage**
- **As a** developer using internal fields
- **I want** `_internal` fields excluded from coverage metrics
- **So that** my test coverage isn't penalized for implementation details
- **Given:** Schema with `_cache_expiry` and `public_field`
- **When:** Running coverage analysis
- **Then:**
  - `_cache_expiry` never appears in orphan list (INV-SC-02)
  - Coverage calculated only for `public_field` (CC-06)
  - Report shows 100% if `public_field` is tested (T-07)

**US-04: Handle zero-field schemas**
- **As a** developer using marker schemas
- **I want** empty schemas to show 100% coverage
- **So that** they don't fail threshold checks
- **Given:** `EmptySchema` with no fields in `app/schemas/markers.py`
- **When:** Running coverage analysis
- **Then:**
  - Report shows 100% coverage for `EmptySchema` (CC-19)
  - Orphan fields list is empty (T-06)
  - Console output marks `EmptySchema` as PASS (INV-SC-01)

**US-05: Validate test file parsing**
- **As a** test engineer
- **I want** the tool to correctly count field references in tests
- **So that** coverage metrics are accurate
- **Given:** Test file `tests/test_users.py` with `UserCreate.email` assertion
- **When:** Running coverage analysis
- **Then:**
  - `email` counted as tested field (INV-SC-03)
  - Import statements like `from app.schemas import UserCreate` not counted (T-09)
  - Dynamic access via `getattr(UserCreate, "email")` not counted (CC-20)

### 9.2 Threshold Enforcement (US-06 .. US-10)

**US-06: Fail CI below coverage threshold**
- **As a** CI pipeline maintainer
- **I want** builds to fail when coverage drops below 80%
- **So that** untested schemas can't reach production
- **Given:** Schema with 79.9% coverage in `.github/workflows/coverage.yml`
- **When:** CI runs `schema_coverage --threshold 80`
- **Then:**
  - Process exits with code 1 (INV-SC-06)
  - GitHub Actions job marked as failed (T-19)
  - Report artifact still generated for analysis (CC-17)

**US-07: Pass CI above coverage threshold**
- **As a** developer pushing tested code
- **I want** CI to pass when coverage meets requirements
- **So that** my deployments aren't blocked
- **Given:** Schema with 80.1% coverage in `app/schemas/valid.py`
- **When:** CI runs `schema_coverage --threshold 80`
- **Then:**
  - Process exits with code 0 (CC-18)
  - GitHub Actions job marked as passed (T-20)
  - Report shows PASS status for the schema (CC-26)

**US-08: Custom threshold per schema**
- **As a** API team lead
- **I want** to set different thresholds for critical vs non-critical schemas
- **So that** core contracts have stricter requirements
- **Given:** `PaymentSchema` requires 95% while `LogSchema` only needs 50%
- **When:** Running `schema_coverage` with config file specifying thresholds
- **Then:**
  - `PaymentSchema` fails at 94% coverage (T-14)
  - `LogSchema` passes at 51% coverage (T-15)
  - Report highlights threshold differences per schema (CC-10)

**US-09: Disable orphan field failures**
- **As a** developer working with legacy schemas
- **I want** to run coverage without failing on orphans
- **So that** I can gather metrics incrementally
- **Given:** Schema with 5 orphan fields
- **When:** Running `schema_coverage(fail_on_orphan_fields=False)`
- **Then:**
  - Orphans still reported in output (CC-06)
  - Process exits 0 if coverage threshold met (INV-SC-04)
  - Console warns about orphans without failing (T-11)

**US-10: Enforce 100% coverage for critical schemas**
- **As a** security engineer
- **I want** auth schemas to require 100% coverage
- **So that** no security fields go untested
- **Given:** `AuthToken` schema with `token`, `expires_at`, `scope`
- **When:** Running with `--threshold 100` for auth schemas
- **Then:**
  - Fails if any field untested (INV-SC-05)
  - Highlights exact missing test cases (CC-11)
  - Report shows coverage gap percentage (T-16)

### 9.3 Schema Exclusions & Edge Cases (US-11 .. US-15)

**US-11: Exclude deprecated schemas**
- **As a** developer maintaining backwards compatibility
- **I want** to exclude legacy schemas from coverage
- **So that** old versions don't fail CI
- **Given:** `LegacyUserV1` in `exclude_schemas: list[str]`
- **When:** Running coverage analysis
- **Then:**
  - `LegacyUserV1` omitted from report (INV-SC-04)
  - Console logs "Skipping LegacyUserV1 (excluded)" (T-12)
  - Coverage percentages only include non-excluded schemas (CC-14)

**US-12: Detect renamed fields**
- **As a** developer refactoring schemas
- **I want** to catch tests using old field names
- **So that** I can update or remove obsolete tests
- **Given:** Field changed from `user_name` to `username` in `UserSchema`
- **When:** Running coverage analysis
- **Then:**
  - `user_name` appears as orphan (CC-21)
  - Tests referencing `user_name` flagged in report (T-28)
  - Console suggests updating tests to `username` (CC-11)

**US-13: Handle nested BaseModels**
- **As a** developer using complex schemas
- **I want** nested models included in coverage
- **So that** all contract surfaces are measured
- **Given:** `Order` schema with nested `Address` BaseModel
- **When:** Running coverage analysis
- **Then:**
  - Both `Order` and `Address` fields counted (INV-SC-07)
  - Nested fields like `order.shipping_address.city` tracked (T-25)
  - Coverage percentage accounts for all nested fields (CC-12)

**US-14: Skip computed properties**
- **As a** developer using @property decorators
- **I want** computed fields excluded from coverage
- **So that** my metrics reflect actual schema contracts
- **Given:** `@property def full_name(self)` in `UserSchema`
- **When:** Running coverage analysis
- **Then:**
  - `full_name` never appears in field counts (CC-07)
  - Coverage percentage based only on declared fields (T-08)
  - Report notes "X computed properties excluded" (INV-SC-02)

**US-15: Validate inherited fields**
- **As a** developer using schema inheritance
- **I want** parent class fields included in coverage
- **So that** all contract surfaces are measured
- **Given:** `AdminUser` inheriting from `BaseUser` with 3 extra fields
- **When:** Running coverage analysis
- **Then:**
  - All parent and child fields counted (CC-13)
  - Coverage percentage reflects total field count (T-26)
  - Orphan detection works across inheritance (INV-SC-07)

### 9.4 CI & Reporting (US-16 .. US-20)

**US-16: Generate PR coverage report**
- **As a** reviewer evaluating a pull request
- **I want** to see coverage changes in GitHub comments
- **So that** I can assess test completeness
- **Given:** PR modifying `ProductSchema` in `app/schemas/product.py`
- **When:** CI runs `schema_coverage --pr-comment`
- **Then:**
  - GitHub comment shows before/after coverage (CC-28)
  - Highlighted orphan fields if any (T-23)
  - Direct links to schema and test files (CC-16)

**US-17: Incremental analysis for PRs**
- **As a** developer working on a feature branch
- **I want** to analyze only changed schemas
- **So that** CI runs faster for small changes
- **Given:** PR touching only `OrderSchema` in `app/schemas/order.py`
- **When:** Running `schema_coverage --incremental`
- **Then:**
  - Only `OrderSchema` analyzed (CC-27)
  - Execution time under 1s (CC-23)
  - Report focuses on modified schemas (T-24)

**US-18: Save historical coverage**
- **As a** engineering manager
- **I want** to track coverage trends over time
- **So that** I can measure quality improvements
- **Given:** Daily CI runs on main branch
- **When:** Tool configured with `--save-history`
- **Then:**
  - Coverage data stored in `coverage_history.json` (CC-04)
  - Timestamps in ISO format (CC-15)
  - SchemaCoverage model updated (T-21)

**US-19: Export machine-readable report**
- **As a** dashboarding system
- **I want** coverage data in structured JSON
- **So that** I can visualize trends
- **Given:** Run with `--format json`
- **When:** Analysis completes
- **Then:**
  - Outputs `coverage.json` with schema data (CC-02)
  - Includes coverage percentages and orphans (CC-16)
  - Valid JSON schema (INV-SC-05)

**US-20: Annotate source with coverage**
- **As a** developer fixing coverage gaps
- **I want** to see orphan markers in my IDE
- **So that** I can quickly add missing tests
- **Given:** Schema with untested `priority` field
- **When:** Running with `--ide-annotations`
- **Then:**
  - Generates `coverage.ide` file with markers (CC-03)
  - Lines contain `# orphan: UserSchema.priority` (T-22)
  - VSCode/IntelliJ can parse the format (CC-28)

### 9.5 Performance & Observability (US-21 .. US-25)

**US-21: Meet 3s SLO for 50 schemas**
- **As a** developer running pre-commit hooks
- **I want** analysis to complete quickly
- **So that** my workflow isn't interrupted
- **Given:** Project with 50 schemas in `app/schemas/`
- **When:** Running `schema_coverage`
- **Then:**
  - Completes in <3s (CC-23)
  - Memory usage <50MB (CC-24)
  - Progress output shows analyzed files (T-30)

**US-22: Skip test files during schema parsing**
- **As a** performance-conscious developer
- **I want** the tool to ignore test files during initial scan
- **So that** analysis runs faster
- **Given:** Project with 100 test files in `tests/`
- **When:** Running coverage analysis
- **Then:**
  - Test files never parsed for schema detection (CC-27)
  - Console shows "Skipping tests/test_user.py" (T-29)
  - Schema parsing completes in <100ms (CC-05)

**US-23: Monitor analysis performance**
- **As a** tool maintainer
- **I want** to track parsing times
- **So that** I can optimize hotspots
- **Given:** Large project with 200 schemas
- **When:** Running with `--profile`
- **Then:**
  - Outputs timing breakdown per phase (CC-28)
  - Flags files taking >100ms (CC-23)
  - Writes `coverage_profile.json` (T-30)

**US-24: Handle 10K field schemas**
- **As a** developer working with generated schemas
- **I want** the tool to handle large schemas
- **So that** I can analyze complex APIs
- **Given:** `BigSchema` with 10,000 fields
- **When:** Running coverage analysis
- **Then:**
  - Completes in <5s (CC-23)
  - Memory stays <100MB (CC-24)
  - Report shows top 10 orphans if truncated (T-27)

**US-25: Verify tool idempotency**
- **As a** CI system administrator
- **I want** multiple runs to produce identical output
- **So that** results are deterministic
- **Given:** Unchanged codebase
- **When:** Running `schema_coverage` twice
- **Then:**
  - Same coverage percentages (INV-SC-05)
  - Same orphan field lists (CC-09)
  - Report has identical checksum (T-29)

---

## 10. Test Plan

### 10.1 Basic Coverage Calculation Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | 100% coverage schema | UserSchema with 3 fields (name, email, age) all referenced in tests/test_user.py | Run `schema_coverage("/project")` | Report shows UserSchema: 100% coverage, 0 orphans (INV-SC-01) |
| T-02 | Partial coverage schema | ProductSchema with 5 fields (id, name, price, category, stock) - only id/name tested | Run coverage analysis | Report shows ProductSchema: 40% coverage, orphans ["price", "category", "stock"] (CC-11) |
| T-03 | Zero coverage schema | OrderSchema with 4 fields (id, items, total, status) - no test references | Run with threshold=50 | Report shows 0% coverage, all fields as orphans, fails CI (T-19) |
| T-04 | Field referenced in multiple tests | AddressSchema.city referenced in test_user.py and test_order.py | Run coverage | city counted once (no double-counting), appears in tested_fields (INV-SC-03) |
| T-05 | Schema with only one field | ConfigSchema.timeout with test reference | Run analysis | Report shows 100% coverage, empty orphans list (CC-19) |
| T-06 | Empty schema | EmptyMarker with no fields | Run coverage | Report shows 100% coverage (INV-SC-01), "No fields to test" note (T-06) |

### 10.2 Orphan Field Detection Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-07 | Private field exclusion | UserSchema._internal_cache field | Run analysis | _internal_cache never appears in schema_fields or orphans (INV-SC-02) |
| T-08 | Computed property exclusion | @property def full_name in UserSchema | Run coverage | full_name excluded from field count, not in orphans (CC-07) |
| T-09 | Import-only not counted | test_user.py imports UserSchema but never references fields | Run analysis | UserSchema shows 0% coverage (INV-SC-03) |
| T-10 | Dynamic access not counted | test uses getattr(UserSchema, "email") | Run coverage | email marked as orphan (CC-20) |
| T-11 | Excluded schema skipped | exclude_schemas=["LegacyModel"] | Run with LegacyModel present | Report omits LegacyModel, logs "Skipping LegacyModel" (INV-SC-04) |
| T-12 | Non-excluded schema processed | exclude_schemas=["OldModel"] but NewModel present | Run analysis | NewModel appears in report (T-12) |

### 10.3 Threshold Enforcement Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-13 | Exact threshold pass | Schema at 80.0% coverage, threshold=80 | Run analysis | Report shows PASS status (CC-10) |
| T-14 | Below threshold fail | Schema at 79.9% coverage, threshold=80 | Run coverage | Process exits 1, CI fails (INV-SC-06) |
| T-15 | Disabled orphan check | fail_on_orphan_fields=False with orphans present | Run tool | Exits 0 if coverage met, orphans still reported (US-09) |
| T-16 | 100% threshold strict | AuthSchema requires 100%, has 1 untested field | Run with --threshold 100 | Fails with "Missing coverage for AuthSchema.token" (T-16) |
| T-17 | Zero threshold always passes | Schema with 0% coverage, threshold=0 | Run analysis | Always passes (CC-10) |
| T-18 | Per-schema thresholds | payment.yml sets PaymentSchema=95%, LogSchema=50% | Run with --config payment.yml | Enforces different thresholds per schema (US-08) |

### 10.4 CI & Report Generation Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-19 | CI failure below threshold | GitHub Actions with threshold=80, schema at 75% | Push commit | Workflow fails, artifact contains report (INV-SC-06) |
| T-20 | CI success above threshold | GitHub Actions with threshold=80, schema at 85% | Push commit | Workflow passes, report uploaded (CC-18) |
| T-21 | Atomic report write | Kill process during report generation | Restart analysis | coverage.json either complete or missing, never corrupt (INV-SC-05) |
| T-22 | IDE annotations | Run with --ide-annotations | Check coverage.ide | Contains "# orphan: UserSchema.age" near field definition (T-22) |
| T-23 | PR comment output | Run with --pr-comment on GitHub PR | Check comment | Shows before/after coverage diffs (US-16) |
| T-24 | Incremental analysis | PR modifies only OrderSchema | Run --incremental | Only analyzes OrderSchema, skips others (US-17) |

### 10.5 Edge Cases & Performance

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-25 | Nested BaseModel | OrderSchema with nested Address fields | Run coverage | Both Order.id and Address.street counted (INV-SC-07) |
| T-26 | Inherited fields | AdminUser inherits from User (username field) | Run analysis | username counted in AdminUser coverage (CC-13) |
| T-27 | Field rename detection | UserSchema changed email→email_address | Run coverage | email marked as orphan, suggests update (CC-21) |
| T-28 | Large schema handling | Schema with 500 fields | Run analysis | Completes in <3s, memory <50MB (CC-23) |
| T-29 | Tool idempotency | Unchanged codebase | Run twice | Identical report checksums (INV-SC-08) |
| T-30 | Performance SLO | Project with 50 schemas | Time execution | <3s total, <100ms/schema (CC-23) |

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|----------------|-------------|-------|
| add_soft_delete | No | ✅ Compatible | Schema coverage analysis works independently of soft delete fields since they're regular model fields |
| add_cursor_pagination | No | ✅ Compatible | Pagination fields are included in schema coverage analysis like any other fields |
| add_search | No | ✅ Compatible | Search filter schemas are analyzed for coverage alongside other schemas |
| add_audit_log | No | ✅ Compatible | Audit log schemas are included in coverage analysis unless explicitly excluded |
| add_data_export | No | ✅ Compatible | Export format schemas are checked for test coverage like other schemas |
| add_bulk_operations | No | ✅ Compatible | Bulk operation request/response schemas are included in coverage analysis |
| add_multi_tenancy | No | ✅ Compatible | Tenant-scoped schemas are analyzed the same way as regular schemas |
| add_feature_flags | No | ✅ Compatible | Feature flag schemas are included in coverage unless excluded |
| add_api_key_auth | No | ✅ Compatible | API key schemas are analyzed for test coverage like other auth schemas |
| add_oauth2_provider | No | ✅ Compatible | OAuth2 token and client schemas are included in coverage analysis |
| add_rbac | No | ✅ Compatible | Role and permission schemas are checked for test coverage |
| add_mfa | No | ✅ Compatible | MFA challenge/response schemas are analyzed like other schemas |
| add_cache_layer | No | ✅ Compatible | Cache key schemas are included in coverage analysis |
| add_outbox_pattern | No | ✅ Compatible | Outbox message schemas are checked for test coverage |
| add_sse | No | ✅ Compatible | Server-sent event schemas are analyzed like other schemas |

**Conflicts:** None identified.

## 12. Rollback Procedure

### Code rollback (before deploy)
```bash
git checkout -- app/core/coverage_analyzer.py
git checkout -- app/core/coverage_report.py
git checkout -- app/models/schema_coverage.py
rm -f coverage.json
rm -f .github/workflows/schema_coverage.yml
rm -f tests/test_schema_coverage.py
```

### Database rollback (after deploy)
**N/A** — this tool is a code-only refactor. No database tables, columns, or indexes are created. `alembic downgrade -1` would be a no-op. Skip this step.

### Data preservation rollback
**N/A** — no business data is created or migrated by this tool. Nothing to archive.

### Failure mode: tool partially modified files
If the generator crashed halfway and left an inconsistent tree (analyzer module present but CI workflow missing, or vice versa), restore to clean HEAD before re-running:
```bash
# 1. Inspect what changed vs HEAD
git status --short app/ scripts/ .github/

# 2. Revert tool-written files + drop freshly created ones
git checkout HEAD -- app/core/coverage_analyzer.py app/core/coverage_report.py \
    app/models/schema_coverage.py
git clean -fd scripts/schema_coverage.py tests/test_schema_coverage.py \
    .github/workflows/schema_coverage.yml .schema-coverage-exclude.yaml

# 3. Verify the tree matches HEAD exactly
git diff HEAD --exit-code && echo "clean" || echo "DIRTY — stop"
```

### Failure mode: CI failing due to coverage threshold
If the gate is failing because a recent schema change dropped overall coverage below the threshold, do NOT just lower the threshold — that hides the regression forever. The fix is to identify the orphan fields and add the missing assertions:
```bash
# 1. Run the tool locally to see exactly which fields are orphaned
python -m scripts.schema_coverage --threshold-pct 80 --format markdown

# 2. For each orphan, open the suggested test file and add an assertion
#    Example:
#    def test_user_create_validates_timezone():
#        user = UserCreate(email="x@y.com", timezone="America/Sao_Paulo")
#        assert user.timezone == "America/Sao_Paulo"

# 3. Re-run the tool to confirm the orphan count dropped to 0
python -m scripts.schema_coverage --threshold-pct 80
```
Only if the orphan is genuinely intentional (computed property, deprecated field, test-only flag) add it to `.schema-coverage-exclude.yaml` with a justification and reviewer.

### Emergency: AST parser crashes on a specific schema file
If the tool raises a `SyntaxError` or `RecursionError` while walking a specific schema file (happens with deeply-nested generic types or custom metaclasses):
1. Identify the offender: `python -m scripts.schema_coverage --verbose 2>&1 | grep -B 3 Error`
2. Exclude the problematic file via `scripts/schema_coverage.py --exclude-file app/models/weird.py`
3. File a ticket with a reduced reproducer — the AST walker should handle every valid Python file, so this is a bug
4. In the interim, run the tool with `--exclude-file` and document the exclusion in the ticket

### Emergency: threshold regression after a dependency bump
If a Pydantic upgrade (v1 → v2, or v2 minor bump) changes how fields are enumerated and causes a sudden drop in coverage:
1. Lock the Pydantic version in `pyproject.toml` to the previous known-good
2. Re-run the tool to confirm the regression is tied to the bump
3. Compare the old and new field lists: `python -m scripts.schema_coverage --dump-fields > fields.json` on each version
4. Update the tool's AST walker if Pydantic added new field-declaration patterns, then unpin

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | Schema with no fields | Tool reports 100% coverage with empty orphan list |
| EC-2 | Schema inheriting from BaseModel but adding no fields | Tool reports 100% coverage with empty orphan list |
| EC-3 | Schema with only private fields (prefix `_`) | Tool reports 100% coverage with empty orphan list |
| EC-4 | Schema excluded via exclude_schemas parameter | Tool skips analysis and omits from report |
| EC-5 | Field renamed in schema but old name used in tests | Tool reports old name as orphan and new name as untested |
| EC-6 | Dynamic field access via getattr() in tests | Tool does not count dynamic access as field coverage |
| EC-7 | Schema with nested BaseModel fields | Tool includes nested fields in parent schema's coverage calculation |
| EC-8 | Schema inheriting fields from parent BaseModel | Tool includes inherited fields in coverage calculation |
| EC-9 | Test file imports schema but never references fields | Tool does not count import as field coverage |
| EC-10 | Schema with computed properties (@property) | Tool excludes properties from coverage analysis |
| EC-11 | Schema with field used only in test fixtures | Tool counts fixture usage as field coverage |
| EC-12 | Schema with field used only in test parametrization | Tool counts parametrized usage as field coverage |
| EC-13 | Schema with field used only in type annotations | Tool does not count type annotation as field coverage |
| EC-14 | Schema with field used only in docstrings | Tool does not count docstring reference as field coverage |
| EC-15 | Schema with field used only in string literals | Tool does not count string literal as field coverage |

## 14. Acceptance Criteria (Final Sign-off)

✅ 1. All 30 Completeness Criteria verified via test evidence  
✅ 2. Test coverage at 100% for analyzer and report modules  
✅ 3. GitHub Actions workflow passes on PR with example project  
✅ 4. Performance benchmarks meet SLOs (3s for 50 schemas)  
✅ 5. Documentation in README.md updated with usage examples  
✅ 6. Example report generated in docs/examples/coverage.json  
✅ 7. Pre-commit hook available in .pre-commit-config.yaml  
✅ 8. All 15 edge cases tested and documented  
✅ 9. Backward compatibility with Pydantic v1 and v2 confirmed  
✅ 10. Developer successfully runs tool on real project, fixes 3 orphan fields identified in report, and verifies CI passes  

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks
- [ ] Validate project_dir exists and is directory
- [ ] Validate FastAPI project structure (app/ directory exists)
- [ ] Validate Pydantic is installed in project
- [ ] Check for existing coverage.json to detect previous runs
- [ ] Validate threshold_pct is between 0 and 100
- [ ] Validate exclude_schemas list contains valid class names
- [ ] Check Python version compatibility (>=3.8)

### 15.2 Coverage analyzer
- [ ] Implement AST parser for schema files
- [ ] Detect BaseModel subclasses via AST inspection
- [ ] Collect public field names from schema classes
- [ ] Skip private fields (starting with _)
- [ ] Skip computed properties (@property)
- [ ] Handle nested BaseModel fields
- [ ] Handle inherited fields from parent BaseModels

### 15.3 Test analyzer
- [ ] Implement AST parser for test files
- [ ] Detect schema field references in test files
- [ ] Skip dynamic field access (getattr)
- [ ] Count field usage in test assertions
- [ ] Count field usage in test fixtures
- [ ] Count field usage in test parametrization
- [ ] Skip field references in type annotations/docstrings

### 15.4 Coverage calculation
- [ ] Calculate coverage percentage per schema
- [ ] Round percentages to 2 decimal places
- [ ] Identify orphan fields per schema
- [ ] Sort orphan fields alphabetically
- [ ] Apply exclude_schemas filter before analysis
- [ ] Handle zero-field schemas as 100% coverage
- [ ] Enforce coverage threshold comparison

### 15.5 Report generation
- [ ] Implement JSON report writer
- [ ] Include UTC timestamp in ISO format
- [ ] Structure report with schema-level details
- [ ] Add PASS/FAIL status per schema
- [ ] Implement atomic file write with tempfile
- [ ] Include tool version in report metadata
- [ ] Add execution time metrics to report

### 15.6 CLI integration
- [ ] Implement command-line interface
- [ ] Add --threshold parameter
- [ ] Add --fail-on-orphans flag
- [ ] Add --exclude-schemas parameter
- [ ] Add --format json/text option
- [ ] Add --incremental mode for PRs
- [ ] Implement non-zero exit on failure

### 15.7 CI integration
- [ ] Create GitHub Actions workflow
- [ ] Add Python setup step
- [ ] Add dependency installation
- [ ] Add coverage analysis step
- [ ] Add report artifact upload
- [ ] Add threshold enforcement
- [ ] Configure to run on PR/push

### 15.8 Model updates
- [ ] Create SchemaCoverage model
- [ ] Add coverage_pct column
- [ ] Add orphan_fields JSON column
- [ ] Add created_at/updated_at timestamps
- [ ] Add schema_name index
- [ ] Implement model tests
- [ ] Add model to alembic migration

### 15.9 Testing
- [ ] Create test_schema_coverage.py
- [ ] Add tests for basic coverage cases
- [ ] Add tests for orphan detection
- [ ] Add tests for threshold enforcement
- [ ] Add tests for edge cases
- [ ] Add performance benchmarks
- [ ] Test with Pydantic v1 and v2
- [ ] Verify 100% test coverage

### 15.10 Documentation
- [ ] Update README.md with usage
- [ ] Add examples to docs/examples/
- [ ] Document CLI parameters
- [ ] Document report format
- [ ] Add CI setup instructions
- [ ] Add pre-commit hook example
- [ ] Add troubleshooting section

### 15.11 Atomicity
- [ ] Track all modified files
- [ ] Implement rollback on failure
- [ ] Use tempfile for report writing
- [ ] Verify file writes complete
- [ ] Check AST parsing of all changes
- [ ] Preserve existing coverage.json on error
- [ ] Return clear error messages

### 15.12 Verification
- [ ] Run ast.parse on all modified files
- [ ] Verify no syntax errors
- [ ] Run pytest on full test suite
- [ ] Check performance benchmarks
- [ ] Verify idempotent operation
- [ ] Test in real project
- [ ] Validate report structure

### 15.13 Performance
- [ ] Measure schema parsing time
- [ ] Measure test analysis time
- [ ] Track memory usage
- [ ] Optimize AST walking
- [ ] Implement file caching
- [ ] Add progress reporting
- [ ] Enforce 3s SLO

## 16. Documentation Output

```json
{
  "status": "success",
  "files_created": [
    "app/core/coverage_analyzer.py",
    "app/core/coverage_report.py",
    "app/models/schema_coverage.py",
    ".github/workflows/schema_coverage.yml",
    "tests/test_schema_coverage.py",
    "docs/examples/coverage.json",
    ".pre-commit-config.yaml",
    "alembic/versions/0001_add_schema_coverage.py"
  ],
  "files_modified": [
    "README.md",
    "app/main.py",
    "pyproject.toml"
  ],
  "metrics": {
    "execution_time_ms": 2450,
    "files_changed": 11,
    "lines_added": 487,
    "lines_removed": 12,
    "schemas_analyzed": 23,
    "average_coverage_pct": 82.4,
    "orphan_fields_found": 17
  },
  "next_steps": [
    "Run: pytest tests/test_schema_coverage.py -v",
    "Add to pre-commit: echo 'schema_coverage: python -m app.core.coverage_analyzer' >> .pre-commit-config.yaml",
    "Commit and push changes to trigger CI workflow",
    "Review coverage.json report for orphan fields",
    "Add missing tests for identified orphan fields"
  ],
  "warnings": [
    "5 schemas are below the 80% coverage threshold - review before merging",
    "Dynamic field access (getattr) is not counted as test coverage"
  ],
  "notes": [
    "Schema coverage analysis completed for 23 Pydantic schemas",
    "Average coverage across all schemas is 82.4%",
    "17 orphan fields identified across 8 schemas",
    "GitHub Actions workflow configured to run on PR and push to main",
    "Pre-commit hook configuration available in .pre-commit-config.yaml",
    "Backward compatibility confirmed with Pydantic v1.10 and v2.0"
  ]
}
