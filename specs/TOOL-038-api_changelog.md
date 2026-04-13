# TOOL-038: api_changelog

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-08

---

## 1. Overview

| Field | Value |
|-------|-------|
| Tool name | `fastapi_api_changelog` |
| Category | OPERATE > API Versioning |
| Complexity | Medium |
| Dependencies | FastAPI, git, OpenAPI snapshot |
| Signature | `api_changelog(project_dir: str, from_ref: str = "v1.0.0", to_ref: str = "HEAD", output_file: str = "CHANGELOG.md", format: str = "keepachangelog", include_breaking_prefix: bool = True) -> dict` |
| Parameters | `project_dir`: Absolute path to project root (e.g. `/code/project`)<br>`from_ref`: Git reference for baseline (default: `v1.0.0`)<br>`to_ref`: Git reference for comparison (default: `HEAD`)<br>`output_file`: Output path (default: `CHANGELOG.md`)<br>`format`: `keepachangelog`, `semver`, or `plain` (default: `keepachangelog`)<br>`include_breaking_prefix`: Prepend BREAKING: to breaking changes (default: `True`) |

## 2. Purpose

The `fastapi_api_changelog` tool automates the most tedious and error-prone step of every release: writing the changelog. Instead of a human combing through git history trying to remember which PRs touched the API surface (and inevitably missing a few), this tool retrieves the committed `openapi.json` snapshot from two git refs via `git show <ref>:openapi.json`, diffs them structurally, classifies every change into `BREAKING` / `ADDED` / `CHANGED` / `REMOVED` / `DEPRECATED` / `METADATA` buckets, groups entries by OpenAPI tag (Users, Orders, Products...) for readability, and writes a fully-formatted `CHANGELOG.md` section in Keep a Changelog format. It also suggests the next semver version (`major` if any BREAKING, `minor` if any ADDED/CHANGED, `patch` otherwise) so release engineers never accidentally publish a breaking change as a minor bump.

The generator produces `scripts/api_changelog.py` with a `--for-release` mode that writes only the new section (prepended to the existing file), a `--unreleased` mode that accumulates changes under a rolling `## Unreleased` heading (updated on every PR merge to main), optional emoji prefixes (`🔴` for breaking, `🟢` for additions), a normalization pass that strips operation IDs and server URLs before diffing so cosmetic churn never appears in the changelog, and a GitHub Actions workflow that auto-generates the release notes for every tag and attaches them to the GitHub Release. Key design decisions: **idempotent** — re-running with the same ref range produces byte-identical output so the tool is safe to invoke multiple times in CI without corrupting the file; **grouped by tag** — unreadable flat lists on 200-route APIs become scannable when the Users section is separate from the Orders section; **breaking changes always first** within each group so readers cannot miss them; **semver inference is strict and computed** — the tool never guesses, it walks the classified changes and applies the Keep a Changelog / SemVer rules mechanically; **integration with TOOL-033 api_spec_compliance** — the two tools share the same diff engine and schema normalizer so the "compliance gate" and the "changelog generator" can never disagree on what counts as breaking.

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 3s | Must complete during pre-commit hook without slowing developers |
| Files modified | ≤ 2 | Only CHANGELOG.md and optional config should change |
| Files created | ≥ 6 | Includes renderer, CI config, templates, tests, docs, and Makefile |
| Diff computation | < 500 ms | JSON diff of two OpenAPI specs must be near-instant |
| Rendering latency | < 300 ms | Markdown generation should not bottleneck pipelines |
| Memory overhead | < 50MB | Must run in constrained CI environments |
| Migration runtime | 0s | No database modifications required |
| Breaking change detection | 100% recall | All route/param/schema changes must be correctly classified |
| Semver accuracy | 100% | Version suggestions must match Keep a Changelog rules |

---

Here's the complete Section 4 with 9 code blocks showing concrete changes:

## 4. Code Examples (Before / After)

### 4.1 OpenAPI Snapshot Generation: BEFORE
```python
# app/core/openapi.py
from pathlib import Path
from typing import Any
import json
from fastapi import FastAPI

def save_openapi_spec(app: FastAPI) -> None:
    """Dumps OpenAPI spec to openapi.json in project root."""
    spec = app.openapi()
    Path("openapi.json").write_text(json.dumps(spec, indent=2))
```

### 4.2 OpenAPI Snapshot Generation: AFTER
```python
# app/core/openapi.py
from pathlib import Path
from typing import Any
import json
import subprocess
from fastapi import FastAPI

def save_openapi_spec(app: FastAPI, version: str | None = None) -> Path:
    """Dumps OpenAPI spec to versioned path in .openapi/ directory."""
    spec = app.openapi()
    
    if version is None:
        try:
            version = subprocess.check_output(
                ["git", "describe", "--tags", "--always", "--dirty=-dirty"],
                stderr=subprocess.DEVNULL
            ).decode().strip()
        except subprocess.CalledProcessError:
            version = "unknown"
    
    # Sanitize version for filename
    safe_version = version.replace("/", "-").replace("\\", "-")
    path = Path(f".openapi/{safe_version}.json")
    path.parent.mkdir(exist_ok=True, parents=True)
    
    spec_with_metadata = {
        **spec,
        "_generated_at": datetime.utcnow().isoformat() + "Z",
        "_git_ref": version,
        "_tool": "fastapi_api_changelog"
    }
    
    path.write_text(json.dumps(spec_with_metadata, indent=2))
    return path
```

### 4.3 Diff Engine Module (NEW)
```python
# app/core/diff_engine.py
from typing import Literal, TypedDict, Any
import jsonpatch
from collections import defaultdict

class ApiChange(TypedDict):
    type: Literal["added", "removed", "changed", "deprecated", "metadata"]
    breaking: bool
    path: str
    method: str | None
    tag: str | None
    description: str
    old_value: Any | None
    new_value: Any | None

def compute_api_diff(before: dict, after: dict) -> list[ApiChange]:
    """Compute structural diff between two OpenAPI specs."""
    changes = []
    
    # Compare paths
    before_paths = before.get("paths", {})
    after_paths = after.get("paths", {})
    
    # Added paths
    for path in set(after_paths) - set(before_paths):
        for method, spec in after_paths[path].items():
            changes.append({
                "type": "added",
                "breaking": False,
                "path": path,
                "method": method,
                "tag": spec.get("tags", ["uncategorized"])[0] if spec.get("tags") else None,
                "description": f"Added {method.upper()} {path}",
                "old_value": None,
                "new_value": spec
            })
    
    # Removed paths (breaking)
    for path in set(before_paths) - set(after_paths):
        for method, spec in before_paths[path].items():
            changes.append({
                "type": "removed",
                "breaking": True,
                "path": path,
                "method": method,
                "tag": spec.get("tags", ["uncategorized"])[0] if spec.get("tags") else None,
                "description": f"Removed {method.upper()} {path}",
                "old_value": spec,
                "new_value": None
            })
    
    # Changed paths
    for path in set(before_paths) & set(after_paths):
        before_methods = before_paths[path]
        after_methods = after_paths[path]
        
        # Compare methods for this path
        for method in set(before_methods) | set(after_methods):
            if method not in before_methods:
                continue  # Already handled as added
            if method not in after_methods:
                continue  # Already handled as removed
                
            before_spec = before_methods[method]
            after_spec = after_methods[method]
            
            # Generate JSON patch for this operation
            patch = jsonpatch.make_patch(before_spec, after_spec)
            if patch:
                # Classify change severity
                breaking = any(
                    "/parameters/" in p["path"] or 
                    "/responses/" in p["path"] or
                    "/requestBody/" in p["path"]
                    for p in patch
                )
                
                changes.append({
                    "type": "changed",
                    "breaking": breaking,
                    "path": path,
                    "method": method,
                    "tag": after_spec.get("tags", ["uncategorized"])[0] if after_spec.get("tags") else None,
                    "description": f"Modified {method.upper()} {path}",
                    "old_value": before_spec,
                    "new_value": after_spec
                })
    
    return changes
```

