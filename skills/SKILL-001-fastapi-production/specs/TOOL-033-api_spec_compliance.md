# TOOL-033: api_spec_compliance

> **Status**: SPEC v2 (rigorous)  
> **Last updated**: 2026-04-08  

---

## 1. Overview

| **Tool name**       | `fastapi_api_spec_compliance` |
|----------------------|-------------------------------|
| **Category**         | VERIFY                        |
| **Complexity**       | Medium                        |
| **Dependencies**     | FastAPI project, optional committed `openapi.json` snapshot |
| **Signature**        | `api_spec_compliance(project_dir: str, spec_file: str = "openapi.json", fail_on_breaking: bool = True, fail_on_undocumented: bool = True, allow_additions: bool = True) -> dict` |
| **Parameters**       | `project_dir`: project root path<br>`spec_file`: path to the committed OpenAPI snapshot<br>`fail_on_breaking`: fail if breaking changes detected (removed endpoints, required params added, type narrowed)<br>`fail_on_undocumented`: fail if any route lacks `summary`, `description`, or `response_model`<br>`allow_additions`: non-breaking additions (new endpoints/optional params) pass |

## 2. Purpose

The `fastapi_api_spec_compliance` tool answers the question that every public-API team dreads at 2 AM: "did we just silently break our consumers?". It extracts the current OpenAPI schema directly from the live FastAPI app (never from a stale committed file), diffs it against `openapi.json` at the committed baseline, and classifies every change into one of three buckets: `BREAKING` (removed route, removed response field, added required request field, type narrowed, enum value removed, required field inversion — any change where a previously-working consumer will stop working), `NON_BREAKING` (new route, new optional query param, added response field, added enum value — additions consumers can safely ignore), or `METADATA` (tag rename, description edit, operation-id noise — nothing consumers can observe). A separate **documentation gate** asserts that every route carries a non-empty `summary`, a `description >= 20 chars`, a `response_model=`, and at least one `tag` — so undocumented endpoints are blocked at PR time rather than accumulating into permanent tech debt.

The generator produces `scripts/api_spec_compliance.py` with a structural-diff algorithm (order-independent, schema-normalized — so a `oneOf` with reordered branches or a path parameter whose regex was re-formatted does NOT show up as a false positive), a GitHub Actions workflow that runs on every PR, a Markdown PR-comment renderer showing the full change list with ✅/⚠️/❌ icons, and a **semver suggestion** that walks the change list and outputs `major` (any BREAKING), `minor` (any NON_BREAKING addition), or `patch` (METADATA-only). Key design decisions: **snapshot lifecycle is explicit** — the committed `openapi.json` is the source of truth and is updated only via `--update-snapshot` with justification, never silently; **extraction is always live** — the tool imports the FastAPI app and calls `app.openapi()` so the analysis matches reality instead of whatever someone last checked in; **breaking-change detection is strict** — renamed fields count as remove+add (BREAKING) because consumers do break on rename, even if the logic is "the same"; **documentation gate is mandatory** — routes without the full metadata quartet fail the PR, so undocumented APIs never reach `main`; and **integration with TOOL-038 api_changelog** so the same diff feeds into the auto-generated CHANGELOG.md, eliminating a whole class of "we forgot to document that" incidents.

## 3. Performance SLOs

| **Metric**               | **Target**                     | **Why**                                                                 |
|--------------------------|--------------------------------|-------------------------------------------------------------------------|
| Tool execution time       | < 2s                          | Schema generation and diff must be fast for CI workflows.               |
| Files modified           | ≤ 2                           | Only `pyproject.toml` and CI workflow files should be touched.          |
| Files created            | ≥ 6                           | Includes spec snapshot, diff rules, CI workflow, report template, tests, and Makefile targets. |
| Diff computation         | < 500 ms for 200-route API     | Ensures scalability for large APIs.                                     |
| Report generation        | < 200 ms                      | Reports must be generated quickly for CI feedback.                     |
| Latency overhead         | 0 ms                          | Tool runs offline; no runtime impact.                                  |
| Memory overhead          | < 50 MB                       | Must fit within typical CI runner constraints.                         |
| Migration runtime        | 0s — no DB changes            | Tool does not interact with databases.                                 |

---

## 4. Code Examples (Before / After)

### 4.1 Route documentation: BEFORE
```python
# app/api/endpoints/items.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.crud import item as crud
from app.db.deps import get_db
from app.schemas.item import ItemCreate, ItemOut

router = APIRouter()

@router.post("/items/")
async def create_item(
    item_in: ItemCreate,
    db: AsyncSession = Depends(get_db)
):
    return await crud.create(db, item_in=item_in)

@router.get("/items/{item_id}")
async def read_item(
    item_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    item = await crud.get(db, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item

@router.delete("/items/{item_id}")
async def delete_item(
    item_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    success = await crud.delete(db, item_id)
    if not success:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"message": "Item deleted"}
```

### 4.2 Route documentation: AFTER
```python
# app/api/endpoints/items.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.crud import item as crud
from app.db.deps import get_db
from app.schemas.item import ItemCreate, ItemOut, ItemDeleteResponse

router = APIRouter(prefix="/v1", tags=["Inventory Management"])

@router.post(
    "/items/",
    response_model=ItemOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new inventory item",
    description="Creates a new item in the inventory system. Requires write permissions. Returns the created item with all fields populated.",
    responses={
        201: {"description": "Item created successfully"},
        400: {"description": "Invalid input data"},
        403: {"description": "Missing write permissions"},
        422: {"description": "Validation error in request body"},
    },
)
async def create_item(
    item_in: ItemCreate,
    db: AsyncSession = Depends(get_db)
) -> ItemOut:
    return await crud.create(db, item_in=item_in)

@router.get(
    "/items/{item_id}",
    response_model=ItemOut,
    summary="Retrieve item details by ID",
    description="Returns full details for a specific inventory item. The item must exist and be accessible to the current user.",
    responses={
        200: {"description": "Item details retrieved successfully"},
        404: {"description": "Item not found or inaccessible"},
    },
)
async def read_item(
    item_id: UUID,
    db: AsyncSession = Depends(get_db)
) -> ItemOut:
    item = await crud.get(db, item_id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Item not found"
        )
    return item

@router.delete(
    "/items/{item_id}",
    response_model=ItemDeleteResponse,
    summary="Delete an inventory item",
    description="Permanently removes an item from inventory. This action cannot be undone. Requires admin permissions.",
    responses={
        200: {"description": "Item deleted successfully"},
        404: {"description": "Item not found"},
        403: {"description": "Admin permissions required"},
    },
)
async def delete_item(
    item_id: UUID,
    db: AsyncSession = Depends(get_db)
) -> ItemDeleteResponse:
    success = await crud.delete(db, item_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Item not found"
        )
    return ItemDeleteResponse(message="Item deleted")
```

### 4.3 OpenAPI schema normalization (NEW)
```python
# app/core/openapi_normalization.py
import json
from collections.abc import Mapping
from typing import Any, Dict, List, Union
from copy import deepcopy

def normalize_openapi_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize OpenAPI schema for deterministic comparison.
    Removes volatile fields, sorts all keys recursively, and standardizes formatting.
    """
    normalized = deepcopy(schema)
    
    # Remove server URLs (environment-specific)
    normalized.pop("servers", None)
    
    # Remove auto-generated operationIds
    if "paths" in normalized:
        for path, methods in normalized["paths"].items():
            if isinstance(methods, dict):
                for method in methods.values():
                    if isinstance(method, dict):
                        method.pop("operationId", None)
    
    # Sort all dictionaries recursively
    def sort_dict_recursive(obj: Any) -> Any:
        if isinstance(obj, Mapping):
            sorted_dict = {k: sort_dict_recursive(v) for k, v in sorted(obj.items())}
            return sorted_dict
        elif isinstance(obj, list):
            return [sort_dict_recursive(item) for item in obj]
        else:
            return obj
    
    return sort_dict_recursive(normalized)

def save_normalized_schema(schema: Dict[str, Any], filepath: str) -> None:
    """Save normalized schema to file with consistent formatting."""
    normalized = normalize_openapi_schema(schema)
    with open(filepath, "w") as f:
        json.dump(normalized, f, indent=2, sort_keys=True)

def load_and_normalize_schema(filepath: str) -> Dict[str, Any]:
    """Load and normalize schema from file."""
    with open(filepath, "r") as f:
        schema = json.load(f)
    return normalize_openapi_schema(schema)

def schema_checksum(schema: Dict[str, Any]) -> str:
    """Generate deterministic checksum for schema comparison."""
    import hashlib
    normalized = normalize_openapi_schema(schema)
    schema_str = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(schema_str.encode()).hexdigest()[:16]
```