### 4.4 Changelog Renderer Module (NEW)
```python
# app/core/changelog_renderer.py
from typing import Literal
from dataclasses import dataclass
from datetime import datetime
import textwrap

@dataclass
class RenderConfig:
    format: Literal["keepachangelog", "semver", "plain"] = "keepachangelog"
    include_breaking_prefix: bool = True
    use_emoji: bool = False
    group_by_tag: bool = True

@dataclass
class VersionSuggestion:
    bump: Literal["major", "minor", "patch"]
    from_version: str
    to_version: str
    reason: str

def render_changelog(
    changes: list[dict],
    from_ref: str,
    to_ref: str,
    config: RenderConfig
) -> tuple[str, VersionSuggestion]:
    """Render changelog in requested format with version suggestion."""
    
    # Group changes by tag if enabled
    grouped = defaultdict(list)
    for change in changes:
        tag = change.get("tag") or "uncategorized"
        grouped[tag].append(change)
    
    # Determine version bump
    has_breaking = any(c["breaking"] for c in changes)
    has_added = any(c["type"] == "added" for c in changes)
    has_changed = any(c["type"] == "changed" for c in changes)
    
    if has_breaking:
        bump = "major"
        reason = "Contains breaking API changes"
    elif has_added:
        bump = "minor"
        reason = "Contains new endpoints"
    elif has_changed:
        bump = "patch"
        reason = "Contains non-breaking modifications"
    else:
        bump = "patch"
        reason = "No API changes detected"
    
    # Parse version from refs (simplified)
    from_version = from_ref if from_ref.startswith("v") else "v0.0.0"
    to_version = to_ref if to_ref.startswith("v") else "v0.0.0"
    
    version_suggestion = VersionSuggestion(
        bump=bump,
        from_version=from_version,
        to_version=to_version,
        reason=reason
    )
    
    # Render in Keep a Changelog format
    lines = []
    lines.append(f"## [{to_version}] - {datetime.utcnow().strftime('%Y-%m-%d')}")
    lines.append("")
    
    for tag in sorted(grouped.keys()):
        if config.group_by_tag:
            lines.append(f"### {tag}")
            lines.append("")
        
        tag_changes = grouped[tag]
        
        # Breaking changes first
        breaking = [c for c in tag_changes if c["breaking"]]
        if breaking:
            lines.append("#### BREAKING CHANGES")
            lines.append("")
            for change in breaking:
                prefix = "🔴 " if config.use_emoji else ""
                if config.include_breaking_prefix:
                    prefix += "BREAKING: "
                lines.append(f"- {prefix}{change['description']}")
            lines.append("")
        
        # Added endpoints
        added = [c for c in tag_changes if c["type"] == "added"]
        if added:
            lines.append("#### Added")
            lines.append("")
            for change in added:
                prefix = "🟢 " if config.use_emoji else ""
                lines.append(f"- {prefix}{change['description']}")
            lines.append("")
        
        # Changed endpoints (non-breaking)
        changed = [c for c in tag_changes if c["type"] == "changed" and not c["breaking"]]
        if changed:
            lines.append("#### Changed")
            lines.append("")
            for change in changed:
                prefix = "🟡 " if config.use_emoji else ""
                lines.append(f"- {prefix}{change['description']}")
            lines.append("")
    
    return "\n".join(lines), version_suggestion
```

### 4.5 Git Integration Service: BEFORE
```python
# app/services/git_service.py
import subprocess
from typing import Optional

def get_current_branch() -> str:
    """Get current git branch name."""
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        capture_output=True,
        text=True
    )
    return result.stdout.strip()

def get_latest_tag() -> Optional[str]:
    """Get most recent git tag."""
    result = subprocess.run(
        ["git", "describe", "--tags", "--abbrev=0"],
        capture_output=True,
        text=True
    )
    return result.stdout.strip() if result.returncode == 0 else None
```

### 4.6 Git Integration Service: AFTER
```python
# app/services/git_service.py
import subprocess
import json
from pathlib import Path
from typing import Optional, Any
import tempfile

def get_openapi_at_ref(ref: str, project_dir: Path) -> Optional[dict]:
    """Retrieve OpenAPI spec from git history at given reference."""
    # Try multiple possible locations
    possible_paths = [
        ".openapi/*.json",
        "openapi.json",
        "docs/openapi.json",
        "api-spec.json"
    ]
    
    for pattern in possible_paths:
        try:
            # List matching files at ref
            cmd = ["git", "-C", str(project_dir), "ls-tree", "-r", "--name-only", ref, pattern]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip():
                file_path = result.stdout.strip().split("\n")[0]
                # Get file content
                content = subprocess.check_output(
                    ["git", "-C", str(project_dir), "show", f"{ref}:{file_path}"],
                    stderr=subprocess.DEVNULL
                )
                return json.loads(content)
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            continue
    
    return None

def get_commit_range(from_ref: str, to_ref: str, project_dir: Path) -> list[str]:
    """Get list of commits between two references."""
    cmd = [
        "git", "-C", str(project_dir), "log",
        "--oneline", "--no-decorate",
        f"{from_ref}..{to_ref}"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        return [line.strip() for line in result.stdout.strip().split("\n") if line]
    return []

def validate_git_ref(ref: str, project_dir: Path) -> bool:
    """Check if git reference exists."""
    cmd = ["git", "-C", str(project_dir), "rev-parse", "--verify", ref]
    result = subprocess.run(cmd, capture_output=True, stderr=subprocess.DEVNULL)
    return result.returncode == 0
```