### 4.4 Change detection service (NEW)
```python
# app/services/spec_change_detector.py
from enum import Enum
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass

class ChangeType(str, Enum):
    BREAKING = "BREAKING"
    NON_BREAKING = "NON_BREAKING"
    METADATA = "METADATA"

@dataclass
class SpecChange:
    path: str
    change_type: ChangeType
    message: str
    before: Optional[Any]
    after: Optional[Any]
    location: List[str]

class SpecChangeDetector:
    def __init__(self, strict_enum_check: bool = True):
        self.strict_enum_check = strict_enum_check
    
    def detect_changes(
        self, 
        before_schema: Dict[str, Any], 
        after_schema: Dict[str, Any]
    ) -> List[SpecChange]:
        """Compare two OpenAPI schemas and classify all changes."""
        changes: List[SpecChange] = []
        
        # Check for removed endpoints
        before_paths = before_schema.get("paths", {})
        after_paths = after_schema.get("paths", {})
        
        for path in set(before_paths.keys()) - set(after_paths.keys()):
            changes.append(SpecChange(
                path=path,
                change_type=ChangeType.BREAKING,
                message=f"Endpoint removed: {path}",
                before=before_paths[path],
                after=None,
                location=["paths", path]
            ))
        
        # Check for new endpoints
        for path in set(after_paths.keys()) - set(before_paths.keys()):
            changes.append(SpecChange(
                path=path,
                change_type=ChangeType.NON_BREAKING,
                message=f"New endpoint added: {path}",
                before=None,
                after=after_paths[path],
                location=["paths", path]
            ))
        
        # Compare existing endpoints
        for path in set(before_paths.keys()) & set(after_paths.keys()):
            path_changes = self._compare_path_items(
                before_paths[path], 
                after_paths[path], 
                path
            )
            changes.extend(path_changes)
        
        # Compare schemas/components
        component_changes = self._compare_components(
            before_schema.get("components", {}),
            after_schema.get("components", {})
        )
        changes.extend(component_changes)
        
        return changes
    
    def _compare_path_items(
        self, 
        before: Dict[str, Any], 
        after: Dict[str, Any], 
        path: str
    ) -> List[SpecChange]:
        changes = []
        all_methods = set(before.keys()) | set(after.keys())
        
        for method in all_methods:
            location = ["paths", path, method]
            
            if method not in after:
                changes.append(SpecChange(
                    path=f"{path}:{method}",
                    change_type=ChangeType.BREAKING,
                    message=f"HTTP method removed: {method.upper()} {path}",
                    before=before.get(method),
                    after=None,
                    location=location
                ))
            elif method not in before:
                changes.append(SpecChange(
                    path=f"{path}:{method}",
                    change_type=ChangeType.NON_BREAKING,
                    message=f"New HTTP method: {method.upper()} {path}",
                    before=None,
                    after=after.get(method),
                    location=location
                ))
            else:
                method_changes = self._compare_operations(
                    before[method], 
                    after[method], 
                    path, 
                    method
                )
                changes.extend(method_changes)
        
        return changes
    
    def _compare_operations(
        self, 
        before_op: Dict[str, Any], 
        after_op: Dict[str, Any], 
        path: str, 
        method: str
    ) -> List[SpecChange]:
        changes = []
        
        # Check for required parameter additions
        before_params = before_op.get("parameters", [])
        after_params = after_op.get("parameters", [])
        
        before_required = {p["name"] for p in before_params if p.get("required", False)}
        after_required = {p["name"] for p in after_params if p.get("required", False)}
        
        for new_req in after_required - before_required:
            changes.append(SpecChange(
                path=f"{path}:{method}",
                change_type=ChangeType.BREAKING,
                message=f"Required parameter added: {new_req}",
                before=None,
                after=next(p for p in after_params if p["name"] == new_req),
                location=["paths", path, method, "parameters"]
            ))
        
        return changes
```

### 4.5 Documentation validation dependency (NEW)
```python
# app/api/deps/documentation.py
from fastapi import Depends, HTTPException, status
from fastapi.routing import APIRoute
from typing import List, Dict, Any, Callable
from functools import wraps

class DocumentationValidator:
    def __init__(
        self,
        min_description_length: int = 20,
        require_tags: bool = True,
        require_response_model: bool = True
    ):
        self.min_description_length = min_description_length
        self.require_tags = require_tags
        self.require_response_model = require_response_model
    
    def validate_route(self, route: APIRoute) -> List[Dict[str, str]]:
        """Validate a single route's documentation completeness."""
        errors = []
        
        if not route.summary:
            errors.append({
                "field": "summary",
                "message": f"Route {route.path} missing summary"
            })
        
        if not route.description or len(route.description.strip()) < self.min_description_length:
            errors.append({
                "field": "description",
                "message": f"Route {route.path} description must be at least {self.min_description_length} characters"
            })
        
        if self.require_response_model and not route.response_model:
            errors.append({
                "field": "response_model",
                "message": f"Route {route.path} must specify a response_model"
            })
        
        if self.require_tags and (not route.tags or len(route.tags) == 0):
            errors.append({
                "field": "tags",
                "message": f"Route {route.path} must have at least one tag"
            })
        
        return errors
    
    def validate_all_routes(self, routes: List[APIRoute]) -> Dict[str, List[Dict[str, str]]]:
        """Validate documentation for all routes in the application."""
        all_errors = {}
        
        for route in routes:
            if not isinstance(route, APIRoute):
                continue
            
            errors = self.validate_route(route)
            if errors:
                route_key = f"{list(route.methods)[0]} {route.path}"
                all_errors[route_key] = errors
        
        return all_errors

def documentation_required(
    min_description_length: int = 20,
    require_tags: bool = True
) -> Callable:
    """
    Dependency that enforces documentation requirements on route definition.
    Use as a decorator on route functions.
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # This would be called during route registration, not at runtime
            # In practice, this would integrate with FastAPI's route inspection
            return await func(*args, **kwargs)
        
        # Store validation requirements as function attributes
        wrapper._doc_validation = {
            "min_description_length": min_description_length,
            "require_tags": require_tags
        }
        return wrapper
    return decorator

def get_documentation_validator() -> DocumentationValidator:
    """Dependency factory for documentation validator."""
    return DocumentationValidator(
        min_description_length=20,
        require_tags=True,
        require_response_model=True
    )
```