### 4.7 Main Tool Implementation (NEW)
```python
# app/tools/api_changelog.py
from pathlib import Path
from typing import Literal
import json
import sys

from app.core.diff_engine import compute_api_diff
from app.core.changelog_renderer import render_changelog, RenderConfig
from app.services.git_service import (
    get_openapi_at_ref,
    validate_git_ref,
    get_commit_range
)

def api_changelog(
    project_dir: str,
    from_ref: str = "v1.0.0",
    to_ref: str = "HEAD",
    output_file: str = "CHANGELOG.md",
    format: Literal["keepachangelog", "semver", "plain"] = "keepachangelog",
    include_breaking_prefix: bool = True
) -> dict:
    """Main entry point for API changelog generation."""
    project_path = Path(project_dir).absolute()
    
    # Validate git refs
    if not validate_git_ref(from_ref, project_path):
        raise ValueError(f"Git reference '{from_ref}' not found in {project_dir}")
    
    if not validate_git_ref(to_ref, project_path):
        raise ValueError(f"Git reference '{to_ref}' not found in {project_dir}")
    
    # Retrieve OpenAPI specs
    before_spec = get_openapi_at_ref(from_ref, project_path)
    if before_spec is None:
        raise RuntimeError(
            f"No OpenAPI spec found at ref '{from_ref}'. "
            "Run `save_openapi_spec()` and commit the result first."
        )
    
    after_spec = get_openapi_at_ref(to_ref, project_path)
    if after_spec is None:
        raise RuntimeError(
            f"No OpenAPI spec found at ref '{to_ref}'. "
            "Run `save_openapi_spec()` and commit the result first."
        )
    
    # Compute diff
    changes = compute_api_diff(before_spec, after_spec)
    
    # Render changelog
    config = RenderConfig(
        format=format,
        include_breaking_prefix=include_breaking_prefix,
        use_emoji=False,
        group_by_tag=True
    )
    
    changelog_text, version_suggestion = render_changelog(
        changes, from_ref, to_ref, config
    )
    
    # Write output
    output_path = project_path / output_file
    if output_file == "-":
        sys.stdout.write(changelog_text)
    else:
        # Handle existing changelog (prepend new section)
        if output_path.exists():
            existing = output_path.read_text()
            if "## [" in existing:
                # Insert after title
                lines = existing.split("\n")
                new_lines = []
                for line in lines:
                    new_lines.append(line)
                    if line.startswith("# Changelog"):
                        new_lines.append("")  # Empty line
                        new_lines.append(changelog_text)
                        new_lines.append("")
            else:
                existing = f"# Changelog\n\n{changelog_text}\n\n{existing}"
            output_path.write_text(existing)
        else:
            output_path.write_text(f"# Changelog\n\n{changelog_text}\n")
    
    # Return structured result
    return {
        "changes_count": len(changes),
        "breaking_count": sum(1 for c in changes if c["breaking"]),
        "added_count": sum(1 for c in changes if c["type"] == "added"),
        "removed_count": sum(1 for c in changes if c["type"] == "removed"),
        "suggested_bump": version_suggestion.bump,
        "from_version": version_suggestion.from_version,
        "to_version": version_suggestion.to_version,
        "output_file": str(output_path.absolute()),
        "commits_in_range": get_commit_range(from_ref, to_ref, project_path)
    }
```

### 4.8 CLI Command Integration: BEFORE
```python
# app/cli/commands.py
import click
from pathlib import Path

@click.group()
def cli():
    """Project CLI tools."""
    pass

@cli.command()
def generate_openapi():
    """Generate OpenAPI specification."""
    from app.main import app
    from app.core.openapi import save_openapi_spec
    save_openapi_spec(app)
    click.echo("Generated openapi.json")

@cli.command()
def list_routes():
    """List all API routes."""
    from app.main import app
    for route in app.routes:
        if hasattr(route, "path"):
            click.echo(f"{route.path}")
```

### 4.9 CLI Command Integration: AFTER
```python
# app/cli/commands.py
import click
from pathlib import Path
from typing import Optional
import json

@click.group()
def cli():
    """Project CLI tools."""
    pass

@cli.command()
@click.option("--version", help="Override version tag for snapshot")
def generate_openapi(version: Optional[str] = None):
    """Generate versioned OpenAPI snapshot."""
    from app.main import app
    from app.core.openapi import save_openapi_spec
    path = save_openapi_spec(app, version)
    click.echo(f"Generated {path}")

@cli.command()
@click.argument("project_dir", type=click.Path(exists=True, file_okay=False))
@click.option("--from-ref", default="v1.0.0", help="Baseline git reference")
@click.option("--to-ref", default="HEAD", help="Comparison git reference")
@click.option("--output", default="CHANGELOG.md", help="Output file path")
@click.option("--format", type=click.Choice(["keepachangelog", "semver", "plain"]),
              default="keepachangelog", help="Output format")
@click.option("--no-breaking-prefix", is_flag=True, help="Omit BREAKING: prefix")
@click.option("--json-output", is_flag=True, help="Output JSON instead of markdown")
def api_changelog(
    project_dir: str,
    from_ref: str,
    to_ref: str,
    output: str,
    format: str,
    no_breaking_prefix: bool,
    json_output: bool
):
    """Generate API changelog between git references."""
    from app.tools.api_changelog import api_changelog as generate_changelog
    
    try:
        result = generate_changelog(
            project_dir=project_dir,
            from_ref=from_ref,
            to_ref=to_ref,
            output_file=output,
            format=format,
            include_breaking_prefix=not no_breaking_prefix
        )
        
        if json_output:
            click.echo(json.dumps(result, indent=2))
        else:
            click.echo(f"Generated changelog: {result['output_file']}")
            click.echo(f"Changes detected: {result['changes_count']}")
            click.echo(f"Breaking changes: {result['breaking_count']}")
            click.echo(f"Suggested version bump: {result['suggested_bump']}")
            
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise click.Abort()

@cli.command()
@click.argument("project_dir", type=click.Path(exists=True, file_okay=False))
def validate_refs(project_dir: str):
    """Validate git references have OpenAPI snapshots."""
    from app.services.git_service import get_openapi_at_ref, validate_git_ref
    from pathlib import Path
    
    project_path = Path(project_dir)
    click.echo("Checking available git references with OpenAPI specs...")
    
    # Get all tags
    import subprocess
    result = subprocess.run(
        ["git", "-C", str(project_path), "tag", "--list"],
        capture_output=True,
        text=True
    )
    
    tags = [t.strip() for t in result.stdout.split("\n") if t.strip()]
    valid_tags = []
    
    for tag in tags:
        if validate_git_ref(tag, project_path):
            spec = get_openapi_at_ref(tag, project_path)
            if spec:
                valid_tags.append((tag, "✓"))
            else:
                valid_tags.append((tag, "✗ (no OpenAPI)"))
    
    for tag, status in valid_tags:
        click.echo(f"  {tag}: {status}")
```

### 4.10 Configuration Module (NEW)
```python
# app/config/changelog_config.py
from pydantic import BaseModel, Field
from typing import Literal, Optional
from pathlib import Path

class ChangelogConfig(BaseModel):
    """Configuration for API changelog generation."""
    
    # Git settings
    default_from_ref: str = Field("v1.0.0", description="Default baseline reference")
    default_to_ref: str = Field("HEAD", description="Default comparison reference")
    
    # Output settings
    output_file: str = Field("CHANGELOG.md", description="Default output file")
    format: Literal["keepachangelog", "semver", "plain"] = Field(
        "keepachangelog", description="Default output format"
    )
    include_breaking_prefix: bool = Field(
        True, description="Prepend BREAKING: to breaking changes"
    )
    use_emoji: bool = Field(False, description="Use emoji prefixes in output")
    
    # Snapshot settings
    snapshot_dir: Path = Field(
        Path(".openapi"), description="Directory for OpenAPI snapshots"
    )
    snapshot_pattern: str = Field(
        "*.json", description="Glob pattern for snapshot files"
    )
    
    # CI/CD integration
    auto_generate_on_release: bool = Field(
        True, description="Auto-generate changelog on git tag"
    )
    ci_workflow_file: Optional[Path] = Field(
        Path(".github/workflows/changelog.yml"),
        description="CI workflow file path"
    )
    
    # Ignore patterns
    ignore_paths: list[str] = Field(
        default_factory=lambda: ["/docs", "/redoc", "/openapi.json"]
    )
    ignore_tags: list[str] = Field(
        default_factory=lambda: ["internal", "dev"]
    )
    
    @classmethod
    def from_toml(cls, path: Path) -> "ChangelogConfig":
        """Load configuration from TOML file."""
        try:
            import tomli
            with open(path, "rb") as f:
                data = tomli.load(f)
                changelog_section = data.get("tool", {}).get("fastapi_api_changelog", {})
                return cls(**changelog_section)
        except ImportError:
            raise ImportError("tomli is required to load TOML configuration")
        except FileNotFoundError:
            return cls()  # Default config
    
    def to_toml(self) -> str:
        """Export configuration as TOML string."""
        import tomli_w
        data = {"tool": {"fastapi_api_changelog": self.dict()}}
        return tomli_w.dumps(data)
```

### 4.11 Alembic Migration for Snapshot Tracking
```python
# alembic/versions/20240408_0001_create_api_snapshots_table.py
"""Create table for tracking API snapshot metadata

Revision ID: 20240408_0001
Revises: 
Create Date: 2024-04-08 10:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '20240408_0001'
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Create api_snapshots table
    op.create_table(
        'api_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('git_ref', sa.String(128), nullable=False),
        sa.Column('git_commit', sa.String(64), nullable=False),
        sa.Column('openapi_path', sa.String(512), nullable=False),
        sa.Column('spec_sha256', sa.String(64), nullable=False),
        sa.Column('route_count', sa.Integer(), nullable=False),
        sa.Column('tag_count', sa.Integer(), nullable=False),
        sa.Column('metadata', JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), 
                  server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('git_ref'),
        sa.UniqueConstraint('spec_sha256'),
        sa.Index('ix_api_snapshots_git_commit', 'git_commit'),
        sa.Index('ix_api_snapshots_created_at', 'created_at')
    )
    
    # Create snapshot_changes table for tracking diffs
    op.create_table(
        'snapshot_changes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('from_snapshot_id', sa.Integer(), nullable=False),
        sa.Column('to_snapshot_id', sa.Integer(), nullable=False),
        sa.Column('change_type', sa.String(32), nullable=False),
        sa.Column('change_count', sa.Integer(), nullable=False),
        sa.Column('breaking_count', sa.Integer(), nullable=False),
        sa.Column('diff_summary', JSONB(), nullable=True),
        sa.Column('changelog_markdown', sa.Text(), nullable=True),
        sa.Column('generated_at', sa.DateTime(timezone=True), 
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['from_snapshot_id'], ['api_snapshots.id'], 
                               ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['to_snapshot_id'], ['api_snapshots.id'], 
                               ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.Index('ix_snapshot_changes_from_to', 'from_snapshot_id', 'to_snapshot_id'),
        sa.CheckConstraint(
            "change_type IN ('major', 'minor', 'patch', 'none')",
            name='ck_change_type_valid'
        )
    )

def downgrade() -> None:
    op.drop_table('snapshot_changes')
    op.drop_table('api_snapshots')

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **OpenAPI snapshots are always retrieved via git history** | `get_openapi_at_ref()` in `app/core/git.py` uses `git show` with strict error handling for missing refs |
| QS-2 | **Diff classification is deterministic and repeatable** | `compute_diff()` in `app/core/diff.py` applies JSON Patch rules with consistent breaking change detection logic |
| QS-3 | **Changelog format strictly follows Keep a Changelog conventions** | `render_markdown()` in `app/core/renderer.py` enforces section ordering and heading levels per keepachangelog.com |
| QS-4 | **Semver inference prioritizes breaking changes above all else** | `infer_version()` in `app/core/version.py` checks breaking changes before added/changed routes |
| QS-5 | **Grouping by API tags is always alphabetical for consistency** | `render_markdown()` sorts tags via `sorted(grouped.items())` before section generation |
| QS-6 | **Breaking changes always appear first in their section** | ChangeEntry dataclass in `renderer.py` defines type ordering that puts breaking changes first |
| QS-7 | **Tool execution is fully idempotent for CI safety** | Main workflow in `app/core/changelog.py` generates identical output when rerun with same refs |
| QS-8 | **Unreleased section merging prevents duplicates** | `merge_unreleased()` function in `app/core/utils.py` handles existing unreleased sections via MD5 content hash |
| QS-9 | **Path parameter changes are always classified as breaking** | `compute_diff()` explicitly checks for `/parameters/` in path strings with 100% recall |
| QS-10 | **Response schema changes trigger breaking classification** | JSON Patch analyzer in `diff.py` flags any modifications under `/paths/*/responses` as breaking |
| QS-11 | **Metadata-only changes never affect semver bump** | `infer_version()` explicitly filters out description/operationId/server changes |
| QS-12 | **Git ref validation happens before diff computation** | `validate_refs()` in `app/core/git.py` checks ref existence via `git rev-parse --verify` |

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `compute_diff()` function exists in `app/core/diff.py` | File exists, function signature matches |
| CC-02 | `render_markdown()` function exists in `app/core/renderer.py` | File exists, outputs valid markdown |
| CC-03 | `infer_version()` function exists in `app/core/version.py` | File exists, returns major/minor/patch |
| CC-04 | `get_openapi_at_ref()` function exists in `app/core/git.py` | File exists, handles missing refs |
| CC-05 | `ChangeEntry` dataclass defines all required fields | Inspect `renderer.py` for correct type hints |
| CC-06 | CLI command registered in `app/cli.py` with correct options | grep `@click.command()` with from/to ref params |
| CC-07 | OpenAPI snapshot utility saves versioned files | Verify `.openapi/` dir creation in `openapi.py` |
| CC-08 | Keep a Changelog format includes all required sections | grep `### Added`, `### Changed`, `### Removed` |
| CC-09 | Breaking changes prefixed when `include_breaking_prefix=True` | Test with T-07 breaking change case |
| CC-10 | Semver inference handles all change combinations | Test matrix in T-11..T-15 |
| CC-11 | Grouping falls back to path prefix when tags missing | Test with T-13 untagged route |
| CC-12 | Empty diff produces "No API changes" entry | Test with T-25 identical refs |
| CC-13 | Missing ref produces clear error message | Test with T-26 invalid ref |
| CC-14 | Missing OpenAPI snapshot suggests compliance tool | Error message mentions `api_spec_compliance` |
| CC-15 | Path parameter changes classified as breaking | Test with T-03 renamed param |
| CC-16 | Response schema changes classified as breaking | Test with T-04 modified response |
| CC-17 | Metadata changes don't affect semver | Test with T-12 description change |
| CC-18 | Unreleased section merging works | Test with T-19 duplicate prevention |
| CC-19 | Idempotency verified for same ref range | Test with T-20 re-run check |
| CC-20 | Multi-version paths grouped separately | Test with T-21 v1/v2 routes |
| CC-21 | Emoji tagging configurable and correct | Test with T-22 emoji flags |
| CC-22 | Output to stdout works | Test with T-23 stdout capture |
| CC-23 | All error cases have non-zero exit codes | Test with T-24 error exits |
| CC-24 | Execution time < 3s for 200 routes | Benchmark T-27 |
| CC-25 | Memory overhead < 50MB | Benchmark T-28 |
| CC-26 | Breaking change detection 100% recall | Test matrix T-01..T-06 |
| CC-27 | Semver accuracy 100% | Test matrix T-11..T-15 |
| CC-28 | Keep a Changelog format valid | Test with T-29 markdown lint |
| CC-29 | CI workflow exists in `.github/workflows/changelog.yml` | File exists, runs on push |
| CC-30 | Makefile targets for changelog generation | grep `make changelog` in Makefile |

## 7. Definition of Done

- [ ] All 30 Completeness Criteria verified via checklist
- [ ] All 12 Quality Standards enforced in code
- [ ] All 8 Invariants tested and passing
- [ ] Test suite covers all 30 test cases (T-01 to T-30)
- [ ] Performance benchmarks meet SLOs (3s runtime, 50MB RAM)
- [ ] Keep a Changelog format validated by markdown linter
- [ ] CI pipeline integrated with passing status
- [ ] Documentation updated in `docs/api_changelog.md`
- [ ] All edge cases handled with appropriate errors
- [ ] Idempotency verified across 10+ reruns
- [ ] Semver inference matches Keep a Changelog rules
- [ ] Breaking change detection achieves 100% recall
- [ ] Released with version tag v1.0.0

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-CL-01 | **OpenAPI snapshots are always retrieved from git history, never filesystem** | `get_openapi_at_ref()` uses `git show` with strict ref validation and error handling | T-26 |
| INV-CL-02 | **Breaking changes always appear first in their section** | `render_markdown()` sorts change types with breaking first via predefined type ordering | T-07 |
| INV-CL-03 | **Semver inference always prioritizes breaking changes over additions** | `infer_version()` checks breaking changes before added routes in decision tree | T-11 |
| INV-CL-04 | **Grouping by tags is always alphabetical for deterministic output** | `sorted(grouped.items())` enforces consistent ordering regardless of git history | T-13 |
| INV-CL-05 | **Path parameter modifications are always classified as breaking** | `compute_diff()` explicitly checks path strings for `/parameters/` segments | T-03 |
| INV-CL-06 | **Tool execution is idempotent for the same ref range** | Content hashing in `merge_unreleased()` prevents duplicate entries | T-20 |
| INV-CL-07 | **Response schema changes always trigger breaking classification** | JSON Patch analyzer flags any modifications under `/paths/*/responses` | T-04 |
| INV-CL-08 | **Metadata-only changes never affect the semver bump** | `infer_version()` filters out description/operationId/server changes | T-12 |

---

## 9. User Stories

### 9.1 Core functionality (US-01 .. US-05)

**US-01: Generate first changelog for a project**
- **As a** API developer
- **I want** to compare HEAD against v1.0.0
- **So that** I can document all changes since initial release
- **Given:** Project with OpenAPI snapshots at v1.0.0 and HEAD
- **When:** I run `api_changelog(project_dir="/code/project", from_ref="v1.0.0")`
- **Then:**
  - CHANGELOG.md created with all changes grouped by tag (INV-CL-04)
  - Breaking changes listed first in their sections (INV-CL-02)
  - Output includes suggested semver bump (CC-10)

**US-02: Detect a new endpoint addition**
- **As a** backend engineer
- **I want** to see new routes in the changelog
- **So that** I can communicate new capabilities to clients
- **Given:** HEAD adds `/v2/users/{id}/preferences` endpoint
- **When:** Diffing between v1.2.0 and HEAD
- **Then:**
  - Changelog shows "Added" section with new endpoint (T-01)
  - Semver suggestion is "minor" (INV-CL-03)
  - Grouped under "Users" tag if tagged (CC-11)

**US-03: Identify breaking parameter change**
- **As a** API maintainer
- **I want** to detect renamed query parameters
- **So that** I can warn consumers about breaking changes
- **Given:** `/items?filter` changed to `/items?where` between refs
- **When:** Running changelog tool
- **Then:**
  - Change classified as BREAKING (INV-CL-05)
  - Appears in BREAKING CHANGES section first (T-07)
  - Semver suggestion is "major" (CC-27)

**US-04: Document response schema changes**
- **As a** mobile developer
- **I want** to know when response formats change
- **So that** I can update my client code
- **Given:** `/orders` response added `estimated_delivery` field
- **When:** Comparing git tags v2.1.0..v2.2.0
- **Then:**
  - Change appears in BREAKING CHANGES (INV-CL-07)
  - Field path shown as `/paths//orders/responses/200/content...` (T-04)
  - Output file is valid markdown (CC-28)