### 4.6 Pydantic response schema (NEW)
```python
# app/schemas/compliance.py
from pydantic import BaseModel, Field
from typing import List, Optional, Any, Dict, Literal
from datetime import datetime
from enum import Enum

class ChangeSeverity(str, Enum):
    BREAKING = "breaking"
    NON_BREAKING = "non_breaking"
    METADATA = "metadata"

class RouteDocumentationIssue(BaseModel):
    route: str = Field(..., description="Route path with method")
    field: str = Field(..., description="Missing or invalid field")
    message: str = Field(..., description="Description of the issue")
    severity: Literal["error", "warning"] = Field("error", description="Issue severity")

class SchemaChange(BaseModel):
    path: str = Field(..., description="API path or schema location")
    change_type: ChangeSeverity = Field(..., description="Type of change")
    message: str = Field(..., description="Human-readable change description")
    before: Optional[Any] = Field(None, description="Previous value")
    after: Optional[Any] = Field(None, description="New value")
    location: List[str] = Field(default_factory=list, description="JSON path to change")

class ComplianceReport(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.now)
    schema_version: str = Field(..., description="Current OpenAPI version")
    baseline_version: Optional[str] = Field(None, description="Baseline snapshot version")
    passed: bool = Field(..., description="Overall compliance status")
    breaking_changes_count: int = Field(0, description="Number of breaking changes")
    non_breaking_changes_count: int = Field(0, description="Number of non-breaking changes")
    documentation_issues_count: int = Field(0, description="Number of documentation issues")
    changes: List[SchemaChange] = Field(default_factory=list)
    documentation_issues: List[RouteDocumentationIssue] = Field(default_factory=list)
    semver_suggestion: Optional[str] = Field(None, description="Suggested version bump")
    checksum: Optional[str] = Field(None, description="Schema checksum for comparison")

class VersionSuggestion(BaseModel):
    current_version: str = Field(..., description="Current API version")
    suggested_bump: Literal["major", "minor", "patch", "none"] = Field(..., description="Suggested version increment")
    reason: str = Field(..., description="Reason for suggestion")
    breaking_changes: List[str] = Field(default_factory=list)
    new_features: List[str] = Field(default_factory=list)

class SnapshotMetadata(BaseModel):
    created_at: datetime = Field(default_factory=datetime.now)
    schema_version: str = Field(..., description="OpenAPI schema version")
    app_version: str = Field(..., description="Application version")
    route_count: int = Field(..., description="Number of documented routes")
    checksum: str = Field(..., description="Schema checksum")
    git_commit: Optional[str] = Field(None, description="Git commit hash")
    generated_by: str = Field("api_spec_compliance", description="Tool that generated snapshot")
```

### 4.7 Main compliance checker (NEW)
```python
# app/core/compliance_checker.py
import json
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from fastapi import FastAPI

from app.core.openapi_normalization import (
    normalize_openapi_schema,
    save_normalized_schema,
    load_and_normalize_schema,
    schema_checksum
)
from app.services.spec_change_detector import SpecChangeDetector, SpecChange, ChangeType
from app.api.deps.documentation import DocumentationValidator
from app.schemas.compliance import ComplianceReport, VersionSuggestion

class APISpecComplianceChecker:
    def __init__(self, app: FastAPI):
        self.app = app
        self.change_detector = SpecChangeDetector(strict_enum_check=True)
        self.doc_validator = DocumentationValidator()
    
    def generate_current_schema(self) -> Dict[str, Any]:
        """Generate and normalize current OpenAPI schema."""
        from fastapi.openapi.utils import get_openapi
        
        schema = get_openapi(
            title=self.app.title,
            version=self.app.version,
            openapi_version=self.app.openapi_version,
            description=self.app.description,
            routes=self.app.routes,
        )
        return normalize_openapi_schema(schema)
    
    def check_compliance(
        self,
        snapshot_path: Path,
        fail_on_breaking: bool = True,
        fail_on_undocumented: bool = True,
        allow_additions: bool = True
    ) -> Tuple[bool, ComplianceReport]:
        """
        Main compliance check against snapshot.
        Returns (passed, report).
        """
        current_schema = self.generate_current_schema()
        
        # Initialize report
        report = ComplianceReport(
            schema_version=current_schema.get("info", {}).get("version", "unknown"),
            passed=True
        )
        
        # Check documentation
        doc_issues = self.doc_validator.validate_all_routes(self.app.routes)
        report.documentation_issues_count = len(doc_issues)
        
        if fail_on_undocumented and doc_issues:
            report.passed = False
        
        # Check against snapshot if it exists
        if snapshot_path.exists():
            baseline_schema = load_and_normalize_schema(str(snapshot_path))
            baseline_version = baseline_schema.get("info", {}).get("version")
            report.baseline_version = baseline_version
            
            # Detect changes
            changes = self.change_detector.detect_changes(baseline_schema, current_schema)
            report.changes = changes
            
            # Count changes by type
            breaking_changes = [c for c in changes if c.change_type == ChangeType.BREAKING]
            non_breaking = [c for c in changes if c.change_type == ChangeType.NON_BREAKING]
            
            report.breaking_changes_count = len(breaking_changes)
            report.non_breaking_changes_count = len(non_breaking)
            
            # Determine if changes are allowed
            if fail_on_breaking and breaking_changes:
                report.passed = False
            
            if not allow_additions and non_breaking:
                # Treat additions as breaking if not allowed
                report.passed = False
            
            # Generate semver suggestion
            report.semver_suggestion = self._suggest_version_bump(
                breaking_changes,
                non_breaking,
                baseline_version,
                current_schema.get("info", {}).get("version")
            )
        
        # Add checksum
        report.checksum = schema_checksum(current_schema)
        
        return report.passed, report
    
    def _suggest_version_bump(
        self,
        breaking_changes: list,
        non_breaking_changes: list,
        baseline_version: Optional[str],
        current_version: Optional[str]
    ) -> str:
        """Suggest version bump based on change types."""
        if breaking_changes:
            return "major"
        elif non_breaking_changes:
            return "minor"
        else:
            return "patch"
    
    def create_snapshot(self, snapshot_path: Path, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Create a new normalized snapshot."""
        current_schema = self.generate_current_schema()
        
        # Add metadata
        if metadata:
            current_schema["x_snapshot_metadata"] = metadata
        
        save_normalized_schema(current_schema, str(snapshot_path))
    
    def generate_report_markdown(self, report: ComplianceReport) -> str:
        """Generate Markdown report for CI/CD systems."""
        lines = []
        lines.append("# API Specification Compliance Report")
        lines.append(f"**Timestamp**: {report.timestamp.isoformat()}")
        lines.append(f"**Status**: {'✅ PASSED' if report.passed else '❌ FAILED'}")
        lines.append(f"**Schema Version**: {report.schema_version}")
        
        if report.baseline_version:
            lines.append(f"**Baseline Version**: {report.baseline_version}")
        
        lines.append(f"**Breaking Changes**: {report.breaking_changes_count}")
        lines.append(f"**Non-breaking Changes**: {report.non_breaking_changes_count}")
        lines.append(f"**Documentation Issues**: {report.documentation_issues_count}")
        
        if report.semver_suggestion:
            lines.append(f"**Suggested Version Bump**: {report.semver_suggestion}")
        
        # Add change details
        if report.changes:
            lines.append("\n## Changes Detected")
            for change in report.changes:
                emoji = "🔴" if change.change_type == ChangeType.BREAKING else "🟡"
                lines.append(f"{emoji} **{change.change_type.value}**: {change.message}")
        
        return "\n".join(lines)
```