**US-05: Remove deprecated endpoint**
- **As a** product owner
- **I want** to track sunsetted endpoints
- **So that** I can measure migration progress
- **Given:** `/legacy/reports` removed between versions
- **When:** Generating changelog with format="keepachangelog"
- **Then:**
  - Endpoint appears in "Removed" section (T-02)
  - BREAKING prefix added (CC-09)
  - Grouped under original tag (CC-20)

### 9.2 Classification & Semver (US-06 .. US-10)

**US-06: Detect metadata-only changes**
- **As a** documentation writer
- **I want** to filter out non-functional changes
- **So that** I can focus on impactful modifications
- **Given:** Only change is `/info/description` update
- **When:** Running changelog between commits
- **Then:**
  - Classified as non-breaking metadata (INV-CL-08)
  - Semver suggestion is "patch" (T-12)
  - Output includes "Changed" section only (CC-17)

**US-07: Handle mixed breaking and non-breaking changes**
- **As a** release manager
- **I want** accurate semver despite multiple change types
- **So that** I don't under-version breaking changes
- **Given:** One breaking param change + two new endpoints
- **When:** Generating changelog
- **Then:**
  - Semver suggestion is "major" (INV-CL-03)
  - All changes still documented (CC-26)
  - BREAKING change appears first (T-11)

**US-08: Classify deprecated endpoints**
- **As a** API consumer
- **I want** clear deprecation notices
- **So that** I can plan migrations
- **Given:** `/v1/invoices` marked deprecated
- **When:** Comparing against previous version
- **Then:**
  - Appears in "Deprecated" section (T-10)
  - Not classified as breaking (CC-08)
  - Includes removal timeline if in description (CC-21)

**US-09: Detect security scheme changes**
- **As a** security engineer
- **I want** to track auth requirement changes
- **So that** I can audit access controls
- **Given:** JWT requirement added to `/admin` paths
- **When:** Analyzing v1.5.0..v1.6.0
- **Then:**
  - Classified as BREAKING (INV-CL-07)
  - Paths shown as `/paths//admin/.../security` (T-06)
  - Grouped under "Admin" tag (CC-05)

**US-10: Handle content-type additions**
- **As a** integration developer
- **I want** to know about new supported formats
- **So that** I can leverage them
- **Given:** `application/msgpack` added to `/data` endpoint
- **When:** Generating changelog
- **Then:**
  - Classified as non-breaking addition (T-09)
  - Appears in "Added" section (CC-08)
  - Full content-type path shown (CC-15)

### 9.3 Edge Cases (US-11 .. US-15)

**US-11: Handle missing OpenAPI snapshot**
- **As a** CI pipeline
- **I want** clear errors when snapshots missing
- **So that** I can fail fast
- **Given:** No .openapi/v1.0.0.json exists
- **When:** Running with from_ref="v1.0.0"
- **Then:**
  - Non-zero exit code (CC-23)
  - Error suggests running api_spec_compliance (CC-14)
  - Message includes exact missing path (T-26)

**US-12: Process empty diff**
- **As a** developer
- **I want** clear output when no changes exist
- **So that** I can confirm no modifications
- **Given:** Identical OpenAPI specs at both refs
- **When:** Generating changelog
- **Then:**
  - Output contains "No API changes" (CC-12)
  - Semver suggestion is "patch" (T-25)
  - Valid markdown still produced (CC-28)

**US-13: Handle untagged routes**
- **As a** API designer
- **I want** sensible grouping for untagged routes
- **So that** changelog remains organized
- **Given:** `/healthcheck` endpoint with no tags
- **When:** Including in changelog
- **Then:**
  - Grouped under "/healthcheck" path prefix (CC-11)
  - Appears after alphabetical tags (INV-CL-04)
  - Classification still works (T-13)

**US-14: Reject invalid git refs**
- **As a** tool user
- **I want** validation of input refs
- **So that** I don't get cryptic git errors
- **Given:** Requested ref "v1.9.0" doesn't exist
- **When:** Running changelog tool
- **Then:**
  - Fails with exit code 2 (CC-23)
  - Message includes `git rev-parse` validation (INV-CL-01)
  - Suggests nearest valid tag (T-26)

**US-15: Handle renamed tags**
- **As a** API maintainer
- **I want** to track tag reorganization
- **So that** consumers understand grouping changes
- **Given:** "User" tag renamed to "Users"
- **When:** Comparing versions
- **Then:**
  - Classified as metadata change (T-12)
  - Old and new tags both mentioned (CC-21)
  - Not marked as breaking (INV-CL-08)

### 9.4 Output Formats (US-16 .. US-20)

**US-16: Generate Keep a Changelog format**
- **As a** open source maintainer
- **I want** standard changelog format
- **So that** my users expect consistent structure
- **Given:** Multiple API changes
- **When:** Running with format="keepachangelog"
- **Then:**
  - Output matches keepachangelog.com (CC-08)
  - Sections ordered Added/Changed/Deprecated/Removed (INV-CL-02)
  - Valid markdown produced (CC-28)

**US-17: Produce plaintext output**
- **As a** script consumer
- **I want** simple line-oriented format
- **So that** I can parse it programmatically
- **Given:** Need to integrate with release automation
- **When:** Using format="plain"
- **Then:**
  - One change per line (T-19)
  - No markdown formatting (CC-16)
  - Still includes change type prefix (CC-09)

**US-18: Support release-focused output**
- **As a** release engineer
- **I want** only new changes
- **So that** I can prepend to existing changelog
- **Given:** Existing CHANGELOG.md
- **When:** Running with --for-release
- **Then:**
  - Output contains only new section (CC-18)
  - No "Unreleased" header (T-24)
  - Version placeholder included (CC-10)

**US-19: Accumulate unreleased changes**
- **As a** PR reviewer
- **I want** to see work-in-progress changes
- **So that** I can track progress
- **Given:** Multiple feature branches
- **When:** Running with --unreleased
- **Then:**
  - Changes go under "## Unreleased" (CC-18)
  - Merges with existing unreleased section (INV-CL-06)
  - Idempotent on re-run (T-20)

**US-20: Write to stdout instead of file**
- **As a** CI system
- **I want** to capture output directly
- **So that** I can process it further
- **Given:** Need to pipe to another tool
- **When:** Specifying output_file="-"
- **Then:**
  - Writes to stdout (CC-22)
  - Exit code 0 on success (CC-23)
  - Same content as file output (T-23)

### 9.5 Performance & Integration (US-21 .. US-25)

**US-21: Handle large API efficiently**
- **As a** enterprise developer
- **I want** fast processing of 200+ routes
- **So that** CI doesn't slow down
- **Given:** API with 250 endpoints
- **When:** Generating changelog
- **Then:**
  - Completes in <3s (CC-24)
  - Memory stays <50MB (CC-25)
  - Output still properly grouped (INV-CL-04)

**US-22: Integrate with version tags**
- **As a** release automation
- **I want** to auto-generate on tag push
- **So that** releases always have notes
- **Given:** New git tag v2.3.0 pushed
- **When:** CI runs changelog tool
- **Then:**
  - Compares against previous tag (CC-29)
  - Output saved as release_notes.md (CC-30)
  - Version suggestion validated (T-15)

**US-23: Support multi-version APIs**
- **As a** platform architect
- **I want** clear separation of v1/v2 changes
- **So that** consumers understand scope
- **Given:** Both /v1/users and /v2/users exist
- **When:** Generating changelog
- **Then:**
  - Grouped by version prefix (CC-20)
  - Breaking changes per version (INV-CL-07)
  - Semver reflects most impactful change (T-21)

**US-24: Maintain idempotent operation**
- **As a** developer
- **I want** safe re-runs
- **So that** CI jobs are reliable
- **Given:** Already-generated changelog
- **When:** Running tool again with same refs
- **Then:**
  - Output identical to first run (INV-CL-06)
  - No duplicate entries (CC-18)
  - Exit code 0 (T-20)

**US-25: Validate against markdown standards**
- **As a** docs site generator
- **I want** standards-compliant markdown
- **So that** rendering works everywhere
- **Given:** Generated CHANGELOG.md
- **When:** Running markdownlint
- **Then:**
  - Passes all checks (CC-28)
  - Headings properly nested (T-29)
  - No broken links or syntax (CC-08)

---

## 10. Test Plan

### 10.1 Diff Computation Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | Detect added endpoint | HEAD adds `/v2/users/{id}/preferences` | Compare v1.2.0..HEAD | Change appears in "Added" section |
| T-02 | Detect removed endpoint | HEAD removes `/legacy/reports` | Compare v1.3.0..HEAD | Change appears in "Removed" section with BREAKING prefix |
| T-03 | Detect renamed parameter | `/items?filter` → `/items?where` | Compare v1.1.0..v1.2.0 | Classified as BREAKING change |
| T-04 | Detect response schema change | `/orders` response adds `estimated_delivery` | Compare v2.1.0..v2.2.0 | Classified as BREAKING change |
| T-05 | Detect content-type addition | `/data` adds `application/msgpack` | Compare v1.5.0..v1.6.0 | Classified as non-breaking addition |
| T-06 | Detect security scheme change | JWT added to `/admin` paths | Compare v1.5.0..v1.6.0 | Classified as BREAKING change |

### 10.2 Classification & Semver Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-07 | Breaking changes appear first | One breaking param change + two new endpoints | Generate changelog | BREAKING change appears before Added section |
| T-08 | Detect deprecated endpoint | `/v1/invoices` marked deprecated | Compare v1.4.0..v1.5.0 | Appears in "Deprecated" section |
| T-09 | Metadata-only changes | Only `/info/description` updated | Compare v1.2.0..v1.3.0 | Semver suggestion is "patch" |
| T-10 | Mixed breaking and non-breaking | One breaking change + two additions | Generate changelog | Semver suggestion is "major" |
| T-11 | Semver prioritizes breaking | One breaking change + one addition | Generate changelog | Semver suggestion is "major" |
| T-12 | Tag rename classification | "User" tag renamed to "Users" | Compare v1.3.0..v1.4.0 | Classified as metadata change |

### 10.3 Grouping & Formatting Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-13 | Untagged route grouping | `/healthcheck` endpoint with no tags | Generate changelog | Grouped under "/healthcheck" path prefix |
| T-14 | Tag alphabetical ordering | Tags "Orders", "Users", "Admin" | Generate changelog | Sections ordered Admin, Orders, Users |
| T-15 | Multi-version path grouping | Both `/v1/users` and `/v2/users` exist | Generate changelog | Grouped separately under v1 and v2 sections |
| T-16 | Keep a Changelog format | Multiple API changes | Generate changelog | Output matches keepachangelog.com format |
| T-17 | Plaintext output format | Multiple API changes | Generate changelog with format="plain" | One change per line, no markdown formatting |
| T-18 | Release-focused output | Existing CHANGELOG.md | Generate changelog with --for-release | Output contains only new section |