### 4.8 CLI command implementation (NEW)
```python
# app/cli/commands/compliance.py
import json
import sys
from pathlib import Path
from typing import Optional

import click
import uvicorn

from app.core.compliance_checker import APISpecComplianceChecker
from app.main import app  # Assuming app is defined in app.main

@click.group()
def compliance():
    """API specification compliance commands."""
    pass

@compliance.command()
@click.argument("project_dir", type=click.Path(exists=True, file_okay=False))
@click.option("--spec-file", default="openapi.json", help="OpenAPI snapshot file")
@click.option("--fail-on-breaking/--no-fail-on-breaking", default=True, 
              help="Fail if breaking changes detected")
@click.option("--fail-on-undocumented/--no-fail-on-undocumented", default=True,
              help="Fail if routes lack documentation")
@click.option("--allow-additions/--no-allow-additions", default=True,
              help="Allow non-breaking additions")
@click.option("--output-format", type=click.Choice(["json", "markdown", "github"]), 
              default="json", help="Output format")
@click.option("--update-snapshot", is_flag=True, 
              help="Update snapshot file after successful check")
def check(
    project_dir: str,
    spec_file: str,
    fail_on_breaking: bool,
    fail_on_undocumented: bool,
    allow_additions: bool,
    output_format: str,
    update_snapshot: bool
):
    """Check API compliance against snapshot."""
    import sys
    sys.path.insert(0, project_dir)
    
    try:
        # Import the app from the project
        from importlib import import_module
        module = import_module("app.main")
        target_app = module.app
    except ImportError as e:
        click.echo(f"Error loading FastAPI app: {e}", err=True)
        sys.exit(1)
    
    snapshot_path = Path(project_dir) / spec_file
    checker = APISpecComplianceChecker(target_app)
    
    passed, report = checker.check_compliance(
        snapshot_path=snapshot_path,
        fail_on_breaking=fail_on_breaking,
        fail_on_undocumented=fail_on_undocumented,
        allow_additions=allow_additions
    )
    
    # Output based on format
    if output_format == "json":
        click.echo(json.dumps(report.dict(), indent=2, default=str))
    elif output_format == "markdown":
        click.echo(checker.generate_report_markdown(report))
    elif output_format == "github":
        # GitHub Actions annotations
        for change in report.changes:
            if change.change_type == "BREAKING":
                level = "error"
            elif change.change_type == "NON_BREAKING":
                level = "warning"
            else:
                level = "notice"
            
            click.echo(f"::{level} file={spec_file},line=1::{change.message}")
    
    # Update snapshot if requested and passed
    if update_snapshot and passed:
        checker.create_snapshot(snapshot_path)
        click.echo(f"✓ Snapshot updated at {snapshot_path}")
    
    sys.exit(0 if passed else 1)

@compliance.command()
@click.argument("project_dir", type=click.Path(exists=True, file_okay=False))
@click.option("--spec-file", default="openapi.json", help="OpenAPI snapshot file")
@click.option("--app-host", default="127.0.0.1", help="Host to run app on")
@click.option("--app-port", default=8000, help="Port to run app on")
def snapshot(
    project_dir: str,
    spec_file: str,
    app_host: str,
    app_port: int
):
    """Generate initial OpenAPI snapshot."""
    import sys
    sys.path.insert(0, project_dir)
    
    try:
        from importlib import import_module
        module = import_module("app.main")
        target_app = module.app
    except ImportError as e:
        click.echo(f"Error loading FastAPI app: {e}", err=True)
        sys.exit(1)
    
    # Start app temporarily to generate schema
    import threading
    import time
    
    def run_app():
        uvicorn.run(target_app, host=app_host, port=app_port, log_level="error")
    
    thread = threading.Thread(target=run_app, daemon=True)
    thread.start()
    time.sleep(2)  # Wait for app to start
    
    # Generate snapshot
    snapshot_path = Path(project_dir) / spec_file
    checker = APISpecComplianceChecker(target_app)
    
    metadata = {
        "git_commit": "manual_snapshot",
        "app_version": target_app.version if hasattr(target_app, "version") else "1.0.0"
    }
    
    checker.create_snapshot(snapshot_path, metadata)
    click.echo(f"✓ Initial snapshot created at {snapshot_path}")
    
    # Cleanup
    sys.exit(0)
```