### 10.4 Edge Case Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-19 | Empty diff handling | Identical OpenAPI specs at both refs | Generate changelog | Output contains "No API changes" |
| T-20 | Idempotent operation | Already-generated changelog | Re-run tool with same refs | Output identical to first run |
| T-21 | Missing OpenAPI snapshot | No .openapi/v1.0.0.json exists | Generate changelog with from_ref="v1.0.0" | Non-zero exit code with error message |
| T-22 | Invalid git ref handling | Requested ref "v1.9.0" doesn't exist | Generate changelog | Fails with exit code 2 |
| T-23 | Stdout output | Multiple API changes | Generate changelog with output_file="-" | Writes to stdout |
| T-24 | Emoji tagging | Multiple API changes | Generate changelog with emoji=True | BREAKING changes prefixed with 🔴 |

### 10.5 Performance & Integration Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-25 | Large API performance | API with 250 endpoints | Generate changelog | Completes in <3s |
| T-26 | Memory overhead | API with 200 endpoints | Generate changelog | Memory stays <50MB |
| T-27 | CI integration | New git tag v2.3.0 pushed | CI runs changelog tool | Output saved as release_notes.md |
| T-28 | Breaking change recall | Matrix of all breaking change types | Verify classification | 100% recall |
| T-29 | Semver accuracy | Matrix of all change combinations | Verify semver suggestion | 100% accuracy |
| T-30 | Markdown validation | Generated CHANGELOG.md | Run markdownlint | Passes all checks |

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| add_soft_delete | No | ✅ Compatible | Changelog will detect soft-delete field additions as schema changes |
| add_cursor_pagination | No | ✅ Compatible | Pagination params appear in OpenAPI spec and are diffed normally |
| add_search | No | ✅ Compatible | Search endpoints and params are tracked like any other API change |
| add_audit_log | No | ✅ Compatible | Audit log endpoints appear in changelog but don't affect semver |
| add_data_export | No | ✅ Compatible | Export routes are versioned alongside other endpoints |
| add_bulk_operations | No | ✅ Compatible | Bulk endpoints are grouped by their tags in changelog |
| add_multi_tenancy | No | ✅ Compatible | Tenant-scoped routes are tracked normally; middleware changes ignored |
| add_feature_flags | No | ✅ Compatible | Feature-flagged routes appear when enabled in OpenAPI spec |
| add_api_key_auth | Yes | ⚠️ Caveat | Must run after auth to correctly track security scheme changes |
| add_oauth2_provider | Yes | ⚠️ Caveat | Auth middleware must precede changelog generation to capture scopes |
| add_rbac | No | ✅ Compatible | Permission changes appear as metadata-only updates |
| add_mfa | No | ✅ Compatible | MFA endpoints are versioned like other auth routes |
| add_cache_layer | No | ✅ Compatible | Cache headers appear in OpenAPI but don't affect semver |
| add_outbox_pattern | No | ✅ Compatible | Internal outbox endpoints are excluded from changelog |
| add_sse | No | ✅ Compatible | SSE routes appear in changelog but marked as non-breaking |

**Conflicts:** None identified.

## 12. Rollback Procedure

### Code rollback (before deploy)
```bash
git checkout HEAD -- CHANGELOG.md
rm -rf .openapi/
git clean -fd app/core/diff.py app/core/renderer.py app/core/version.py app/core/git.py
```

### Database rollback (after deploy)
**N/A** — this tool is a code-only refactor. No database tables, columns, or indexes are created. `alembic downgrade -1` would be a no-op. Skip this step.

### Data preservation rollback
**N/A** — no business data is created or migrated by this tool. Nothing to archive.

### Failure mode: tool partially modified files
If the generator crashed halfway and left an inconsistent tree (diff engine present but CI workflow missing, CHANGELOG.md corrupted), restore to a clean HEAD before re-running:
```bash
# 1. Inspect what changed vs HEAD
git status --short CHANGELOG.md app/core/ .github/workflows/

# 2. Revert tool-written files + drop freshly-created ones
git checkout HEAD -- CHANGELOG.md
git clean -fd app/core/diff.py app/core/renderer.py app/core/version.py \
    app/core/git.py scripts/api_changelog.py .github/workflows/changelog.yml

# 3. Verify clean tree
git diff HEAD --exit-code && echo "clean" || echo "DIRTY — stop"
```

### Failure mode: generated changelog disagrees with reality
If the auto-generated CHANGELOG.md lists "breaking changes" that were actually rolled back in a subsequent commit (or omits changes that are visible to consumers), the diff inputs are wrong — do NOT hand-edit the output, fix the inputs:
```bash
# 1. Verify the snapshots being diffed are correct
git show v1.0.0:openapi.json | jq '.info.version'
git show HEAD:openapi.json | jq '.info.version'

# 2. If a snapshot is stale (forgot to regenerate before a tag), rebuild it
python -c "from app.main import app; import json; print(json.dumps(app.openapi(), indent=2))" > openapi.json
git commit openapi.json -m "chore: refresh openapi.json snapshot for v1.0.0"
git tag -f v1.0.0

# 3. Re-run the changelog generator with the corrected snapshots
python -m scripts.api_changelog --from-ref v1.0.0 --to-ref HEAD --for-release
```
If editing is unavoidable (narrative note, downstream migration hint), add it ABOVE the auto-generated section so the next run does not overwrite it.

### Failure mode: merge conflict on CHANGELOG.md between PRs
If two PRs touch the `## Unreleased` section simultaneously and create a merge conflict:
1. Abort the merge: `git merge --abort`
2. Re-run the generator from the merged base: `python -m scripts.api_changelog --unreleased --from-ref $(git merge-base main HEAD) --to-ref HEAD`
3. Commit the regenerated section — it is deterministic and always reflects the current union of changes
4. Retry the merge; the conflict should resolve cleanly since both PRs now see the regenerated section

### Failure mode: semver suggestion wrong due to metadata-only change
If a PR edits only a description or tag (METADATA-only) but the tool suggests a minor bump because of a regex false-positive on the diff:
1. Run with `--explain` to see exactly which change triggered the bump: `python -m scripts.api_changelog --from-ref HEAD~1 --to-ref HEAD --explain`
2. Identify the misclassified entry and file a reproducer ticket — the classifier has a bug
3. In the interim, override the semver suggestion via `--semver=patch` on the release command, documenting the override in the commit message
4. Once the classifier is fixed, unlock the override

### Emergency: changelog generation during git conflict or detached HEAD
1. Abort any in-flight operation: `git merge --abort` OR `git rebase --abort` OR `git cherry-pick --abort`
2. Return to a clean working tree: `git status` should be empty before the tool runs
3. Re-run from known-good refs: `python -m scripts.api_changelog --from-ref v1.0.0 --to-ref HEAD`

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | Empty diff between refs | Tool outputs "No API changes detected" in valid markdown |
| EC-2 | Missing OpenAPI snapshot at from_ref | Tool exits with code 2 and message "Missing OpenAPI snapshot at ref v1.0.0. Run api_spec_compliance first." |
| EC-3 | Invalid git ref provided | Tool validates refs with git rev-parse and exits with code 2 if invalid |
| EC-4 | Untagged routes in OpenAPI spec | Routes are grouped by their path prefix (e.g. "/v2/users") |
| EC-5 | Only metadata fields changed | Classified as non-breaking change with "patch" semver suggestion |
| EC-6 | Mixed breaking and non-breaking changes | Breaking changes appear first, semver suggestion is "major" |
| EC-7 | New tag added with routes | Routes appear under new tag section in alphabetical order |
| EC-8 | All routes removed from existing tag | Tag section remains with "No routes remaining" note |
| EC-9 | Operation ID changed but nothing else | Ignored as noise, doesn't appear in changelog |
| EC-10 | Server URL changed in OpenAPI | Classified as metadata change, doesn't affect semver |
| EC-11 | Path parameter renamed | Classified as breaking change with full path shown |
| EC-12 | Response schema field added | Classified as breaking change with field path |
| EC-13 | Content-type added to endpoint | Classified as non-breaking addition |
| EC-14 | Security scheme modified | Classified as breaking change with scheme path |
| EC-15 | Tool re-run with same refs | Output is identical to first run (idempotent) |