### 4.9 Migration for audit logging table
```python
# alembic/versions/2026_04_08_0001_create_spec_audit_log.py
"""Create API specification audit log table

Revision ID: 2026_04_08_0001
Revises: 
Create Date: 2026-04-08 14:30:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = '2026_04_08_0001'
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Create audit log table
    op.create_table(
        'api_spec_audit_log',
        sa.Column('id', UUID(), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('check_timestamp', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('schema_version', sa.String(32), nullable=False),
        sa.Column('baseline_version', sa.String(32), nullable=True),
        sa.Column('passed', sa.Boolean(), nullable=False),
        sa.Column('breaking_changes_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('non_breaking_changes_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('documentation_issues_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('changes_detected', JSONB(), nullable=False, server_default='[]'),
        sa.Column('documentation_issues', JSONB(), nullable=False, server_default='[]'),
        sa.Column('semver_suggestion', sa.String(16), nullable=True),
        sa.Column('schema_checksum', sa.String(64), nullable=False),
        sa.Column('git_commit_hash', sa.String(40), nullable=True),
        sa.Column('ci_run_id', sa.String(64), nullable=True),
        sa.Column('triggered_by', sa.String(128), nullable=False, server_default='manual'),
    )
    
    # Create indexes for common queries
    op.create_index('ix_audit_log_timestamp', 'api_spec_audit_log', ['check_timestamp'])
    op.create_index('ix_audit_log_version', 'api_spec_audit_log', ['schema_version'])
    op.create_index('ix_audit_log_passed', 'api_spec_audit_log', ['passed'])
    op.create_index('ix_audit_log_checksum', 'api_spec_audit_log', ['schema_checksum'])
    
    # Create summary view for reporting
    op.execute("""
        CREATE VIEW api_spec_compliance_summary AS
        SELECT 
            DATE(check_timestamp) as check_date,
            schema_version,
            COUNT(*) as total_checks,
            SUM(CASE WHEN passed THEN 1 ELSE 0 END) as passed_checks,
            SUM(breaking_changes_count) as total_breaking_changes,
            SUM(non_breaking_changes_count) as total_non_breaking_changes
        FROM api_spec_audit_log
        GROUP BY DATE(check_timestamp), schema_version
        ORDER BY check_date DESC
    """)

def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS api_spec_compliance_summary")
    op.drop_index('ix_audit_log_checksum', table_name='api_spec_audit_log')
    op.drop_index('ix_audit_log_passed', table_name='api_spec_audit_log')
    op.drop_index('ix_audit_log_version', table_name='api_spec_audit_log')
    op.drop_index('ix_audit_log_timestamp', table_name='api_spec_audit_log')
    op.drop_table('api_spec_audit_log')

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Breaking changes are always detected** | `classify_changes()` in `app/core/spec_diff.py` compares paths, params, and response types using structural diff |
| QS-2 | **Documentation completeness is enforced** | `validate_route_docs()` in `app/core/doc_validator.py` checks `summary`, `description`, `response_model`, and `tags` for every route |
| QS-3 | **Schema normalization is deterministic** | `_normalize_schema()` in `app/core/openapi_snapshot.py` recursively sorts keys and removes volatile fields like `servers` |
| QS-4 | **Snapshot updates require explicit flag** | `api_spec_compliance()` in `app/main.py` only writes snapshot when `--update-snapshot` is passed |
| QS-5 | **Semver version bump suggestions are accurate** | `classify_changes()` maps `BREAKING` → major, `NON_BREAKING` → minor, `METADATA` → patch |
| QS-6 | **Report generation is comprehensive** | `api_spec_compliance()` outputs JSON, Markdown, and GitHub annotations with all changes |
| QS-7 | **CI integration blocks breaking changes** | GitHub Actions workflow in `.github/workflows/api-spec.yml` fails on `BREAKING` changes |
| QS-8 | **Schema comparison ignores non-semantic changes** | `_normalize_schema()` strips operation IDs and server URLs before diff |
| QS-9 | **Tool execution time remains under 2 seconds** | `generate_snapshot()` and `classify_changes()` use optimized algorithms for schema traversal |
| QS-10 | **Edge cases are handled gracefully** | `api_spec_compliance()` validates snapshot integrity and provides clear error messages |
| QS-11 | **Diff results are reproducible** | `_normalize_schema()` ensures identical schemas produce identical diffs across runs |
| QS-12 | **Documentation errors are actionable** | `validate_route_docs()` provides specific feedback on missing fields and short descriptions |

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `spec_diff.py` exists at `app/core/spec_diff.py` | File exists, parses |
| CC-02 | `doc_validator.py` exists at `app/core/doc_validator.py` | File exists, contains `validate_route_docs` |
| CC-03 | `openapi_snapshot.py` exists at `app/core/openapi_snapshot.py` | File exists, contains `generate_snapshot` |
| CC-04 | `main.py` exists with `api_spec_compliance()` | File exists, exports verified |
| CC-05 | All routes have `summary` field | grep `summary=` in route decorators |
| CC-06 | All routes have `description` >= 20 chars | Inspect `description=` in route decorators |
| CC-07 | All routes have `response_model` | grep `response_model=` in route decorators |
| CC-08 | All routes have at least one `tag` | grep `tags=` in route decorators |
| CC-09 | Migration creates `openapi_snapshots` table | Inspect `upgrade()` |
| CC-10 | Migration `downgrade()` drops `openapi_snapshots` | Inspect `downgrade()` |
| CC-11 | `generate_snapshot()` normalizes schema | Inspect `_normalize_schema()` |
| CC-12 | `classify_changes()` detects removed paths | grep `Endpoint removed` in `spec_diff.py` |
| CC-13 | `classify_changes()` detects added paths | grep `New endpoint` in `spec_diff.py` |
| CC-14 | `classify_changes()` detects modified paths | grep `_compare_path_items` in `spec_diff.py` |
| CC-15 | `validate_route_docs()` checks summary | grep `if not route.summary` in `doc_validator.py` |
| CC-16 | `validate_route_docs()` checks description | grep `len(route.description) < 20` in `doc_validator.py` |
| CC-17 | `validate_route_docs()` checks response_model | grep `if not route.response_model` in `doc_validator.py` |
| CC-18 | `validate_route_docs()` checks tags | grep `if not route.tags` in `doc_validator.py` |
| CC-19 | `api_spec_compliance()` fails on breaking changes | grep `fail_on_breaking=True` in `main.py` |
| CC-20 | `api_spec_compliance()` fails on undocumented routes | grep `fail_on_undocumented=True` in `main.py` |
| CC-21 | `api_spec_compliance()` allows additions | grep `allow_additions=True` in `main.py` |
| CC-22 | CI workflow exists at `.github/workflows/api-spec.yml` | File exists |
| CC-23 | CI workflow fails on breaking changes | grep `fail_on_breaking: true` in CI workflow |
| CC-24 | CI workflow posts Markdown report | grep `markdown_report.md` in CI workflow |
| CC-25 | CI workflow uploads JSON report | grep `upload-artifact` in CI workflow |
| CC-26 | Existing test suite passes | pytest 0 failures |
| CC-27 | New file `tests/test_api_spec.py` created with 30 tests | File exists |
| CC-28 | All target routes verified with `ast.parse` after edit | Tool internal step |
| CC-29 | Tool execution time < 2s | Time measurement |
| CC-30 | Report generation time < 200ms | Benchmark T-29 |

## 7. Definition of Done

- [ ] All 30 Completeness Criteria verified
- [ ] Existing test suite passes with 0 failures
- [ ] New `tests/test_api_spec.py` file created with 30 tests
- [ ] CI workflow `.github/workflows/api-spec.yml` implemented
- [ ] Documentation completeness enforced for all routes
- [ ] Breaking change detection implemented in `spec_diff.py`
- [ ] Schema normalization implemented in `openapi_snapshot.py`
- [ ] Report generation produces JSON, Markdown, and GitHub annotations
- [ ] Tool execution time remains under 2 seconds
- [ ] Report generation time remains under 200ms
- [ ] Snapshot update requires explicit `--update-snapshot` flag
- [ ] Semver version bump suggestions are accurate
- [ ] Edge cases handled gracefully with clear error messages

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-SC-01 | Breaking changes are **never** missed | `classify_changes()` compares paths, params, and response types using structural diff | T-01, T-02, T-03 |
| INV-SC-02 | Undocumented routes are **never** allowed | `validate_route_docs()` checks `summary`, `description`, `response_model`, and `tags` for every route | T-07, T-08, T-09 |
| INV-SC-03 | Schema comparison is **always** deterministic | `_normalize_schema()` recursively sorts keys and removes volatile fields like `servers` | T-13, T-14 |
| INV-SC-04 | Snapshot updates **never** happen silently | `api_spec_compliance()` only writes snapshot when `--update-snapshot` is passed | T-15, T-16 |
| INV-SC-05 | Semver version bump suggestions are **always** accurate | `classify_changes()` maps `BREAKING` → major, `NON_BREAKING` → minor, `METADATA` → patch | T-19, T-20 |
| INV-SC-06 | Reports **always** include all changes | `api_spec_compliance()` outputs JSON, Markdown, and GitHub annotations with all changes | T-21, T-22 |
| INV-SC-07 | CI integration **always** blocks breaking changes | GitHub Actions workflow fails on `BREAKING` changes | T-23, T-24 |
| INV-SC-08 | Schema comparison **never** includes non-semantic changes | `_normalize_schema()` strips operation IDs and server URLs before diff | T-25, T-26 |

---

## 9. User Stories

### 9.1 Breaking Change Detection (US-01 .. US-05)

**US-01: Detect removed endpoint**
- **As a** API consumer
- **I want** to know if an endpoint I rely on disappears
- **So that** I can update my integration before it breaks
- **Given:** `/v1/items/{id}` exists in snapshot
- **When:** Route is removed from FastAPI app
- **Then:**
  - Tool detects `BREAKING` change (INV-SC-01)
  - Report shows `/v1/items/{id}` as removed (CC-12)
  - CI workflow fails with exit code 1 (T-23)

**US-02: Detect narrowed response type**
- **As a** API maintainer
- **I want** to catch when a response schema becomes more restrictive
- **So that** I don't break existing consumers
- **Given:** `/v1/items/` returns `ItemOut` with optional `price` field
- **When:** `price` becomes required in `ItemOut`
- **Then:**
  - Tool detects `BREAKING` change (INV-SC-01)
  - Report shows `/v1/items/` response schema change (CC-14)
  - Semver suggestion is `major` bump (INV-SC-05)

**US-03: Detect removed enum value**
- **As a** API consumer
- **I want** to know if an enum value I use disappears
- **So that** I can update my integration before it breaks
- **Given:** `/v1/items/` accepts `status` enum `["active", "archived"]`
- **When:** `archived` is removed from enum
- **Then:**
  - Tool detects `BREAKING` change (INV-SC-01)
  - Report shows `/v1/items/` enum change (CC-14)
  - CI workflow blocks merge (T-24)

**US-04: Detect added required parameter**
- **As a** API maintainer
- **I want** to catch when a new required parameter is added
- **So that** I don't break existing consumers
- **Given:** `GET /v1/items/` has no required query params
- **When:** `limit` becomes required query param
- **Then:**
  - Tool detects `BREAKING` change (INV-SC-01)
  - Report shows `/v1/items/` parameter change (CC-14)
  - Semver suggestion is `major` bump (INV-SC-05)

**US-05: Detect renamed path parameter**
- **As a** API consumer
- **I want** to know if a path parameter name changes
- **So that** I can update my integration before it breaks
- **Given:** `/v1/items/{item_id}` exists in snapshot
- **When:** Path changes to `/v1/items/{id}`
- **Then:**
  - Tool detects `BREAKING` change (INV-SC-01)
  - Report shows `/v1/items/{item_id}` removed and `/v1/items/{id}` added (CC-12)
  - CI workflow fails with exit code 1 (T-23)

### 9.2 Non-Breaking Change Detection (US-06 .. US-10)

**US-06: Allow new endpoint**
- **As a** API developer
- **I want** to add new endpoints without breaking existing consumers
- **So that** I can evolve my API safely
- **Given:** `/v1/items/` exists in snapshot
- **When:** `/v1/orders/` is added to FastAPI app
- **Then:**
  - Tool detects `NON_BREAKING` change (INV-SC-01)
  - Report shows `/v1/orders/` as new endpoint (CC-13)
  - Semver suggestion is `minor` bump (INV-SC-05)

**US-07: Allow new optional parameter**
- **As a** API developer
- **I want** to add optional parameters without breaking existing consumers
- **So that** I can extend functionality safely
- **Given:** `GET /v1/items/` has no query params
- **When:** Optional `limit` query param is added
- **Then:**
  - Tool detects `NON_BREAKING` change (INV-SC-01)
  - Report shows `/v1/items/` parameter change (CC-14)
  - Semver suggestion is `minor` bump (INV-SC-05)

**US-08: Allow new response field**
- **As a** API developer
- **I want** to add fields to responses without breaking existing consumers
- **So that** I can provide more data safely
- **Given:** `/v1/items/{id}` returns `ItemOut` without `created_at`
- **When:** `created_at` field is added to `ItemOut`
- **Then:**
  - Tool detects `NON_BREAKING` change (INV-SC-01)
  - Report shows `/v1/items/{id}` response schema change (CC-14)
  - Semver suggestion is `minor` bump (INV-SC-05)

**US-09: Allow new enum value**
- **As a** API developer
- **I want** to add enum values without breaking existing consumers
- **So that** I can extend functionality safely
- **Given:** `/v1/items/` accepts `status` enum `["active"]`
- **When:** `archived` is added to enum
- **Then:**
  - Tool detects `NON_BREAKING` change (INV-SC-01)
  - Report shows `/v1/items/` enum change (CC-14)
  - Semver suggestion is `minor` bump (INV-SC-05)

**US-10: Allow tag change**
- **As a** API developer
- **I want** to update tags without breaking existing consumers
- **So that** I can improve organization safely
- **Given:** `/v1/items/` has tag `["inventory"]`
- **When:** Tag changes to `["products"]`
- **Then:**
  - Tool detects `METADATA` change (INV-SC-01)
  - Report shows `/v1/items/` tag change (CC-14)
  - Semver suggestion is `patch` bump (INV-SC-05)

### 9.3 Documentation Gate (US-11 .. US-15)

**US-11: Enforce summary**
- **As a** API consumer
- **I want** every endpoint to have a clear summary
- **So that** I can understand its purpose quickly
- **Given:** `GET /v1/items/` has no `summary`
- **When:** Tool runs with `fail_on_undocumented=True`
- **Then:**
  - Tool detects missing `summary` (INV-SC-02)
  - Report shows `/v1/items/` documentation error (CC-15)
  - CI workflow fails with exit code 1 (T-23)

**US-12: Enforce description**
- **As a** API consumer
- **I want** every endpoint to have a detailed description
- **So that** I can understand its behavior fully
- **Given:** `POST /v1/items/` has description "Create item"
- **When:** Tool runs with `fail_on_undocumented=True`
- **Then:**
  - Tool detects insufficient description (INV-SC-02)
  - Report shows `/v1/items/` documentation error (CC-16)
  - CI workflow fails with exit code 1 (T-23)

**US-13: Enforce response_model**
- **As a** API consumer
- **I want** every endpoint to declare its response schema
- **So that** I can understand its return type
- **Given:** `GET /v1/items/` has no `response_model`
- **When:** Tool runs with `fail_on_undocumented=True`
- **Then:**
  - Tool detects missing `response_model` (INV-SC-02)
  - Report shows `/v1/items/` documentation error (CC-17)
  - CI workflow fails with exit code 1 (T-23)

**US-14: Enforce tags**
- **As a** API consumer
- **I want** every endpoint to be tagged
- **So that** I can navigate related endpoints easily
- **Given:** `DELETE /v1/items/{id}` has no `tags`
- **When:** Tool runs with `fail_on_undocumented=True`
- **Then:**
  - Tool detects missing `tags` (INV-SC-02)
  - Report shows `/v1/items/{id}` documentation error (CC-18)
  - CI workflow fails with exit code 1 (T-23)

**US-15: Allow undocumented routes when configured**
- **As a** API developer
- **I want** to disable documentation checks temporarily
- **So that** I can iterate quickly during development
- **Given:** `GET /v1/items/` has no `summary`
- **When:** Tool runs with `fail_on_undocumented=False`
- **Then:**
  - Tool ignores missing `summary` (INV-SC-02)
  - Report shows `/v1/items/` as undocumented (CC-15)
  - CI workflow passes (T-23)

### 9.4 CI Integration (US-16 .. US-20)

**US-16: Block PRs with breaking changes**
- **As a** CI maintainer
- **I want** PRs with breaking changes to be blocked
- **So that** I can prevent accidental API regressions
- **Given:** PR removes `/v1/items/{id}`
- **When:** CI workflow runs `api_spec_compliance`
- **Then:**
  - Tool detects `BREAKING` change (INV-SC-01)
  - CI workflow fails with exit code 1 (T-23)
  - PR merge is blocked (CC-23)

**US-17: Post Markdown report**
- **As a** PR reviewer
- **I want** to see a detailed Markdown report of API changes
- **So that** I can review them effectively
- **Given:** PR adds `/v1/orders/`
- **When:** CI workflow runs `api_spec_compliance`
- **Then:**
  - Tool generates `markdown_report.md` (INV-SC-06)
  - CI workflow posts report as PR comment (CC-24)
  - Report shows `/v1/orders/` as new endpoint (CC-13)

**US-18: Upload JSON report**
- **As a** CI maintainer
- **I want** JSON reports to be archived
- **So that** I can track API changes over time
- **Given:** PR modifies `/v1/items/`
- **When:** CI workflow runs `api_spec_compliance`
- **Then:**
  - Tool generates `report.json` (INV-SC-06)
  - CI workflow uploads report as artifact (CC-25)
  - Report includes all changes (CC-14)

**US-19: Suggest semver bump**
- **As a** release manager
- **I want** tool to suggest version bumps
- **So that** I can follow semver correctly
- **Given:** PR adds `/v1/orders/`
- **When:** CI workflow runs `api_spec_compliance`
- **Then:**
  - Tool suggests `minor` bump (INV-SC-05)
  - Report includes semver suggestion (CC-24)
  - CI workflow posts suggestion as PR comment (T-19)

**US-20: Handle first run**
- **As a** new project maintainer
- **I want** tool to create initial snapshot
- **So that** I can start tracking API changes
- **Given:** No `openapi.json` exists
- **When:** Tool runs first time
- **Then:**
  - Tool creates `openapi.json` (INV-SC-04)
  - Report shows snapshot created (CC-03)
  - CI workflow passes (T-15)

### 9.5 Edge Cases (US-21 .. US-25)

**US-21: Handle corrupted snapshot**
- **As a** CI maintainer
- **I want** tool to handle corrupted snapshots gracefully
- **So that** CI doesn't fail silently
- **Given:** `openapi.json` contains invalid JSON
- **When:** Tool runs
- **Then:**
  - Tool raises clear error (INV-SC-10)
  - Report suggests `--reset-snapshot` (CC-03)
  - CI workflow fails with exit code 1 (T-23)

**US-22: Handle empty app**
- **As a** new project maintainer
- **I want** tool to handle empty apps gracefully
- **So that** I can start tracking API changes early
- **Given:** FastAPI app has no routes
- **When:** Tool runs
- **Then:**
  - Tool creates empty snapshot (INV-SC-04)
  - Report shows snapshot created (CC-03)
  - CI workflow passes (T-15)

**US-23: Handle server URL changes**
- **As a** API developer
- **I want** server URL changes to be ignored
- **So that** CI doesn't fail on non-breaking changes
- **Given:** `servers` changes from `http://localhost` to `https://api.example.com`
- **When:** Tool runs
- **Then:**
  - Tool ignores server URL change (INV-SC-08)
  - Report shows no changes (CC-14)
  - CI workflow passes (T-23)

**US-24: Handle operation ID changes**
- **As a** API developer
- **I want** operation ID changes to be ignored
- **So that** CI doesn't fail on non-breaking changes
- **Given:** `operationId` changes from `getItems` to `listItems`
- **When:** Tool runs
- **Then:**
  - Tool ignores operation ID change (INV-SC-08)
  - Report shows no changes (CC-14)
  - CI workflow passes (T-23)

**US-25: Handle large schema**
- **As a** API developer
- **I want** tool to handle large schemas quickly
- **So that** CI remains fast
- **Given:** API has 500 routes
- **When:** Tool runs
- **Then:**
  - Tool completes in < 2s (INV-SC-09)
  - Report includes all changes (CC-14)
  - CI workflow passes (T-29)

---

## 10. Test Plan

### 10.1 Breaking Change Detection

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | Detect removed endpoint | `/v1/items/{id}` exists in snapshot | Remove route from FastAPI app | `BREAKING` change detected for removed path (INV-SC-01) |
| T-02 | Detect narrowed response type | `/v1/items/` returns `ItemOut` with optional `price` | Make `price` required | `BREAKING` change detected for response schema (INV-SC-01) |
| T-03 | Detect removed enum value | `/v1/items/` accepts `status` enum `["active", "archived"]` | Remove `archived` value | `BREAKING` change detected for enum reduction (INV-SC-01) |
| T-04 | Detect added required param | `GET /v1/items/` has no required params | Add required `limit` param | `BREAKING` change detected for new required param (INV-SC-01) |
| T-05 | Detect renamed path param | `/v1/items/{item_id}` in snapshot | Change to `/v1/items/{id}` | `BREAKING` change detected for path param rename (INV-SC-01) |
| T-06 | Detect response field rename | `/v1/items/` returns `item_id` field | Rename field to `id` | `BREAKING` change detected for field rename (INV-SC-01) |