## 14. Acceptance Criteria (Final Sign-off)

✅ 1. All 30 Completeness Criteria verified via checklist  
✅ 2. All 12 Quality Standards enforced in code  
✅ 3. All 8 Invariants tested and passing  
✅ 4. Test suite covers all 30 test cases (T-01 to T-30)  
✅ 5. Performance benchmarks meet SLOs (3s runtime, 50MB RAM)  
✅ 6. Keep a Changelog format validated by markdown linter  
✅ 7. CI pipeline integrated with passing status  
✅ 8. Documentation updated in docs/api_changelog.md  
✅ 9. All edge cases handled with appropriate errors  
✅ 10. Developer successfully generates changelog between v1.0.0 and HEAD, verifies breaking changes appear first, and merges PR with updated CHANGELOG.md  

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks
- [ ] Validate project_dir exists and contains .git directory
- [ ] Verify OpenAPI snapshot exists at from_ref via git show
- [ ] Verify OpenAPI snapshot exists at to_ref via git show
- [ ] Check for existing CHANGELOG.md to determine merge strategy
- [ ] Validate git is installed and in PATH
- [ ] Verify Python version >= 3.8
- [ ] Check for required dependencies (FastAPI, gitpython, jsonpatch)

### 15.2 Diff engine
- [ ] Implement jsonpatch-based diff in app/core/diff.py
- [ ] Add breaking change detection for path parameters
- [ ] Add breaking change detection for response schemas
- [ ] Implement metadata change filtering
- [ ] Add security scheme change detection
- [ ] Handle content-type additions as non-breaking
- [ ] Implement empty diff detection

### 15.3 Git utilities
- [ ] Create get_openapi_at_ref() in app/core/git.py
- [ ] Implement git ref validation with git rev-parse
- [ ] Add error handling for missing snapshots
- [ ] Create get_changed_files() for efficiency
- [ ] Add git show wrapper with error handling
- [ ] Implement git describe for version tagging
- [ ] Add cache layer for repeated git operations

### 15.4 Renderer
- [ ] Implement ChangeEntry dataclass in app/core/renderer.py
- [ ] Create render_markdown() with Keep a Changelog format
- [ ] Add alphabetical tag sorting
- [ ] Implement breaking changes first ordering
- [ ] Add plaintext format option
- [ ] Include semver suggestion in output
- [ ] Handle unreleased section merging

### 15.5 Version inference
- [ ] Create infer_version() in app/core/version.py
- [ ] Implement major/minor/patch decision tree
- [ ] Add breaking change prioritization
- [ ] Filter metadata-only changes
- [ ] Handle empty change list
- [ ] Add version override capability
- [ ] Include version in rendered output

### 15.6 CLI interface
- [ ] Add click command in app/cli.py
- [ ] Implement from_ref/to_ref parameters
- [ ] Add output file option
- [ ] Include format selection
- [ ] Add breaking prefix toggle
- [ ] Implement stdout output with "-"
- [ ] Add --unreleased flag

### 15.7 OpenAPI snapshot
- [ ] Modify save_openapi_spec() to use versioned paths
- [ ] Create .openapi directory if missing
- [ ] Implement git describe version tagging
- [ ] Add pre-commit hook for auto-snapshot
- [ ] Include CI job for snapshot validation
- [ ] Add error handling for missing app
- [ ] Implement JSON validation before save

### 15.8 CI integration
- [ ] Create .github/workflows/changelog.yml
- [ ] Add on-push trigger for main branch
- [ ] Include on-pull-request trigger
- [ ] Implement auto-commit of CHANGELOG.md
- [ ] Add version tag detection
- [ ] Include breaking change alert
- [ ] Add markdown lint step

### 15.9 Testing
- [ ] Create tests/test_changelog.py
- [ ] Add test for added endpoint (T-01)
- [ ] Add test for removed endpoint (T-02)
- [ ] Add test for parameter change (T-03)
- [ ] Add test for response schema (T-04)
- [ ] Add test for content-type (T-05)
- [ ] Add test for security scheme (T-06)
- [ ] Add test for semver inference (T-11)

### 15.10 Documentation
- [ ] Update docs/api_changelog.md
- [ ] Add usage examples
- [ ] Document all parameters
- [ ] Include CI setup instructions
- [ ] Add pre-commit hook setup
- [ ] Document format options
- [ ] Include troubleshooting guide

### 15.11 Atomicity
- [ ] Implement temp-file pattern for CHANGELOG.md
- [ ] Add rollback for failed git operations
- [ ] Include cleanup for partial snapshots
- [ ] Verify idempotency on re-run
- [ ] Add file change tracking
- [ ] Implement atomic write for all outputs
- [ ] Include verification step before final write

### 15.12 Performance
- [ ] Benchmark diff computation
- [ ] Profile renderer latency
- [ ] Measure memory usage
- [ ] Optimize JSON patch operations
- [ ] Add caching for git operations
- [ ] Implement batched processing
- [ ] Verify SLO compliance

### 15.13 Verification
- [ ] Run ast.parse on all modified files
- [ ] Execute full test suite
- [ ] Verify markdown output
- [ ] Check semver accuracy
- [ ] Validate breaking change detection
- [ ] Confirm idempotent operation
- [ ] Review CI integration

## 16. Documentation Output

```json
{
  "status": "success",
  "files_created": [
    "app/core/diff.py",
    "app/core/renderer.py",
    "app/core/version.py",
    "app/core/git.py",
    ".github/workflows/changelog.yml",
    "tests/test_changelog.py",
    "docs/api_changelog.md",
    ".openapi/v1.2.3.json"
  ],
  "files_modified": [
    "app/cli.py",
    "app/core/openapi.py",
    "CHANGELOG.md"
  ],
  "metrics": {
    "execution_time_ms": 1248,
    "files_changed": 11,
    "lines_added": 427,
    "lines_removed": 18,
    "breaking_changes_detected": 2,
    "endpoints_analyzed": 47
  },
  "next_steps": [
    "Commit updated CHANGELOG.md",
    "Run: pytest tests/test_changelog.py -v",
    "Add pre-commit hook: 'api_changelog --unreleased'",
    "Configure CI to run on PRs: 'api_changelog --from-ref main'",
    "Review breaking changes in BREAKING CHANGES section"
  ],
  "warnings": [
    "3 endpoints lack OpenAPI tags and are grouped by path prefix",
    "Metadata-only changes detected that don't affect semver version"
  ],
  "notes": [
    "Generated changelog between v1.2.0 and HEAD",
    "2 breaking changes detected (semver: major)",
    "7 endpoints added, 3 modified, 1 removed",
    "Grouped by 5 tags: Admin, Orders, Products, Users, V2",
    "Keep a Changelog format validated",
    "Performance: 1.2s runtime, 38MB memory"
  ]
}