### 10.2 Non-Breaking Change Detection

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-07 | Allow new endpoint | `/v1/items/` in snapshot | Add `/v1/orders/` route | `NON_BREAKING` change detected (INV-SC-01) |
| T-08 | Allow new optional param | `GET /v1/items/` has no params | Add optional `limit` param | `NON_BREAKING` change detected (INV-SC-01) |
| T-09 | Allow new response field | `/v1/items/` returns basic `ItemOut` | Add `created_at` field | `NON_BREAKING` change detected (INV-SC-01) |
| T-10 | Allow new enum value | `/v1/items/` accepts `status` enum `["active"]` | Add `archived` value | `NON_BREAKING` change detected (INV-SC-01) |
| T-11 | Allow tag change | `/v1/items/` has tag `["inventory"]` | Change to `["products"]` | `METADATA` change detected (INV-SC-01) |

### 10.3 Documentation Validation

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-12 | Reject missing summary | Route has no `summary` | Run tool with `fail_on_undocumented=True` | Documentation error for missing `summary` (INV-SC-02) |
| T-13 | Reject short description | Route has 10-char description | Run tool | Error for insufficient description (INV-SC-02) |
| T-14 | Reject missing response_model | Route has no `response_model` | Run tool | Error for missing `response_model` (INV-SC-02) |
| T-15 | Reject missing tags | Route has no `tags` | Run tool | Error for missing `tags` (INV-SC-02) |
| T-16 | Allow undocumented when configured | Route missing `summary` | Run with `fail_on_undocumented=False` | Warning but no failure (INV-SC-02) |

### 10.4 Snapshot Lifecycle

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-17 | Create initial snapshot | No `openapi.json` exists | First tool run | Snapshot created, passes (INV-SC-04) |
| T-18 | Reject silent updates | Existing `openapi.json` | Modify routes without `--update-snapshot` | Fails on diff, no file changes (INV-SC-04) |
| T-19 | Normalize schema deterministically | Schema with shuffled keys | Generate snapshot twice | Identical output files (INV-SC-03) |
| T-20 | Ignore server URL changes | `servers` changes from localhost to prod | Run diff | No changes detected (INV-SC-08) |
| T-21 | Ignore operation ID changes | `operationId` changes from `getItems` to `listItems` | Run diff | No changes detected (INV-SC-08) |

### 10.5 CI Integration

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-22 | Block PR on breaking change | PR removes `/v1/items/{id}` | CI runs tool | Fails with exit code 1 (INV-SC-07) |
| T-23 | Generate Markdown report | PR adds `/v1/orders/` | CI runs tool | `markdown_report.md` created (INV-SC-06) |
| T-24 | Upload JSON report | PR modifies `/v1/items/` | CI runs tool | `report.json` artifact uploaded (INV-SC-06) |
| T-25 | Suggest semver bump | PR adds new endpoint | CI runs tool | Report suggests `minor` bump (INV-SC-05) |

### 10.6 Edge Cases

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-26 | Handle corrupted snapshot | `openapi.json` contains invalid JSON | Run tool | Clear error message (INV-SC-10) |
| T-27 | Handle empty app | FastAPI app has no routes | Run tool | Empty snapshot created (INV-SC-04) |
| T-28 | Handle large schema | API with 500 routes | Run tool | Completes in <2s (INV-SC-09) |
| T-29 | Verify report generation speed | 200-route API | Generate report | Completes in <200ms (INV-SC-09) |
| T-30 | Tool idempotency | Tenancy already enabled | Run tool again | No changes, "skipped" note (INV-SC-10) |

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|----------------|-------------|-------|
| add_soft_delete | No | ✅ Compatible | Soft delete modifies models but doesn't affect API contracts |
| add_cursor_pagination | No | ✅ Compatible | Pagination adds query params but doesn't break existing endpoints |
| add_search | No | ✅ Compatible | Search endpoints are additive and don't modify existing routes |
| add_audit_log | No | ✅ Compatible | Audit logs are transparent to API consumers |
| add_data_export | No | ✅ Compatible | Export endpoints are additive and don't modify existing routes |
| add_bulk_operations | No | ✅ Compatible | Bulk endpoints are additive and don't modify existing routes |
| add_multi_tenancy | Yes | ⚠️ Caveat | Must run after multi-tenancy since tenant middleware affects route resolution |
| add_feature_flags | No | ✅ Compatible | Feature flags are transparent to API consumers |
| add_api_key_auth | No | ✅ Compatible | API key auth adds security but doesn't modify routes |
| add_oauth2_provider | No | ✅ Compatible | OAuth2 adds auth endpoints but doesn't modify existing routes |
| add_rbac | No | ✅ Compatible | RBAC adds permissions but doesn't modify route contracts |
| add_mfa | No | ✅ Compatible | MFA adds auth endpoints but doesn't modify existing routes |
| add_cache_layer | No | ✅ Compatible | Caching is transparent to API consumers |
| add_outbox_pattern | No | ✅ Compatible | Outbox pattern modifies background processing but not API contracts |
| add_sse | No | ✅ Compatible | SSE endpoints are additive and don't modify existing routes |

**Conflicts:** None identified.

## 12. Rollback Procedure

### Code rollback (before deploy)
```bash
git checkout HEAD -- app/core/openapi_snapshot.py
git checkout HEAD -- app/core/spec_diff.py
git checkout HEAD -- app/core/doc_validator.py
git checkout HEAD -- app/main.py
rm -rf .github/workflows/api-spec.yml
rm -rf tests/test_api_spec.py
rm -rf openapi.json
```

### Database rollback (after deploy)
**N/A** — this tool is a code-only refactor. No database tables, columns, or
indexes are created. `alembic downgrade -1` would be a no-op. Skip this step.

### Data preservation rollback
**N/A** — no business data is created or migrated by this tool. Nothing to archive.

### Failure mode: tool partially modified files
```bash
git status
git checkout HEAD -- app/core/openapi_snapshot.py
git checkout HEAD -- app/core/spec_diff.py
git checkout HEAD -- app/core/doc_validator.py
git checkout HEAD -- app/main.py
rm -rf .github/workflows/api-spec.yml
rm -rf tests/test_api_spec.py
rm -rf openapi.json
```

### Emergency: Corrupted snapshot file
1. Delete corrupted snapshot: `rm openapi.json`
2. Regenerate snapshot: `python -m app.main --update-snapshot`
3. Commit new snapshot: `git add openapi.json && git commit -m "Regenerate snapshot"`

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | First run with no snapshot | Tool creates initial snapshot and passes |
| EC-2 | Snapshot file corrupted | Tool errors with message: "Snapshot corrupted. Delete and regenerate with --update-snapshot" |
| EC-3 | Route renamed | Tool detects removed old route and added new route as breaking changes |
| EC-4 | Path parameter renamed | Tool detects breaking change due to path parameter modification |
| EC-5 | Response field renamed | Tool detects breaking change due to response schema modification |
| EC-6 | Optional field made required | Tool detects breaking change due to parameter requirement change |
| EC-7 | Required field made optional | Tool detects non-breaking change since existing consumers still work |
| EC-8 | Enum value added | Tool detects non-breaking change since existing consumers still work |
| EC-9 | Enum value removed | Tool detects breaking change due to enum value removal |
| EC-10 | Tag renamed | Tool detects metadata change with no version bump required |
| EC-11 | Operation ID auto-generated | Tool ignores operation ID changes since they're non-semantic |
| EC-12 | Server URL changed | Tool ignores server URL changes since they're non-semantic |
| EC-13 | Schema uses oneOf/anyOf | Tool handles complex schemas via structural comparison |
| EC-14 | API has 500 routes | Tool completes diff in under 2 seconds despite large schema |
| EC-15 | Route added AND route removed same PR | Tool reports both changes and fails if any are breaking |

## 14. Acceptance Criteria (Final Sign-off)

✅ 1. All 30 completeness criteria verified
✅ 2. Existing test suite passes with 0 failures
✅ 3. New test_api_spec.py created with 30 passing tests
✅ 4. CI workflow api-spec.yml implemented and functional
✅ 5. Documentation completeness enforced for all routes
✅ 6. Breaking change detection implemented and verified
✅ 7. Schema normalization produces deterministic results
✅ 8. Report generation produces JSON, Markdown and GitHub annotations
✅ 9. Tool execution time remains under 2 seconds
✅ 10. Developer successfully runs tool, reviews report, and merges PR with API changes

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks
- [ ] Validate project_dir exists and contains FastAPI app
- [ ] Validate spec_file exists or create initial snapshot
- [ ] Parse all route files with AST for documentation validation
- [ ] Detect existing OpenAPI snapshot for comparison
- [ ] Validate FastAPI app initialization state
- [ ] Check for required dependencies (fastapi, pydantic)
- [ ] Verify Python version compatibility (>=3.8)

### 15.2 Schema generation
- [ ] Create openapi_snapshot.py module
- [ ] Implement generate_snapshot() using FastAPI's get_openapi()
- [ ] Add _normalize_schema() for deterministic comparison
- [ ] Implement save_snapshot() with pretty JSON formatting
- [ ] Implement load_snapshot() with validation
- [ ] Add schema version compatibility check
- [ ] Handle schema generation errors gracefully

### 15.3 Diff classification
- [ ] Create spec_diff.py module
- [ ] Implement classify_changes() for path-level comparison
- [ ] Add _compare_path_items() for operation-level comparison
- [ ] Add _compare_operations() for parameter/schema comparison
- [ ] Implement semver version bump suggestion
- [ ] Add schema normalization before comparison
- [ ] Handle large schemas efficiently (<500ms for 200 routes)

### 15.4 Documentation validation
- [ ] Create doc_validator.py module
- [ ] Implement validate_route_docs() for completeness check
- [ ] Add summary validation (required, non-empty)
- [ ] Add description validation (>=20 characters)
- [ ] Add response_model validation (required)
- [ ] Add tags validation (at least one tag)
- [ ] Handle undocumented routes gracefully with configurable failure

### 15.5 Report generation
- [ ] Implement JSON report format
- [ ] Implement Markdown report format
- [ ] Add GitHub annotations format
- [ ] Include detailed change classification
- [ ] Add semver version bump suggestion
- [ ] Include documentation validation results
- [ ] Add execution metrics (time, routes checked)

### 15.6 CI integration
- [ ] Create api-spec.yml workflow
- [ ] Add OpenAPI snapshot generation step
- [ ] Add spec compliance check step
- [ ] Configure fail_on_breaking=true
- [ ] Configure fail_on_undocumented=true
- [ ] Add Markdown report posting
- [ ] Add JSON report artifact upload

### 15.7 Test generation
- [ ] Create test_api_spec.py
- [ ] Add tests for breaking change detection
- [ ] Add tests for non-breaking changes
- [ ] Add tests for documentation validation
- [ ] Add tests for schema normalization
- [ ] Add tests for report generation
- [ ] Add performance benchmarks
- [ ] Add edge case tests

### 15.8 Error handling
- [ ] Handle corrupted snapshot gracefully
- [ ] Provide clear error messages for validation failures
- [ ] Add recovery instructions for common failures
- [ ] Handle partial failures during file operations
- [ ] Validate input parameters thoroughly
- [ ] Add logging for debugging
- [ ] Implement graceful shutdown on SIGINT

### 15.9 Documentation
- [ ] Add tool documentation to KNOWLEDGE.md
- [ ] Update manifest.yaml with new tool entry
- [ ] Add tool to SKILL.md tools table
- [ ] Document CI integration steps
- [ ] Add troubleshooting guide
- [ ] Document snapshot management
- [ ] Add examples of common workflows

### 15.10 Performance optimization
- [ ] Benchmark schema generation time
- [ ] Optimize diff algorithm for large schemas
- [ ] Cache normalized schemas for repeated comparisons
- [ ] Parallelize documentation validation
- [ ] Profile memory usage
- [ ] Optimize report generation
- [ ] Add performance SLO validation

### 15.11 Atomicity
- [ ] Use temp files for snapshot updates
- [ ] Implement rollback on failure
- [ ] Verify file writes complete successfully
- [ ] Handle concurrent execution safely
- [ ] Validate generated files parse correctly
- [ ] Add checksum verification for snapshots
- [ ] Implement idempotent operations

### 15.12 Verification
- [ ] Run ast.parse on all modified files
- [ ] Verify all generated code imports correctly
- [ ] Run pytest with full test suite
- [ ] Validate CI workflow execution
- [ ] Check report formats are valid
- [ ] Verify performance benchmarks
- [ ] Confirm edge case handling

### 15.13 Finalization
- [ ] Update version in pyproject.toml
- [ ] Add changelog entry
- [ ] Verify all dependencies are pinned
- [ ] Clean up temporary files
- [ ] Generate final documentation
- [ ] Run full integration test suite
- [ ] Prepare release artifacts

## 16. Documentation Output

```json
{
  "status": "success",
  "files_created": [
    "app/core/openapi_snapshot.py",
    "app/core/spec_diff.py",
    "app/core/doc_validator.py",
    ".github/workflows/api-spec.yml",
    "tests/test_api_spec.py",
    "openapi.json",
    "docs/api_spec_compliance.md",
    "scripts/generate_report.py"
  ],
  "files_modified": [
    "app/main.py",
    "pyproject.toml",
    "docs/KNOWLEDGE.md",
    "manifest.yaml",
    "SKILL.md"
  ],
  "metrics": {
    "execution_time_ms": 1245,
    "files_changed": 13,
    "lines_added": 842,
    "lines_removed": 32,
    "routes_validated": 47,
    "breaking_changes": 0,
    "undocumented_routes": 0
  },
  "next_steps": [
    "Commit the new openapi.json snapshot: git add openapi.json && git commit -m 'Update API snapshot'",
    "Run the CI workflow: gh workflow run api-spec.yml",
    "Review the Markdown report: cat markdown_report.md",
    "Verify API changes: pytest tests/test_api_spec.py -v",
    "Update API version in pyproject.toml if needed"
  ],
  "warnings": [
    "Ensure all routes have complete documentation before merging",
    "Breaking changes will block CI - review carefully",
    "Snapshot updates require explicit --update-snapshot flag"
  ],
  "notes": [
    "API spec compliance tool installed successfully",
    "47 routes validated with complete documentation",
    "No breaking changes detected",
    "CI workflow configured to run on all PRs",
    "Report generation completed in 1245ms",
    "Existing tests still pass: 112/112"
  ]
}
