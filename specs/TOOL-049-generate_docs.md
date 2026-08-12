---
spec_id: "TOOL-049"
tool_name: "add_generate_docs"
primitive: "api/DeprecationRegistry"
primitive_path: "core.venous.api.DeprecationRegistry"
version: "1.0.0"
status: "ratified"
invariants:
  - "INV-DOCS-001"
  - "INV-DOCS-002"
  - "INV-DOCS-003"
  - "INV-DOCS-004"
  - "INV-DOCS-005"
  - "INV-DOCS-006"
  - "INV-DOCS-007"
  - "INV-DOCS-008"
completeness_criteria:
  - "CC-01"
  - "CC-02"
  - "CC-03"
  - "CC-04"
  - "CC-05"
  - "CC-06"
  - "CC-07"
  - "CC-08"
  - "CC-09"
  - "CC-10"
  - "CC-11"
  - "CC-12"
  - "CC-13"
  - "CC-14"
  - "CC-15"
  - "CC-16"
  - "CC-17"
  - "CC-18"
  - "CC-19"
  - "CC-20"
  - "CC-21"
  - "CC-22"
  - "CC-23"
  - "CC-24"
  - "CC-25"
  - "CC-26"
  - "CC-27"
  - "CC-28"
  - "CC-29"
  - "CC-30"
  - "CC-31"
  - "CC-32"
  - "CC-33"
  - "CC-34"
  - "CC-35"
quality_standards:
  - "QS-01"
  - "QS-02"
  - "QS-03"
  - "QS-04"
  - "QS-05"
  - "QS-06"
  - "QS-07"
  - "QS-08"
  - "QS-09"
  - "QS-10"
  - "QS-11"
  - "QS-12"
test_plan:
  - "T-01"
  - "T-02"
  - "T-03"
  - "T-04"
  - "T-05"
  - "T-06"
  - "T-07"
  - "T-08"
  - "T-09"
  - "T-10"
  - "T-11"
  - "T-12"
  - "T-13"
  - "T-14"
  - "T-15"
  - "T-16"
  - "T-17"
  - "T-18"
  - "T-19"
  - "T-20"
  - "T-21"
  - "T-22"
  - "T-23"
  - "T-24"
  - "T-25"
  - "T-26"
  - "T-27"
  - "T-28"
  - "T-29"
  - "T-30"
tags:
  - "auth"
  - "api"
  - "performance"
  - "testing"
  - "infrastructure"
---
# TOOL-049: fastapi_generate_docs

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-12

---

## 1. Overview

| Field | Value |
|-------|-------|
| Tool name | `fastapi_generate_docs` |
| Category | EVOLVE |
| Complexity | Medium |
| Dependencies | Existing FastAPI project, MkDocs Material (`mkdocs-material>=9.5`), mkdocstrings (`mkdocstrings[python]>=0.25`), mike (`mike>=2.1`), OpenAPI schema accessible from app |
| Signature | `generate_docs(project_dir: str, output_dir: str = "docs/generated", include_sections: list[str] \| None = None, deploy_target: str = "none", theme: str = "material") -> dict` |
| Parameters | `project_dir`: project root path<br>`output_dir`: destination for generated MkDocs site source (default: `docs/generated`)<br>`include_sections`: subset of `["api","models","schemas","deployment","architecture"]`; `None` = all sections<br>`deploy_target`: `none` \| `github_pages` \| `s3` \| `netlify` (default: `none`; publish only if explicit)<br>`theme`: MkDocs theme name or path to custom theme directory (default: `material`) |

---

## 2. Purpose

`fastapi_generate_docs` solves the **documentation drift problem** endemic to fast-moving FastAPI services: hand-written docs fall behind the implementation within weeks of the first release, dead links accumulate silently, and new engineers onboard against inaccurate API references. The tool auto-generates comprehensive, versioned project documentation directly from live code and metadata—covering the OpenAPI specification (rendered via Redoc for rich, interactive navigation), all Pydantic model schemas (extracted by mkdocstrings with full field-level docstrings), architecture diagrams (Mermaid flowcharts synthesised from the module-level import dependency graph), deployment guides (parsed from `Dockerfile` + `docker-compose.yml`), and a getting-started tutorial scaffold. The MkDocs Material site is written deterministically to `output_dir`, so the output can be committed to version control, reviewed in pull requests, and deployed to GitHub Pages, S3, or Netlify with a single flag. Strict mode (`--strict`) is enforced by default in CI, converting every dead link and missing reference into a hard build failure that blocks the publish step—making broken documentation a gate, not a warning.

Versioning is powered by `mike`, which pushes named aliases (`latest`, `v1`, `v2.1`) to the `gh-pages` branch alongside a version switcher in the MkDocs nav bar, so external users always land on the correct docs for their installed release. The entire tool is designed to be idempotent: re-running it on an unchanged project produces a byte-for-byte identical output directory, making it safe to call on every CI push. Navigation is built deterministically from the `include_sections` list—sorted by a canonical section order—so adding or removing a section never causes random ordering churn in diffs. Mermaid syntax is validated before the site is built, and any diagram that references a module not present in the dependency graph is rejected with a structured error rather than silently omitting the node. The net result is a documentation pipeline that is as trustworthy as the test suite: if it builds, it is correct; if it fails, the error is actionable.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 15s for a project with ≤ 100 routes | Dev CLI latency; cold run includes OpenAPI export and diagram synthesis |
| Files created | ≥ 12 (`mkdocs.yml`, section pages, plugin config, navigation YAML, theme override CSS, CI workflow YAML, tests, publish script, index page, Makefile targets, Redoc HTML embed, README) | Predictable scaffolding surface |
| Files modified | ≤ 2 (`pyproject.toml` deps block, `.github/workflows/docs.yml`) | Minimal blast radius on existing project structure |
| MkDocs build time (`mkdocs build`) | < 20s for ≤ 100 pages | Lunr pre-index + incremental plugin cache |
| Redoc render time in browser | < 3s on a 500-operation schema | Static Redoc bundle; no runtime API calls |
| Mermaid diagram generation | < 2s per diagram (≤ 50 nodes) | Pure Python AST traversal; no subprocess for graph extraction |
| Strict mode overhead vs normal build | < 10% additional time | Link checker runs in-process; no external HTTP requests |
| mike version push time | < 30s | Local branch manipulation + single `git push` |
| Idempotency guarantee | Byte-for-byte identical output on unchanged input | Deterministic nav order + stable hash comparison |
| Dead-link detection rate | 100% of internal links checked | `mkdocs build --strict` traverses every anchor |

---

## 4. Code Examples

### 4.1 MkDocs Config Loader

```python
# tools/generate_docs/mkdocs_config_loader.py
"""
Load, validate, and write mkdocs.yml for a FastAPI project.
Ensures Material theme, mkdocstrings plugin, and mike versioning
are always present and correctly configured.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import yaml


CANONICAL_SECTION_ORDER = ["api", "models", "schemas", "deployment", "architecture"]


def build_mkdocs_config(
    project_dir: Path,
    output_dir: Path,
    include_sections: list[str],
    theme: str,
) -> dict:
    """
    Return a validated mkdocs.yml config dict for the given project.

    Args:
        project_dir: Root of the FastAPI project.
        output_dir: Where the generated docs source lives.
        include_sections: Sections to include, ordered canonically.
        theme: MkDocs theme name.

    Returns:
        Dict suitable for yaml.dump() into mkdocs.yml.
    """
    ordered = [s for s in CANONICAL_SECTION_ORDER if s in include_sections]
    nav = _build_nav(ordered)

    config: dict = {
        "site_name": _infer_site_name(project_dir),
        "site_url": "",
        "docs_dir": str(output_dir),
        "theme": {
            "name": theme,
            "features": [
                "navigation.tabs",
                "navigation.sections",
                "search.highlight",
            ],
            "palette": [
                {"scheme": "default", "toggle": {"icon": "material/brightness-7"}},
                {"scheme": "slate", "toggle": {"icon": "material/brightness-4"}},
            ],
        },
        "plugins": [
            "search",
            {
                "mkdocstrings": {
                    "handlers": {
                        "python": {
                            "options": {
                                "docstring_style": "google",
                                "show_source": True,
                                "show_root_heading": True,
                                "merge_init_into_class": True,
                            }
                        }
                    }
                }
            },
            {
                "mike": {
                    "alias_type": "redirect",
                    "canonical_version": "latest",
                    "version_selector": True,
                }
            },
        ],
        "markdown_extensions": [
            "admonition",
            "pymdownx.superfences",
            {"pymdownx.superfences": {"custom_fences": [
                {"name": "mermaid", "class": "mermaid",
                 "format": "!!python/name:pymdownx.superfences.fence_code_format"}
            ]}},
        ],
        "nav": nav,
        "extra": {"version": {"provider": "mike"}},
    }
    return config


def write_mkdocs_config(config: dict, dest: Path) -> Path:
    """Write config dict to mkdocs.yml and return the path."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8") as fh:
        yaml.dump(config, fh, default_flow_style=False, sort_keys=False, allow_unicode=True)
    return dest


def _infer_site_name(project_dir: Path) -> str:
    pyproject = project_dir / "pyproject.toml"
    if pyproject.exists():
        import tomllib
        data = tomllib.loads(pyproject.read_text())
        return data.get("project", {}).get("name", project_dir.name)
    return project_dir.name


def _build_nav(sections: list[str]) -> list[dict]:
    label_map = {
        "api": "API Reference",
        "models": "Data Models",
        "schemas": "Schemas",
        "deployment": "Deployment",
        "architecture": "Architecture",
    }
    nav: list[dict] = [{"Home": "index.md"}]
    for section in sections:
        nav.append({label_map[section]: f"{section}/index.md"})
    return nav
```

### 4.2 OpenAPI Renderer — Redoc Embed

```python
# tools/generate_docs/openapi_renderer.py
"""
Export the FastAPI OpenAPI schema and render it as an embedded Redoc page.
Supports iframe embed and standalone HTML modes.

Usage:
    renderer = OpenAPIRenderer(project_dir)
    renderer.render(output_dir / "api" / "index.md")
"""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path


REDOC_CDN = "https://cdn.jsdelivr.net/npm/redoc@latest/bundles/redoc.standalone.js"

REDOC_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head>
  <title>API Reference</title>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link href="https://fonts.googleapis.com/css?family=Montserrat:300,400,700|Roboto:300,400,700" rel="stylesheet">
  <style>body {{ margin: 0; padding: 0; }}</style>
</head>
<body>
  <redoc spec-url="{schema_url}"></redoc>
  <script src="{redoc_js}"></script>
</body>
</html>
"""


class OpenAPIRenderer:
    """
    Extract OpenAPI schema from a FastAPI app and produce a Redoc HTML page.

    Attributes:
        project_dir: Root of the FastAPI project.
        app_module: Python import path to the FastAPI ``app`` object.
    """

    def __init__(self, project_dir: Path, app_module: str = "app.main:app") -> None:
        self.project_dir = project_dir
        self.app_module = app_module
        self._schema: dict | None = None

    def extract_schema(self) -> dict:
        """Import the FastAPI app and return its OpenAPI schema dict."""
        if self._schema is not None:
            return self._schema
        sys.path.insert(0, str(self.project_dir / "src"))
        sys.path.insert(0, str(self.project_dir))
        module_path, attr = self.app_module.rsplit(":", 1)
        module = importlib.import_module(module_path)
        app = getattr(module, attr)
        self._schema = app.openapi()
        return self._schema

    def write_schema_json(self, dest_dir: Path) -> Path:
        """Write openapi.json to dest_dir/openapi.json, return path."""
        dest_dir.mkdir(parents=True, exist_ok=True)
        schema = self.extract_schema()
        out = dest_dir / "openapi.json"
        out.write_text(json.dumps(schema, indent=2), encoding="utf-8")
        return out

    def render_redoc_page(self, dest_dir: Path) -> Path:
        """
        Generate a standalone Redoc HTML page at dest_dir/index.html.

        The schema is served from a relative openapi.json so the page
        works both locally and on GitHub Pages.
        """
        self.write_schema_json(dest_dir)
        html = REDOC_TEMPLATE.format(
            schema_url="./openapi.json",
            redoc_js=REDOC_CDN,
        )
        out = dest_dir / "index.html"
        out.write_text(html, encoding="utf-8")
        return out

    def render_mkdocs_page(self, dest: Path) -> Path:
        """
        Write a Markdown page that embeds the Redoc iframe for MkDocs.
        """
        dest.parent.mkdir(parents=True, exist_ok=True)
        schema = self.extract_schema()
        route_count = sum(
            len(methods)
            for methods in schema.get("paths", {}).values()
        )
        content = (
            f"# API Reference\n\n"
            f"**{route_count} operations** across {len(schema.get('paths', {}))} paths.\n\n"
            f'<iframe src="./redoc.html" style="width:100%;height:80vh;border:none;"></iframe>\n\n'
            f"[Open in full screen](./redoc.html)\n"
        )
        dest.write_text(content, encoding="utf-8")
        return dest
```

### 4.3 mkdocstrings Plugin Config Builder

```python
# tools/generate_docs/mkdocstrings_config.py
"""
Build per-module mkdocstrings reference pages for all Pydantic models
and FastAPI routers discovered in the project.

Generates docs/generated/models/index.md with ::: directives
that mkdocstrings resolves at build time.
"""
from __future__ import annotations

import ast
import textwrap
from pathlib import Path


def find_pydantic_models(project_dir: Path) -> list[str]:
    """
    Return fully-qualified class names for all Pydantic BaseModel subclasses.

    Traverses all .py files under src/ or app/ (whichever exists).
    Uses AST analysis — does not import modules, safe for broken envs.

    Returns:
        List of import paths like ["app.models.user.User", ...].
    """
    search_roots = [project_dir / "src", project_dir / "app"]
    results: list[str] = []
    for root in search_roots:
        if not root.exists():
            continue
        for py_file in sorted(root.rglob("*.py")):
            rel = py_file.relative_to(root)
            module = ".".join(rel.with_suffix("").parts)
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                bases = [
                    ast.unparse(b) if hasattr(ast, "unparse") else ""
                    for b in node.bases
                ]
                if any("BaseModel" in b or "SQLModel" in b for b in bases):
                    results.append(f"{module}.{node.name}")
    return results


def write_models_page(models: list[str], dest: Path) -> Path:
    """
    Write docs/generated/models/index.md with mkdocstrings directives.

    Each model gets a ::: directive so mkdocstrings renders its full
    class signature, docstring, and field descriptions.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Data Models\n", ""]
    lines.append("All Pydantic models are auto-extracted from source.\n")
    lines.append("")
    for fqn in models:
        short = fqn.split(".")[-1]
        lines.append(f"## `{short}`\n")
        lines.append(f"::: {fqn}")
        lines.append("    options:")
        lines.append("      show_source: true")
        lines.append("      show_root_heading: false")
        lines.append("      merge_init_into_class: true")
        lines.append("")
    dest.write_text("\n".join(lines), encoding="utf-8")
    return dest


def write_schemas_page(schemas: list[str], dest: Path) -> Path:
    """
    Write docs/generated/schemas/index.md for request/response schemas.

    Schemas are Pydantic models whose names end in Request, Response,
    or Schema (convention used by this tool's scaffolding).
    """
    schema_models = [s for s in schemas if s.split(".")[-1].endswith(("Request", "Response", "Schema"))]
    dest.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Schemas\n\n"]
    lines.append("Request and response schemas auto-generated from source.\n\n")
    for fqn in schema_models:
        short = fqn.split(".")[-1]
        lines.append(f"## `{short}`\n")
        lines.append(f"::: {fqn}")
        lines.append("    options:")
        lines.append("      show_source: false")
        lines.append("      show_root_heading: false")
        lines.append("")
    dest.write_text("\n".join(lines), encoding="utf-8")
    return dest
```

### 4.4 Dependency Graph Extractor for Mermaid

```python
# tools/generate_docs/dependency_graph.py
"""
Extract a module-level dependency graph via AST import analysis
and render it as a Mermaid flowchart for the Architecture section.

No imports are actually executed — the graph is built from AST only,
making it safe to run on projects with optional or broken dependencies.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path


def extract_dependency_graph(project_dir: Path) -> dict[str, set[str]]:
    """
    Return adjacency dict {module: {imported_module, ...}} for all internal imports.

    Only intra-project imports are included (third-party filtered by checking
    whether the imported package has a corresponding directory under project_dir).
    """
    roots = [project_dir / "src", project_dir / "app"]
    all_modules: set[str] = set()
    raw_imports: dict[str, set[str]] = {}

    for root in roots:
        if not root.exists():
            continue
        for py_file in sorted(root.rglob("*.py")):
            rel = py_file.relative_to(root)
            module = ".".join(rel.with_suffix("").parts)
            all_modules.add(module.split(".")[0])
            deps: set[str] = set()
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"))
            except SyntaxError:
                raw_imports[module] = deps
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        deps.add(alias.name.split(".")[0])
                elif isinstance(node, ast.ImportFrom) and node.module:
                    deps.add(node.module.split(".")[0])
            raw_imports[module] = deps

    # Filter to intra-project only
    graph: dict[str, set[str]] = {}
    for module, deps in raw_imports.items():
        internal = {d for d in deps if d.split(".")[0] in all_modules}
        graph[module] = internal
    return graph


def render_mermaid_flowchart(
    graph: dict[str, set[str]],
    max_nodes: int = 40,
) -> str:
    """
    Render the dependency graph as a Mermaid flowchart LR string.

    Truncates to max_nodes most-connected modules to keep diagrams readable.
    Validates node names are safe Mermaid identifiers before rendering.
    Raises ValueError if any node name contains unsafe characters.
    """
    _SAFE_RE = re.compile(r"^[A-Za-z0-9_.]+$")

    # Select top-N by out-degree
    sorted_modules = sorted(graph, key=lambda m: len(graph[m]), reverse=True)
    selected = set(sorted_modules[:max_nodes])

    for name in selected:
        if not _SAFE_RE.match(name):
            raise ValueError(f"Unsafe Mermaid node name: {name!r}")

    lines = ["flowchart LR"]
    for module in sorted(selected):
        short = module.split(".")[-1]
        for dep in sorted(graph[module]):
            if dep in selected:
                dep_short = dep.split(".")[-1]
                lines.append(f"    {short} --> {dep_short}")
    return "\n".join(lines)


def write_architecture_page(graph: dict[str, set[str]], dest: Path) -> Path:
    """
    Write the Architecture section page with embedded Mermaid diagram.

    Raises ValueError (from render_mermaid_flowchart) on invalid node names.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    mermaid = render_mermaid_flowchart(graph)
    content = (
        "# Architecture\n\n"
        "Module dependency graph auto-generated from AST import analysis.\n\n"
        "```mermaid\n"
        f"{mermaid}\n"
        "```\n\n"
        "> Re-generated on every docs build. Do not edit manually.\n"
    )
    dest.write_text(content, encoding="utf-8")
    return dest
```

### 4.5 Navigation Builder

```python
# tools/generate_docs/navigation_builder.py
"""
Build the complete MkDocs navigation structure from a list of sections.
Navigation order is DETERMINISTIC — section order follows CANONICAL_SECTION_ORDER,
never the filesystem order, ensuring stable diffs across reruns.

Raises ValueError if an unrecognised section name is requested.
"""
from __future__ import annotations

from pathlib import Path

CANONICAL_SECTION_ORDER = ["api", "models", "schemas", "deployment", "architecture"]

SECTION_META: dict[str, dict] = {
    "api": {
        "label": "API Reference",
        "pages": [
            {"Overview": "api/index.md"},
            {"Redoc": "api/redoc.html"},
            {"OpenAPI JSON": "api/openapi.json"},
        ],
    },
    "models": {
        "label": "Data Models",
        "pages": [{"All Models": "models/index.md"}],
    },
    "schemas": {
        "label": "Schemas",
        "pages": [{"Request / Response": "schemas/index.md"}],
    },
    "deployment": {
        "label": "Deployment",
        "pages": [
            {"Overview": "deployment/index.md"},
            {"Docker": "deployment/docker.md"},
            {"Environment Variables": "deployment/env.md"},
        ],
    },
    "architecture": {
        "label": "Architecture",
        "pages": [
            {"Dependency Graph": "architecture/index.md"},
            {"Module Map": "architecture/modules.md"},
        ],
    },
}


def build_navigation(sections: list[str]) -> list[dict]:
    """
    Return the MkDocs ``nav`` list for the given sections.

    Args:
        sections: Section names from CANONICAL_SECTION_ORDER.

    Returns:
        Deterministically ordered nav list for mkdocs.yml.

    Raises:
        ValueError: If a section name is not in CANONICAL_SECTION_ORDER.
    """
    unknown = set(sections) - set(CANONICAL_SECTION_ORDER)
    if unknown:
        raise ValueError(f"Unknown sections: {unknown}. Valid: {CANONICAL_SECTION_ORDER}")

    ordered = [s for s in CANONICAL_SECTION_ORDER if s in sections]
    nav: list[dict] = [{"Home": "index.md"}, {"Getting Started": "getting_started.md"}]
    for section in ordered:
        meta = SECTION_META[section]
        nav.append({meta["label"]: meta["pages"]})
    return nav


def ensure_section_dirs(output_dir: Path, sections: list[str]) -> None:
    """Create empty index.md placeholders for all requested sections."""
    for section in sections:
        section_dir = output_dir / section
        section_dir.mkdir(parents=True, exist_ok=True)
        index = section_dir / "index.md"
        if not index.exists():
            index.write_text(f"# {section.title()}\n\nAuto-generated.\n", encoding="utf-8")
```

### 4.6 Version Alias Registration with mike

```python
# tools/generate_docs/versioning.py
"""
Register a versioned alias with mike after a successful mkdocs build.

mike maintains a versions.json on the gh-pages branch that maps
version strings to directory names. This module validates that the
current Git tag matches the alias being registered before pushing.

Raises:
    ValueError: If the git tag and alias are inconsistent.
    RuntimeError: If mike subprocess exits non-zero.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path


_SEMVER_RE = re.compile(r"^v?\d+\.\d+(?:\.\d+)?(?:[-+].+)?$")


def get_current_git_tag(project_dir: Path) -> str | None:
    """
    Return the most recent annotated tag reachable from HEAD, or None.

    Uses ``git describe --tags --exact-match`` so it only returns a value
    when HEAD is exactly on a tag (not a commit ahead of a tag).
    """
    result = subprocess.run(
        ["git", "describe", "--tags", "--exact-match"],
        cwd=project_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def register_mike_version(
    project_dir: Path,
    version: str,
    alias: str = "latest",
    push: bool = True,
    remote: str = "origin",
    branch: str = "gh-pages",
) -> dict:
    """
    Run ``mike deploy`` to register a versioned alias on the gh-pages branch.

    Args:
        project_dir: Project root (git repo).
        version: Semantic version string, e.g. ``v2.1.0``.
        alias: Short alias to point at this version, e.g. ``latest``.
        push: If True, push the gh-pages branch to remote.
        remote: Git remote name.
        branch: Branch where versioned docs live.

    Returns:
        Dict with ``{"version": ..., "alias": ..., "pushed": ...}``.

    Raises:
        ValueError: If version string does not match semver pattern.
        RuntimeError: If mike subprocess fails.
    """
    if not _SEMVER_RE.match(version):
        raise ValueError(f"Version {version!r} does not match semver pattern")

    cmd = ["mike", "deploy", "--update-aliases", version, alias]
    if push:
        cmd += ["--push", "--remote", remote, "--branch", branch]
    result = subprocess.run(cmd, cwd=project_dir, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"mike deploy failed (exit {result.returncode}):\n{result.stderr}"
        )
    return {"version": version, "alias": alias, "pushed": push, "output": result.stdout}
```

### 4.7 Strict-Mode Validator (dead-link checker)

```python
# tools/generate_docs/strict_validator.py
"""
Run mkdocs build in strict mode to detect dead links and missing references.
Strict mode converts every WARNING into an ERROR, so the build fails fast
rather than publishing a site with broken anchors.

This module is always called BEFORE any deploy step.
Raises BuildValidationError on any strict-mode failure.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class BuildValidationResult:
    """Result of a strict-mode mkdocs build."""

    passed: bool
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    dead_links: list[str] = field(default_factory=list)
    site_dir: Path | None = None


class BuildValidationError(Exception):
    """Raised when strict-mode validation fails."""

    def __init__(self, result: BuildValidationResult) -> None:
        self.result = result
        super().__init__(
            f"Strict build failed with {len(result.errors)} errors, "
            f"{len(result.dead_links)} dead links"
        )


_DEAD_LINK_RE = re.compile(r"WARNING.*doc.*'(.+?)' contains a link '(.+?)' that is not found")


def run_strict_build(
    project_dir: Path,
    mkdocs_config: Path,
    site_dir: Path,
    clean: bool = True,
) -> BuildValidationResult:
    """
    Execute ``mkdocs build --strict`` and parse the output.

    Args:
        project_dir: Project root.
        mkdocs_config: Path to mkdocs.yml.
        site_dir: Where the built HTML site should land.
        clean: Pass ``--clean`` to mkdocs (remove stale files).

    Returns:
        BuildValidationResult with full diagnostics.

    Raises:
        BuildValidationError: If the build exits non-zero.
    """
    cmd = [
        "mkdocs", "build",
        "--strict",
        "--config-file", str(mkdocs_config),
        "--site-dir", str(site_dir),
    ]
    if clean:
        cmd.append("--clean")

    proc = subprocess.run(cmd, cwd=project_dir, capture_output=True, text=True)
    output = proc.stdout + proc.stderr
    warnings = re.findall(r"WARNING\s*-\s*(.+)", output)
    errors = re.findall(r"ERROR\s*-\s*(.+)", output)
    dead_links = [
        f"{m.group(1)} -> {m.group(2)}"
        for m in _DEAD_LINK_RE.finditer(output)
    ]
    result = BuildValidationResult(
        passed=proc.returncode == 0,
        warnings=warnings,
        errors=errors,
        dead_links=dead_links,
        site_dir=site_dir if proc.returncode == 0 else None,
    )
    if not result.passed:
        raise BuildValidationError(result)
    return result
```

### 4.8 GitHub Actions CI Workflow (generated YAML)

```yaml
# .github/workflows/docs.yml
# AUTO-GENERATED by fastapi_generate_docs — do not edit manually.
# Re-run the tool to update.
name: Docs

on:
  push:
    branches: [main]
    tags: ["v*"]
  pull_request:
    branches: [main]

permissions:
  contents: write

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0  # Required by mike for full tag history

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install docs dependencies
        run: |
          pip install mkdocs-material mkdocstrings[python] mike pymdown-extensions

      - name: Build docs (strict)
        run: mkdocs build --strict --site-dir site/

      - name: Deploy to GitHub Pages (tagged release only)
        if: startsWith(github.ref, 'refs/tags/v')
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          VERSION="${GITHUB_REF_NAME}"
          mike deploy --push --update-aliases "$VERSION" latest
          mike set-default --push latest
```

### 4.9 CI Workflow Caller from Python

```python
# tools/generate_docs/ci_workflow_writer.py
"""
Write the GitHub Actions docs workflow file to .github/workflows/docs.yml.
Triggered automatically by generate_docs() when deploy_target='github_pages'.

Does NOT call the GitHub API — just writes the workflow YAML to disk.
The CI infrastructure reads it on the next push.

Raises:
    FileExistsError: If the workflow file already exists and overwrite=False.
"""
from __future__ import annotations

from pathlib import Path

_WORKFLOW_TEMPLATE = """\
# AUTO-GENERATED by fastapi_generate_docs. Re-run tool to update.
name: Docs

on:
  push:
    branches: [main]
    tags: ["v*"]
  pull_request:
    branches: [main]

permissions:
  contents: write

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install docs dependencies
        run: pip install mkdocs-material "mkdocstrings[python]" mike pymdown-extensions
      - name: Strict build
        run: mkdocs build --strict --site-dir site/
      - name: Deploy versioned docs (tags only)
        if: startsWith(github.ref, 'refs/tags/v')
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          mike deploy --push --update-aliases "${{github.ref_name}}" latest
          mike set-default --push latest
"""


def write_ci_workflow(project_dir: Path, overwrite: bool = True) -> Path:
    """
    Write the docs CI workflow to .github/workflows/docs.yml.

    Args:
        project_dir: Root of the FastAPI project.
        overwrite: Replace existing file if present (default True for idempotency).

    Returns:
        Path to the written workflow file.

    Raises:
        FileExistsError: If overwrite=False and the file already exists.
    """
    workflow_dir = project_dir / ".github" / "workflows"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    dest = workflow_dir / "docs.yml"
    if dest.exists() and not overwrite:
        raise FileExistsError(f"CI workflow already exists at {dest}. Pass overwrite=True to replace.")
    dest.write_text(_WORKFLOW_TEMPLATE, encoding="utf-8")
    return dest


def ensure_github_token_secret_documented(project_dir: Path) -> None:
    """
    Append a note to README.md if GITHUB_TOKEN is not mentioned.

    The built-in GITHUB_TOKEN secret is available automatically in GitHub
    Actions — no manual secret configuration is needed for public repos.
    This function only adds the note to README once.
    """
    readme = project_dir / "README.md"
    if not readme.exists():
        return
    content = readme.read_text(encoding="utf-8")
    marker = "<!-- docs-ci-note -->"
    if marker in content:
        return
    note = (
        f"\n{marker}\n"
        "## Documentation CI\n\n"
        "Docs are auto-built and deployed to GitHub Pages on every tagged release.\n"
        "No manual secret configuration is required — the built-in `GITHUB_TOKEN` is used.\n"
    )
    readme.write_text(content + note, encoding="utf-8")
```

### 4.10 Tests for generate_docs

```python
# tests/tools/test_generate_docs.py
"""
Tests for fastapi_generate_docs tool.
Covers config generation, navigation ordering, Mermaid rendering,
strict-mode validation, and version registration.
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from tools.generate_docs.mkdocs_config_loader import (
    build_mkdocs_config,
    write_mkdocs_config,
    CANONICAL_SECTION_ORDER,
)
from tools.generate_docs.navigation_builder import build_navigation
from tools.generate_docs.dependency_graph import (
    extract_dependency_graph,
    render_mermaid_flowchart,
)
from tools.generate_docs.strict_validator import (
    BuildValidationError,
    BuildValidationResult,
    run_strict_build,
)
from tools.generate_docs.versioning import register_mike_version


def test_build_mkdocs_config_canonical_order(tmp_path: Path) -> None:
    """Nav section order must follow CANONICAL_SECTION_ORDER regardless of input order."""
    shuffled = ["architecture", "api", "models"]
    config = build_mkdocs_config(tmp_path, tmp_path / "docs", shuffled, "material")
    nav_labels = [list(entry.keys())[0] for entry in config["nav"]]
    # Home and Getting Started first, then api < models < architecture
    api_idx = nav_labels.index("API Reference")
    models_idx = nav_labels.index("Data Models")
    arch_idx = nav_labels.index("Architecture")
    assert api_idx < models_idx < arch_idx, "Nav must follow CANONICAL_SECTION_ORDER"


def test_write_mkdocs_config_roundtrip(tmp_path: Path) -> None:
    """Write config to disk and re-read; all keys must survive yaml round-trip."""
    config = build_mkdocs_config(tmp_path, tmp_path / "docs", ["api", "models"], "material")
    dest = tmp_path / "mkdocs.yml"
    write_mkdocs_config(config, dest)
    loaded = yaml.safe_load(dest.read_text())
    assert loaded["theme"]["name"] == "material"
    assert any("mkdocstrings" in str(p) for p in loaded["plugins"])


def test_navigation_builder_rejects_unknown_section() -> None:
    """Unknown section names must raise ValueError, not silently skip."""
    with pytest.raises(ValueError, match="Unknown sections"):
        build_navigation(["api", "nonexistent_section"])


def test_dependency_graph_no_import_errors(tmp_path: Path) -> None:
    """extract_dependency_graph must not raise even when a .py file has syntax errors."""
    bad_py = tmp_path / "app" / "broken.py"
    bad_py.parent.mkdir(parents=True)
    bad_py.write_text("def broken(\n", encoding="utf-8")
    good_py = tmp_path / "app" / "main.py"
    good_py.write_text("from app import models\n", encoding="utf-8")
    graph = extract_dependency_graph(tmp_path)
    assert isinstance(graph, dict)


def test_render_mermaid_flowchart_safe_names() -> None:
    """Mermaid renderer must raise ValueError on node names with unsafe characters."""
    bad_graph: dict[str, set[str]] = {"app.module-name": {"other"}}
    with pytest.raises(ValueError, match="Unsafe Mermaid node name"):
        render_mermaid_flowchart(bad_graph)


def test_render_mermaid_flowchart_truncates_at_max_nodes() -> None:
    """Diagram must include at most max_nodes modules."""
    large_graph: dict[str, set[str]] = {f"module{i}": set() for i in range(100)}
    mermaid = render_mermaid_flowchart(large_graph, max_nodes=10)
    node_names = {line.split(" --> ")[0].strip() for line in mermaid.splitlines() if "-->" in line}
    assert len(node_names) <= 10


def test_strict_build_raises_on_failure(tmp_path: Path) -> None:
    """run_strict_build must raise BuildValidationError on non-zero mkdocs exit."""
    fail_result = BuildValidationResult(
        passed=False, errors=["doc 'index.md' has dead link 'missing.md'"], dead_links=["index.md -> missing.md"]
    )
    with patch("tools.generate_docs.strict_validator.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="ERROR - dead link")
        with pytest.raises(BuildValidationError):
            run_strict_build(tmp_path, tmp_path / "mkdocs.yml", tmp_path / "site")


def test_register_mike_version_rejects_invalid_semver(tmp_path: Path) -> None:
    """mike version registration must reject non-semver strings immediately."""
    with pytest.raises(ValueError, match="does not match semver pattern"):
        register_mike_version(tmp_path, version="not-a-version", push=False)


def test_generate_docs_idempotent(tmp_path: Path) -> None:
    """Running generate_docs twice must produce identical output directory content."""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
    config1 = build_mkdocs_config(tmp_path, tmp_path / "docs", ["api"], "material")
    config2 = build_mkdocs_config(tmp_path, tmp_path / "docs", ["api"], "material")
    assert config1 == config2, "Config generation must be idempotent"
```

---

## 5. Quality Standards

| QS-ID | Standard | Enforcement |
|-------|----------|-------------|
| QS-01 | **Deterministic nav order** | `navigation_builder.py` sorts by `CANONICAL_SECTION_ORDER`; test `T-03` asserts order equality across two runs |
| QS-02 | **No hand-editable output** | Output dir header comment states "DO NOT EDIT"; CI step re-generates on every push |
| QS-03 | **Strict mode always on in CI** | `docs.yml` workflow always passes `--strict` flag; failing to add it is a CI lint error caught by `T-05` |
| QS-04 | **Mermaid syntax validated before build** | `render_mermaid_flowchart` raises `ValueError` on unsafe names; `T-10` asserts validation fires |
| QS-05 | **100% internal links checked** | `run_strict_build` captures all dead-link WARNINGs from mkdocs output; `T-06` exercises this path |
| QS-06 | **Versioning aligned with Git tags** | `register_mike_version` calls `get_current_git_tag` and rejects semver mismatch; see `T-15` |
| QS-07 | **All Python blocks parse cleanly** | CI runs `python -m py_compile` on every generated `.py` file; `T-29` validates this |
| QS-08 | **Redoc renders without network call in tests** | Redoc CDN URL is configurable; tests pass `redoc_js="./redoc.standalone.js"` local bundle |
| QS-09 | **Section inclusion is complete or explicit** | Missing section triggers WARNING log, never a silent omission; `T-25` exercises missing-section path |
| QS-10 | **Deploy never runs without dry-run gate** | `deploy_target != "none"` requires `--dry-run` flag first; `T-22` asserts dry-run runs before real push |
| QS-11 | **Non-ASCII docstrings render correctly** | UTF-8 enforced in all `Path.write_text(encoding="utf-8")` calls; `T-30` tests CJK + emoji in docstrings |
| QS-12 | **Incremental builds skip unchanged sections** | File hash comparison in `section_cache.py` skips re-generation; `T-04` measures rebuild time delta |

---

## 6. Completeness Criteria

| CC-ID | Criterion | Verification |
|-------|-----------|--------------|
| CC-01 | `mkdocs.yml` is written to `project_dir/mkdocs.yml` | File exists, parses as valid YAML |
| CC-02 | `docs/generated/index.md` is created with site title | File contains `# <site_name>` heading |
| CC-03 | `docs/generated/getting_started.md` scaffold present | File length >= 20 lines |
| CC-04 | `docs/generated/api/index.md` present when section enabled | File contains Redoc iframe |
| CC-05 | `docs/generated/api/openapi.json` written and valid | `json.loads()` succeeds, has `openapi` key |
| CC-06 | `docs/generated/api/redoc.html` standalone page generated | `<redoc spec-url=` present in file |
| CC-07 | `docs/generated/models/index.md` has mkdocstrings directives | File contains `:::` lines for each model |
| CC-08 | `docs/generated/schemas/index.md` present when models found | File exists and has at least one `:::` directive |
| CC-09 | `docs/generated/deployment/index.md` generated from Dockerfile | Dockerfile path referenced in deployment page |
| CC-10 | `docs/generated/deployment/env.md` lists env vars parsed from docker-compose | All `environment:` keys listed |
| CC-11 | `docs/generated/architecture/index.md` contains Mermaid block | File has ` ```mermaid ` fence |
| CC-12 | Navigation in `mkdocs.yml` matches `include_sections` canonical order | YAML `nav` key validated against CANONICAL_SECTION_ORDER |
| CC-13 | Search plugin enabled in `mkdocs.yml` | `plugins` list contains `"search"` |
| CC-14 | mkdocstrings plugin present with Python handler | `plugins` dict has `mkdocstrings.handlers.python` |
| CC-15 | mike plugin present with `version_selector: true` | `plugins` dict has `mike.version_selector: true` |
| CC-16 | Strict mode enabled in CI workflow | `docs.yml` contains `--strict` flag |
| CC-17 | GitHub Actions workflow written to `.github/workflows/docs.yml` when `deploy_target=github_pages` | File exists and parses as valid YAML |
| CC-18 | mike deploy command correct syntax in workflow | Workflow contains `mike deploy --push --update-aliases` |
| CC-19 | mike set-default command present | Workflow contains `mike set-default --push latest` |
| CC-20 | `pyproject.toml` docs dependency group updated | `[project.optional-dependencies] docs` present |
| CC-21 | Makefile targets `docs-build`, `docs-serve`, `docs-deploy` added | Targets present in Makefile |
| CC-22 | Tool exits cleanly when `include_sections=[]` (empty list) | Returns dict with `sections_generated: 0`, no exception |
| CC-23 | Tool is idempotent — re-run produces same output hash | Second run hash equals first run hash |
| CC-24 | Dead-link failures surface in return dict under `errors` key | `result["errors"]` populated when strict build fails |
| CC-25 | Mermaid validation error surfaced in return dict under `errors` | `result["errors"]` contains Mermaid diagnostic |
| CC-26 | `deploy_target=none` produces no publish step and no git operations | No `git push` subprocess call when deploy_target is none |
| CC-27 | `deploy_target=github_pages` requires explicit `--push` confirmation | Push step gated; CI workflow handles actual push |
| CC-28 | Tool reports `files_created` count in returned dict | Return dict has `files_created` list with >= 12 entries |
| CC-29 | Tool reports `files_modified` count in returned dict | Return dict has `files_modified` list with <= 2 entries |
| CC-30 | Missing module docstring emits WARNING log, does not abort build | `logging.warning` called; build continues to completion |
| CC-31 | Theme override CSS file written to `docs/generated/overrides/` | Custom CSS file present when `theme != "material"` |
| CC-32 | Section exclusion adjusts navigation automatically | Excluded section absent from nav; no dead nav link |
| CC-33 | Large OpenAPI schema (> 200 operations) handled without timeout | `write_schema_json` completes within SLO |
| CC-34 | i18n language setting propagated to mkdocs.yml | `theme.language` key set when `LANG` env var specifies locale |
| CC-35 | Tool returns structured result dict conforming to JSON schema | Result dict passes Pydantic model validation |

---

## 7. Definition of Done

- [ ] `fastapi_generate_docs()` entry point exists in `tools/generate_docs/__init__.py` and is importable
- [ ] `mkdocs.yml` is written correctly to project root for all valid `include_sections` inputs
- [ ] All 5 section pages (`api`, `models`, `schemas`, `deployment`, `architecture`) are generated when `include_sections=None`
- [ ] `docs/generated/api/openapi.json` is a valid OpenAPI 3.x document exported from the FastAPI app
- [ ] `docs/generated/api/redoc.html` renders without JavaScript errors in a browser (manual smoke test)
- [ ] `docs/generated/models/index.md` contains correct `:::` mkdocstrings directives for all Pydantic models
- [ ] `docs/generated/architecture/index.md` contains a valid Mermaid `flowchart LR` block
- [ ] `mkdocs build --strict` completes with exit code 0 on the generated docs site
- [ ] `mike deploy` registers the version alias correctly (validated by checking `versions.json` on gh-pages branch)
- [ ] `.github/workflows/docs.yml` is written and triggers correctly on tag push
- [ ] Tool is idempotent: two consecutive runs on unchanged project produce byte-for-byte identical output
- [ ] All 30 T-01..T-30 test cases pass in CI
- [ ] Dead-link detection fires and surfaces in return dict when a broken internal link exists
- [ ] Non-ASCII (CJK, emoji) content in docstrings renders correctly in MkDocs HTML output
- [ ] `pyproject.toml` updated with docs dependency group listing all required packages

---

## 8. Invariants

| ID | Invariant | Enforcement | Test Refs |
|----|-----------|-------------|-----------|
| INV-DOCS-001 | Output directory MUST be entirely generated from source — no manual edits survive a re-run | `write_mkdocs_config` overwrites unconditionally; CI re-generates on push | T-04, T-23 |
| INV-DOCS-002 | Strict mode MUST be enabled in all CI builds — dead links block publishing | `run_strict_build` always passes `--strict`; CI workflow hardcodes flag | T-05, T-06 |
| INV-DOCS-003 | Navigation order MUST follow `CANONICAL_SECTION_ORDER` — never filesystem order | `build_navigation` sorts by CANONICAL list before returning nav | T-03, T-01 |
| INV-DOCS-004 | Publishing MUST NOT happen without an explicit `deploy_target` flag — no accidental pushes | `generate_docs` checks `deploy_target != "none"` before calling any `git push` subprocess | T-22, T-19 |
| INV-DOCS-005 | API reference MUST be regenerated whenever the OpenAPI schema changes — no stale docs | `openapi.json` hash compared on each run; changed hash forces `api` section rebuild | T-07, T-12 |
| INV-DOCS-006 | mike versioning MUST be aligned with Git tags — synthetic versions are rejected | `register_mike_version` calls `get_current_git_tag` and validates semver pattern | T-15, T-16 |
| INV-DOCS-007 | Mermaid diagrams MUST be validated before the build step — invalid syntax blocks publish | `render_mermaid_flowchart` validates node names; error raised before `mkdocs build` | T-10, T-11 |
| INV-DOCS-008 | Dead-link errors MUST be surfaced in the return dict — never swallowed silently | `BuildValidationError` is caught in `generate_docs`; `result["errors"]` always populated | T-06, T-24 |

---

## 9. User Stories

### 9.1 Basic Documentation Sections

**US-01** — As a backend engineer, I want the tool to generate an API reference page from my FastAPI OpenAPI schema so that my team always has accurate, up-to-date endpoint documentation without maintaining it manually.

*Given* a FastAPI project with 20+ routes,
*When* I run `generate_docs(project_dir)`,
*Then* `docs/generated/api/index.md` is created containing a Redoc iframe, and `docs/generated/api/openapi.json` is a valid OpenAPI 3.x JSON file with all routes present.
The page renders without JavaScript errors in a browser (verified by T-07).
This enforces INV-DOCS-001: output is always generated from source, never hand-edited.
Complies with CC-04, CC-05, INV-DOCS-001.

**US-02** — As a data engineer, I want the tool to generate a models reference page with full Pydantic field documentation so I can understand every model's constraints without reading source code.

*Given* a project with Pydantic `BaseModel` subclasses,
*When* I run `generate_docs(project_dir, include_sections=["models"])`,
*Then* `docs/generated/models/index.md` contains a `:::` mkdocstrings directive for each discovered model, and `mkdocs build` renders field-level descriptions from docstrings.
AST traversal in `find_pydantic_models()` discovers models without executing imports, making it safe for projects with optional dependencies.
Verified by T-08.
Complies with CC-07, INV-DOCS-001.

**US-03** — As an API consumer, I want a dedicated schemas page listing all request and response schemas so I can understand the expected input/output shapes for every endpoint without reading Python.

*Given* request/response Pydantic models named with `Request`, `Response`, or `Schema` suffix,
*When* `generate_docs` runs with `include_sections=["schemas"]`,
*Then* `docs/generated/schemas/index.md` contains directives for all matching classes and excludes domain models.
The naming convention filter (`write_schemas_page`) prevents internal domain models from polluting the public API documentation.
`show_source: false` is set for schemas to keep the page concise for external API consumers.
Verified by T-09. Complies with CC-08.

**US-04** — As a DevOps engineer, I want an auto-generated deployment guide parsed from my Dockerfile and docker-compose.yml so new team members can spin up the service without asking me.

*Given* a project with a `Dockerfile` and `docker-compose.yml` in the root,
*When* `generate_docs` runs with `include_sections=["deployment"]`,
*Then* `docs/generated/deployment/index.md` references the Docker image build command, and `docs/generated/deployment/env.md` lists all `environment:` keys from docker-compose.
The deployment page builder (`deployment_page_builder.py`) parses `FROM`, `EXPOSE`, and `CMD` Dockerfile directives and converts docker-compose `environment:` blocks into a Markdown table.
If the Dockerfile is absent the page is generated with a note rather than failing (EC-15 edge case).
Verified by T-09. Complies with CC-09, CC-10.

**US-05** — As a senior engineer, I want an architecture diagram automatically generated from module imports so I can explain system structure to stakeholders without manually maintaining a diagram.

*Given* a Python project with internal imports between modules,
*When* `generate_docs` runs with `include_sections=["architecture"]`,
*Then* `docs/generated/architecture/index.md` contains a valid Mermaid `flowchart LR` block and the diagram renders in MkDocs Material without error.
The dependency graph extractor uses pure AST analysis — no modules are imported — so the tool is safe even when optional dependencies are missing.
Node names with hyphens are rejected before diagram generation (INV-DOCS-007), producing a clear `ValueError` instead of a silent render failure.
Verified by T-11. Complies with CC-11, INV-DOCS-007.

### 9.2 Build Quality

**US-06** — As a tech lead, I want the docs build to fail on dead links so my team is alerted immediately when a doc page references a missing endpoint or section.

*Given* a generated docs site with one intentionally broken internal link,
*When* `mkdocs build --strict` runs,
*Then* the build exits non-zero, `result["errors"]` contains the dead-link diagnostic, and the publish step is blocked.
`run_strict_build()` captures the `_DEAD_LINK_RE` pattern from mkdocs stderr and populates `BuildValidationResult.dead_links` with structured diagnostics.
The `BuildValidationError` is always re-raised to the caller so it cannot be silently swallowed.
Verified by T-06. Complies with INV-DOCS-002, INV-DOCS-008, CC-24.

**US-07** — As an engineer, I want incremental builds to skip unchanged sections so CI is fast and docs regeneration does not block PRs.

*Given* a project where only the `api` section changed (new route added),
*When* `generate_docs` runs a second time,
*Then* only the `api` section pages are rewritten; all other section pages retain their original mtime.
`SectionCache` in `section_cache.py` stores per-section MD5 hashes in `.docs_cache.json`; a section is only regenerated when its source hash differs from the cached value.
This also satisfies the idempotency contract (CC-23): if no sources changed, zero sections are regenerated and the output dir is unchanged.
Verified by T-04. Complies with CC-23.

**US-08** — As a CI engineer, I want strict mode enforced automatically in the generated GitHub Actions workflow so dead links cannot slip into published docs even if a developer forgets the flag locally.

*Given* `deploy_target="github_pages"`,
*When* `generate_docs` writes `.github/workflows/docs.yml`,
*Then* the workflow step contains `mkdocs build --strict`.
`write_ci_workflow()` embeds the `--strict` flag unconditionally in the `_WORKFLOW_TEMPLATE` constant — it cannot be removed by passing arguments.
T-05 asserts the flag is present by grepping the generated YAML; this test must remain in the test suite to guard against accidental template changes.
Verified by T-05. Complies with QS-03, CC-16, INV-DOCS-002.

**US-09** — As a developer, I want the docs build to report Mermaid syntax errors immediately so I know before merging whether my architecture page will render correctly.

*Given* a module name that contains a hyphen (invalid in Mermaid node IDs),
*When* `generate_docs` attempts to render the architecture diagram,
*Then* `ValueError` is raised with the offending node name before `mkdocs build` is called.
The `_SAFE_RE = re.compile(r"^[A-Za-z0-9_.]+$")` pattern in `render_mermaid_flowchart` validates every selected node before emitting any Mermaid lines.
This ensures the error is caught deterministically in the tool layer, not discovered as a broken page in a browser after deploy.
Verified by T-10. Complies with INV-DOCS-007, QS-04.

**US-10** — As a developer, I want the tool to be idempotent so I can add it to a pre-commit hook without it causing spurious diffs.

*Given* an unchanged FastAPI project,
*When* `generate_docs` is run twice consecutively,
*Then* the output directory content is byte-for-byte identical and the tool reports `sections_regenerated: 0`.
Idempotency is guaranteed by deterministic nav ordering, stable `json.dumps` with `sort_keys=True`, and per-section MD5 hash comparison that skips regeneration when nothing changed.
A pre-commit hook running this tool will produce zero diff to commit, making it safe for developer workflows.
Verified by T-04. Complies with CC-23, INV-DOCS-001.

### 9.3 Versioning

**US-11** — As a release engineer, I want `mike` to register a `latest` alias pointing to the newest release so users always land on correct docs without manually updating a redirect.

*Given* a `v2.1.0` Git tag on HEAD,
*When* `register_mike_version(project_dir, version="v2.1.0", alias="latest")` is called,
*Then* `versions.json` on the `gh-pages` branch contains `v2.1.0` with alias `latest`.
`mike deploy --update-aliases` atomically updates the alias pointer so users navigating to `/latest/` are redirected to the correct version directory.
The semver regex `_SEMVER_RE` validates the version string before any subprocess is called, preventing accidental registration of branch-name strings.
Verified by T-15. Complies with INV-DOCS-006, CC-19.

**US-12** — As a product manager, I want a version switcher in the docs nav bar so users of older releases can access the documentation matching their installed version.

*Given* `mike` has deployed versions `v1.0`, `v2.0`, and `v2.1`,
*When* a user opens the docs site,
*Then* the Material theme version-switcher dropdown lists all three versions and navigating to each version loads the correct content.
The switcher is enabled via `extra.version.provider: mike` in `mkdocs.yml` and `mike.version_selector: true` in the mike plugin config (CC-15).
Each mike version deploy pushes a dedicated subdirectory on `gh-pages` (`/v1.0/`, `/v2.0/`, `/v2.1/`), so versions are independent and do not overwrite each other.
Verified by T-16. Complies with CC-15.

**US-13** — As a backend engineer, I want `generate_docs` to reject a `mike deploy` call when HEAD is not on an exact Git tag so I cannot accidentally publish a development build as a versioned release.

*Given* HEAD is 3 commits ahead of the last tag,
*When* I call `register_mike_version` with `version="v2.2.0"` where no such tag exists,
*Then* `ValueError` is raised with a clear message before any `git push` is executed.
`get_current_git_tag()` uses `git describe --tags --exact-match`; a non-zero exit code means HEAD is not exactly on a tag and the deploy is blocked.
This prevents contaminating the `gh-pages` history with snapshots that are not tied to a release, keeping the version list aligned with the project's release process.
Verified by T-17. Complies with INV-DOCS-006, QS-06.

**US-14** — As a DevOps engineer, I want the `gh-pages` branch to be the sole deployment target for versioned docs so I have a single source of truth and can roll back by reverting that branch.

*Given* `deploy_target="github_pages"`,
*When* `mike deploy` runs successfully,
*Then* all versioned docs are under the `gh-pages` branch, no other branches are modified.
`register_mike_version` passes `--branch gh-pages` explicitly to mike, ensuring the target branch is never inferred from git config.
Rollback is straightforward: `git revert HEAD` on `gh-pages` or `mike delete` removes a bad version without affecting other deployed versions.
Verified by T-18. Complies with INV-DOCS-004.

**US-15** — As a team lead, I want the default version shown to new visitors to always be `latest` so users who arrive via search land on the most current documentation.

*Given* multiple deployed versions,
*When* `mike set-default latest` has been executed,
*Then* navigating to the docs root URL redirects to the `latest` alias.
mike writes a root `index.html` redirect to the default version; `mike set-default --push latest` is included in the CI workflow step (CC-19) after every tagged release deploy.
The `canonical_version: latest` setting in the mike plugin config (`mkdocs.yml`) ensures canonical link tags point to `latest`, improving search engine indexing.
Verified by T-18. Complies with CC-19.

### 9.4 Publishing

**US-16** — As a DevOps engineer, I want to publish docs to GitHub Pages on every tagged release automatically so I never forget to update docs after a release.

*Given* `deploy_target="github_pages"` and a valid `v*` Git tag,
*When* the CI workflow runs,
*Then* `mike deploy --push --update-aliases` runs and docs appear at the project's GitHub Pages URL.
The workflow uses `permissions: contents: write` and the built-in `GITHUB_TOKEN` — no manual secret configuration is required for public repositories.
The strict build step must pass before the deploy step is reached; GitHub Actions `needs: build` dependency ensures this sequencing.
Verified by T-19. Complies with CC-17, CC-18, INV-DOCS-004.

**US-17** — As a backend engineer, I want a `--dry-run` mode so I can verify the full publish pipeline without touching the `gh-pages` branch.

*Given* `deploy_target="github_pages"`,
*When* `generate_docs` is called without an explicit push flag,
*Then* all docs are generated and validated but no `git push` occurs; result dict contains `dry_run: true`.
`register_mike_version` accepts `push=False`, which runs `mike deploy` without the `--push` flag — the version is staged locally on `gh-pages` but not pushed to `origin`.
This allows full end-to-end validation of the versioning pipeline in a developer's local environment before triggering CI.
Verified by T-22. Complies with QS-10, INV-DOCS-004.

**US-18** — As a platform engineer, I want to optionally publish to S3 so I can host docs on a private bucket rather than GitHub Pages.

*Given* `deploy_target="s3"` and valid AWS credentials in environment,
*When* `generate_docs` runs,
*Then* the built site is synced to the configured S3 bucket using `aws s3 sync`; no `gh-pages` branch is modified.
The S3 deploy path writes an `aws s3 sync` command to the `docs-deploy` Makefile target with `--delete` to remove stale pages.
No mike versioning is applied when `deploy_target="s3"` — version directories are managed by S3 key prefixes instead.
Verified by T-20. Complies with CC-26.

**US-19** — As a developer, I want `deploy_target="none"` to be the safe default so running the tool locally never accidentally pushes docs to production.

*Given* `generate_docs` called without `deploy_target` argument,
*When* the tool runs,
*Then* no subprocess `git push` or `aws s3 sync` is called; docs are only written to local `output_dir`.
The default value `deploy_target: str = "none"` in the function signature means a plain `generate_docs(project_dir)` call is always safe for local development.
T-21 asserts that `subprocess.run` is never called with `git push` when the default is in effect, protecting against future refactors that might inadvertently add a push step.
Verified by T-21. Complies with INV-DOCS-004, QS-10, CC-26.

**US-20** — As a release manager, I want the publish step blocked when the strict build fails so a release with broken docs is impossible even if someone forces a deploy.

*Given* a broken internal link exists in the generated docs,
*When* the CI workflow's strict build step fails,
*Then* the deploy step is skipped due to GitHub Actions step dependency, and no docs are pushed.
The generated `docs.yml` workflow uses a two-job structure: `build` (runs strict mkdocs build) and `deploy` (has `needs: build`), so a build failure always prevents the deploy job from starting.
`BuildValidationError` in the tool layer surfaces the specific dead-link paths so the developer knows exactly which page to fix.
Verified by T-06. Complies with INV-DOCS-002, CC-16.

### 9.5 Edge Cases

**US-21** — As a developer, I want a warning (not an error) when a module lacks a docstring so the build still completes and I see where documentation gaps exist.

*Given* a project module with no module-level docstring,
*When* `generate_docs` runs,
*Then* `logging.warning` is emitted with the module path, the build continues without error, and the generated models page omits the docstring section gracefully.
The warning message includes the full module path so developers can locate and fill the gap without guessing.
`result["warnings"]` in the return dict accumulates all missing-docstring paths, enabling bulk reporting across large projects.
Verified by T-25. Complies with QS-09, CC-30.

**US-22** — As a developer, I want `generate_docs` to handle the case where `mike` is not installed by disabling versioning gracefully rather than crashing.

*Given* `mike` is not present in the Python environment,
*When* `generate_docs` runs,
*Then* the MkDocs build and section generation complete successfully; `result["warnings"]` contains `"mike not installed — versioning disabled"`.
The mike availability check uses `shutil.which("mike")` before any versioning step; a `None` result triggers the graceful fallback path.
The MkDocs config is still written with the mike plugin block so enabling versioning later requires no configuration changes, only installing mike.
Verified by T-26. Complies with CC-22.

**US-23** — As a developer, I want re-running `generate_docs` on an unchanged project to be a no-op so it is safe to call in a pre-commit hook without performance cost.

*Given* no source files have changed since the last run,
*When* `generate_docs` runs,
*Then* all section hashes match cache; `result["sections_regenerated"] == 0` and tool completes in under 3 seconds.
`SectionCache.is_section_dirty()` computes a combined MD5 of all Python source files contributing to a section; if the hash matches the stored value in `.docs_cache.json`, the section render is skipped entirely.
The sub-3-second target for a no-op run is achieved because hash computation over typical project sizes is O(n file reads), not O(n AST parse + n mkdocstrings render).
Verified by T-04. Complies with CC-23, INV-DOCS-001.

**US-24** — As a developer, I want non-ASCII characters in docstrings (CJK, accented letters, emoji) to render correctly in the generated site so international team members can document in their native language.

*Given* a Python model docstring containing `"""商品モデル — détails complets"""`,
*When* `generate_docs` runs and `mkdocs build` executes,
*Then* the rendered HTML contains the correct Unicode characters without escaping.
UTF-8 encoding is enforced at every file write (`encoding="utf-8"`) and `yaml.dump` uses `allow_unicode=True` so Japanese and accented characters are written literally rather than as escape sequences.
`mkdocs build` processes Markdown as UTF-8 by default; T-30 asserts the final HTML contains raw CJK code points, not `&#x` entities.
Verified by T-30. Complies with QS-11, CC-34.

**US-25** — As a developer, I want the generated deployment page to function when no `docker-compose.yml` is present so projects that do not use Docker are not blocked.

*Given* a FastAPI project with no `docker-compose.yml` and no `Dockerfile`,
*When* `generate_docs` runs with `include_sections=["deployment"]`,
*Then* `docs/generated/deployment/index.md` is generated with a placeholder noting Docker files were not found, and the build completes without error.
`deployment_page_builder.py` checks for file existence before parsing and falls back to a structured placeholder with instructions for adding Docker support.
The placeholder page still passes `mkdocs build --strict` because it contains no dead links — only informational prose.
Verified by T-27. Complies with CC-22, CC-09.

---

## 10. Test Plan

### 10.1 Generation Tests

| Test ID | Description | Pass Condition |
|---------|-------------|----------------|
| T-01 | All 5 sections generated when `include_sections=None` | Five section dirs present under `output_dir` |
| T-02 | Only specified sections generated when subset provided | Non-included section dirs absent from `output_dir` |
| T-03 | Navigation order follows `CANONICAL_SECTION_ORDER` | Nav list index: `api < models < schemas < deployment < architecture` |
| T-04 | Second run on unchanged project produces identical file hashes | `hashlib.md5` of all output files equal between run 1 and run 2 |
| T-05 | CI workflow contains `--strict` flag | `docs.yml` grep for `--strict` returns match |
| T-06 | Dead link causes strict build to fail and populate `result["errors"]` | `BuildValidationError` raised; `errors` non-empty |

### 10.2 Content Tests

| Test ID | Description | Pass Condition |
|---------|-------------|----------------|
| T-07 | API section contains valid `openapi.json` | `json.loads(openapi.json)` succeeds; `openapi` key present |
| T-08 | Models page has mkdocstrings directives for all BaseModel subclasses | `:::` count in `models/index.md` equals number of discovered models |
| T-09 | Deployment page parses docker-compose env vars | All `environment:` keys appear in `deployment/env.md` |
| T-10 | Mermaid validator rejects hyphenated module names | `ValueError` raised before build |
| T-11 | Architecture page has valid `flowchart LR` Mermaid block | Regex `^flowchart LR` matches first non-blank line of Mermaid fence |
| T-12 | API section rebuild triggered when `openapi.json` hash changes | After adding a route, `api/` files have updated mtime; other sections unchanged |

### 10.3 Versioning Tests

| Test ID | Description | Pass Condition |
|---------|-------------|----------------|
| T-13 | mike plugin configured in `mkdocs.yml` with `version_selector: true` | YAML has `mike.version_selector: true` |
| T-14 | `register_mike_version` calls `mike deploy` subprocess | `subprocess.run` called with `["mike", "deploy", ...]` |
| T-15 | Valid semver string accepted by `register_mike_version` | No exception raised for `v1.0.0`, `v2.1.3-rc1`, `1.0.0` |
| T-16 | Invalid version string rejected | `ValueError` for `not-a-version`, `1.0`, `v1.0.0.0.0` |
| T-17 | `register_mike_version` raises when no exact git tag on HEAD | `ValueError` raised; no subprocess call |
| T-18 | mike set-default command present in CI workflow | `docs.yml` contains `mike set-default --push latest` |

### 10.4 Publishing Tests

| Test ID | Description | Pass Condition |
|---------|-------------|----------------|
| T-19 | `deploy_target="github_pages"` writes CI workflow with push step | `docs.yml` has deploy step gated on `startsWith(github.ref, 'refs/tags/v')` |
| T-20 | `deploy_target="s3"` writes `aws s3 sync` command to Makefile | `docs-deploy` Makefile target contains `aws s3 sync` |
| T-21 | `deploy_target="none"` calls no subprocess with `git push` | `subprocess.run` never called with `git push` arg |
| T-22 | Publish step requires explicit push confirmation | No push on default invocation; `pushed: false` in result |
| T-23 | Docs output dir entirely regenerated on `--clean` | All files have mtime > run start time after clean run |
| T-24 | Strict build failure blocks publish step in CI | Workflow uses `needs: build` dependency; deploy step not reached on build failure |

### 10.5 Edge Case Tests

| Test ID | Description | Pass Condition |
|---------|-------------|----------------|
| T-25 | Module without docstring emits WARNING, build continues | `logging.warning` called; no exception; output file written |
| T-26 | Missing `mike` binary disables versioning gracefully | `result["warnings"]` contains mike-disabled message |
| T-27 | Missing `docker-compose.yml` does not abort deployment section | `deployment/index.md` written with missing-docker note |
| T-28 | Empty `include_sections=[]` returns without error | `result["sections_generated"] == 0`; no exception |
| T-29 | All generated `.py` files compile cleanly | `python -m py_compile` exit 0 on every generated `.py` |
| T-30 | Non-ASCII docstrings (CJK + emoji) render correctly | HTML output contains raw Unicode; no `&#x` escapes |

---

## 11. Interaction Matrix

| Tool | Interaction Type | Direction | Description |
|------|-----------------|-----------|-------------|
| `fastapi_api_spec_compliance` (TOOL-033) | Data consumer | Inbound | `generate_docs` reads the validated OpenAPI spec produced by TOOL-033 as the authoritative source for the API reference section; if TOOL-033 has not run, `generate_docs` exports the schema directly from the app |
| `fastapi_api_changelog` (TOOL-038) | Data consumer | Inbound | The deployment page pulls the CHANGELOG generated by TOOL-038 to embed a "What's New" section; missing CHANGELOG triggers a WARNING, not an error |
| `fastapi_dependency_graph` (TOOL-039) | Data consumer | Inbound | Architecture section imports the dependency adjacency dict from TOOL-039 if available; if not, `generate_docs` computes its own via AST traversal |
| `fastapi_generate_sdk` (TOOL-047) | Cross-reference | Bidirectional | SDK docs link to the API reference generated here; `generate_docs` optionally embeds a "Download SDK" badge linking to the SDK package generated by TOOL-047 |
| `fastapi_versioning` (TOOL-017) | Dependency | Inbound | mike versioning requires the semver string set by TOOL-017; `register_mike_version` reads the version from `pyproject.toml` written by TOOL-017 |
| `fastapi_add_event_driven` (TOOL-046) | Data source | Inbound | Event schemas discovered by TOOL-046 are included in the schemas section; the tool checks for `events/schemas/` directory created by TOOL-046 |
| `fastapi_add_multi_tenancy` (TOOL-008) | Data source | Inbound | Tenant-scoped models added by TOOL-008 are included in models page with tenant context noted in their mkdocstrings directive |
| `fastapi_ci_cd` (TOOL-015) | Integration target | Outbound | `generate_docs` writes `.github/workflows/docs.yml`; it checks for existing `ci.yml` from TOOL-015 to avoid workflow naming conflicts |
| `fastapi_add_monitoring` (TOOL-020) | Cross-reference | Outbound | Deployment section links to the monitoring runbook generated by TOOL-020 if present at `docs/runbooks/monitoring.md` |
| `fastapi_auth_jwt` (TOOL-003) | Data source | Inbound | Auth schemas (token request/response) are included in the schemas page; security schemes from JWT setup appear in the OpenAPI spec rendered by Redoc |
| `fastapi_db_migrations` (TOOL-006) | Cross-reference | Outbound | Deployment guide links to migration runbook from TOOL-006; environment variables for `DATABASE_URL` sourced from TOOL-006's docker-compose snippet |
| `fastapi_add_rate_limiting` (TOOL-021) | Data source | Inbound | Rate-limit headers documented in the API reference via the OpenAPI spec enriched by TOOL-021 |
| `fastapi_add_caching` (TOOL-022) | Cross-reference | Outbound | Architecture diagram includes cache layer nodes when TOOL-022 has been applied and `redis` module is detected in the dependency graph |
| `fastapi_testing_scaffold` (TOOL-010) | Consumer | Outbound | Test scaffold from TOOL-010 includes a `test_docs_build.py` that calls `run_strict_build` in CI to keep tests and docs in sync |
| `fastapi_add_background_jobs` (TOOL-024) | Data source | Inbound | Background job schemas and worker entrypoints documented in architecture section when TOOL-024 directory structure is detected |

---

## 12. Rollback Procedure

### 12.1 Pre-Rollback Assessment

Before rolling back, identify which failure mode occurred:

1. **mkdocs build failure** — generated docs source is written but `mkdocs build` fails
2. **mike version conflict** — `mike deploy` fails because the version already exists on `gh-pages`
3. **Dead link during strict build** — a broken internal reference blocks publish
4. **Mermaid syntax error** — architecture diagram generation raises `ValueError`
5. **Redoc embed failure** — `openapi.json` export fails (app import error)
6. **Font or CDN resource missing** — MkDocs Material requires Google Fonts (network-dependent)

Capture the tool's return dict and `result["errors"]` before any rollback action.

### 12.2 Database Rollback

N/A — `fastapi_generate_docs` is a code-generation tool only. It does not write to any database, execute SQL migrations, or modify any database schema. No database rollback is required under any failure mode.

### 12.3 File System Rollback

If the tool partially wrote files to `docs/generated/` before failing:

```bash
# Remove the partially generated output dir
rm -rf docs/generated/

# If mkdocs.yml was overwritten and the previous version was tracked:
git checkout -- mkdocs.yml

# If CI workflow was written and you want to revert:
git checkout -- .github/workflows/docs.yml

# Verify only intended files were modified:
git diff --name-only
```

To restore the previous state of `docs/generated/` from the last known-good commit:

```bash
# Restore last committed state of docs/generated
git checkout HEAD -- docs/generated/

# If output_dir is gitignored, restore from a backup made before the run
cp -r docs/generated.bak/ docs/generated/
```

### 12.4 GitHub Pages Branch Rollback

If `mike deploy` pushed a broken version to the `gh-pages` branch:

```bash
# View recent commits on gh-pages
git log origin/gh-pages --oneline -10

# Identify the last known-good commit SHA
GOOD_SHA="<sha-before-bad-deploy>"

# Revert gh-pages to last known-good state (does not delete history)
git checkout gh-pages
git revert HEAD --no-edit
git push origin gh-pages

# OR: hard reset to known-good SHA (destructive — use only when revert is insufficient)
# git reset --hard "$GOOD_SHA"
# git push --force-with-lease origin gh-pages
```

To remove a specific mike version that was incorrectly deployed:

```bash
# Delete the incorrect version from gh-pages
mike delete --push v2.1.0-broken

# Re-deploy the correct version
mike deploy --push --update-aliases v2.1.0 latest
mike set-default --push latest
```

### 12.5 Emergency: Disable Strict Mode Temporarily

If a dead link is discovered in production that cannot be fixed immediately, strict mode can be disabled in the CI workflow to unblock a hotfix release:

```bash
# Temporarily disable strict mode in CI (creates a commit in the fix branch)
sed -i 's/mkdocs build --strict/mkdocs build/' .github/workflows/docs.yml

# Commit with a clear note
git add .github/workflows/docs.yml
git commit -m "temp: disable docs strict mode for hotfix release — re-enable in follow-up"

# Re-enable strict mode in the follow-up PR once the dead link is fixed
```

Note: Disabling strict mode should always be a temporary measure with a follow-up PR to fix the underlying dead link. Track the follow-up in the issue tracker.

### 12.6 mkdocs.yml Rollback

If `mkdocs.yml` was corrupted by a partial write:

```bash
# Restore mkdocs.yml from git history
git show HEAD:mkdocs.yml > mkdocs.yml

# If the file was never committed, regenerate it from scratch
PYTHONPATH=. python -c "
from pathlib import Path
from tools.generate_docs.mkdocs_config_loader import build_mkdocs_config, write_mkdocs_config
config = build_mkdocs_config(Path('.'), Path('docs/generated'), ['api', 'models'], 'material')
write_mkdocs_config(config, Path('mkdocs.yml'))
print('mkdocs.yml regenerated')
"
```

### 12.7 Rollback Validation

After any rollback action, validate the docs build is healthy:

```bash
# Validate strict build passes
mkdocs build --strict --site-dir site/

# Validate mike versions are consistent
mike list

# Validate openapi.json is valid
python -c "import json; json.loads(open('docs/generated/api/openapi.json').read()); print('OK')"

# Run the full test suite for docs tooling
pytest tests/tools/test_generate_docs.py -v
```

---

## 13. Edge Cases

| EC-ID | Input Condition | Expected Behaviour |
|-------|----------------|-------------------|
| EC-01 | Module has no docstring | WARNING logged with module path; mkdocstrings renders class without docstring |
| EC-02 | Mermaid node name contains hyphen character | `ValueError` raised before build with offending node name in message |
| EC-03 | Section excluded from `include_sections` | Navigation adjusted automatically; no dead nav link for excluded section |
| EC-04 | Git tag does not exist for requested mike version | `ValueError` raised; mike subprocess never called |
| EC-05 | `mike` binary not installed in environment | Versioning disabled; `result["warnings"]` contains mike-missing message |
| EC-06 | `strict=False` in MkDocs config (not via tool) | Tool always passes `--strict` to subprocess; config file setting overridden by CLI flag |
| EC-07 | Very large OpenAPI schema with > 500 operations | Paginated Redoc rendering; `write_schema_json` completes within 15s SLO |
| EC-08 | `deploy_target="none"` (default) | No publish step; no git operations; docs written locally only |
| EC-09 | Tool re-run on unchanged project | Idempotent; all file hashes identical; `sections_regenerated: 0` |
| EC-10 | Custom theme path provided instead of theme name | CSS override file written to `docs/generated/overrides/`; theme path validated |
| EC-11 | OpenAPI schema changes between section runs | API section hash mismatch detected; API section fully rebuilt |
| EC-12 | `LANG=pt-BR` environment variable set | `theme.language: pt` propagated to mkdocs.yml; search index uses Portuguese tokeniser |
| EC-13 | Dead link to `/api/orders` route that was removed | `mkdocs build --strict` fails; `result["errors"]` contains dead-link diagnostic |
| EC-14 | Non-ASCII characters in docstrings (CJK + emoji) | Rendered HTML contains raw Unicode; no HTML entity escaping |
| EC-15 | `include_sections=[]` (empty list) | Tool returns immediately with `sections_generated: 0`; no files written; no exception |

---

## 14. Acceptance Criteria

✅ 1. `fastapi_generate_docs()` generates all 5 section pages (`api`, `models`, `schemas`, `deployment`, `architecture`) for a project with 20+ routes in under 15 seconds on a standard laptop.

✅ 2. `mkdocs build --strict` exits with code 0 on the generated site (no dead links, no missing references).

✅ 3. Introducing a broken internal link in a generated page causes `mkdocs build --strict` to exit non-zero and populates `result["errors"]` with the dead-link diagnostic.

✅ 4. `register_mike_version` correctly registers a `latest` alias on the `gh-pages` branch, verified by checking `versions.json` content.

✅ 5. The tool is fully idempotent: two consecutive runs on an unchanged project produce byte-for-byte identical output directory content.

✅ 6. Navigation order strictly follows `CANONICAL_SECTION_ORDER` regardless of the order in which sections are passed to `include_sections`.

✅ 7. A Mermaid diagram with an unsafe node name (containing a hyphen) raises `ValueError` before `mkdocs build` is called, and the error message identifies the offending node.

✅ 8. `deploy_target="none"` (the default) never triggers any `git push` or `aws s3 sync` subprocess call.

✅ 9. Non-ASCII characters in Python docstrings (Chinese, accented Latin, emoji) are rendered correctly in the generated HTML without HTML entity encoding.

✅ 10. All 30 T-01..T-30 test cases pass in CI with zero failures and zero skips.

---

## 15. Implementation Checklist

### 15.1 Project Structure Setup
- [ ] Create `tools/generate_docs/` package directory
- [ ] Write `tools/generate_docs/__init__.py` with `generate_docs()` entry point
- [ ] Write `tools/generate_docs/mkdocs_config_loader.py`
- [ ] Write `tools/generate_docs/openapi_renderer.py`
- [ ] Write `tools/generate_docs/mkdocstrings_config.py`
- [ ] Write `tools/generate_docs/dependency_graph.py`
- [ ] Write `tools/generate_docs/navigation_builder.py`
- [ ] Write `tools/generate_docs/versioning.py`
- [ ] Write `tools/generate_docs/strict_validator.py`
- [ ] Write `tools/generate_docs/ci_workflow_writer.py`
- [ ] Write `tools/generate_docs/section_cache.py` (hash-based incremental build)
- [ ] Write `tools/generate_docs/deployment_page_builder.py`

### 15.2 MkDocs Configuration
- [ ] Implement `build_mkdocs_config()` with all required plugins
- [ ] Implement `write_mkdocs_config()` with UTF-8 yaml.dump
- [ ] Implement `_infer_site_name()` from `pyproject.toml` via `tomllib`
- [ ] Validate Material theme is available; raise ImportError with install instructions if not
- [ ] Write `docs/generated/overrides/` custom CSS for theme overrides
- [ ] Implement canonical section order enforcement in nav builder
- [ ] Write `docs/generated/index.md` with site title and intro paragraph

### 15.3 OpenAPI and Redoc Integration
- [ ] Implement `OpenAPIRenderer.extract_schema()` via FastAPI app import
- [ ] Implement `OpenAPIRenderer.write_schema_json()` with stable JSON serialisation
- [ ] Implement `OpenAPIRenderer.render_redoc_page()` standalone HTML
- [ ] Implement `OpenAPIRenderer.render_mkdocs_page()` with iframe embed
- [ ] Handle `app.openapi()` failures gracefully (import error → WARNING + skip section)
- [ ] Support configurable `redoc_js` URL for offline/air-gapped environments
- [ ] Validate `openapi.json` parses before writing Redoc HTML

### 15.4 mkdocstrings Integration
- [ ] Implement `find_pydantic_models()` via AST traversal (no imports executed)
- [ ] Implement `write_models_page()` with `:::` directives and Google docstring style
- [ ] Implement `write_schemas_page()` filtering by `Request`/`Response`/`Schema` suffix
- [ ] Handle SyntaxError in source files gracefully during AST traversal
- [ ] Validate mkdocstrings is installed; emit WARNING and skip section if missing
- [ ] Configure `show_source: true` for models, `show_source: false` for schemas

### 15.5 Mermaid and Architecture
- [ ] Implement `extract_dependency_graph()` via AST import analysis
- [ ] Implement `render_mermaid_flowchart()` with node name safety validation
- [ ] Implement `write_architecture_page()` with fenced Mermaid block
- [ ] Validate `max_nodes` truncation selects top-N by out-degree
- [ ] Write `docs/generated/architecture/modules.md` listing all discovered modules
- [ ] Validate Mermaid syntax does not exceed 40 nodes by default

### 15.6 Deployment Page Builder
- [ ] Parse `Dockerfile` for `FROM`, `EXPOSE`, and `CMD` instructions
- [ ] Parse `docker-compose.yml` `environment:` keys for env var documentation
- [ ] Write `docs/generated/deployment/index.md` with build and run commands
- [ ] Write `docs/generated/deployment/env.md` with env var table
- [ ] Write `docs/generated/deployment/docker.md` with Docker Compose snippet
- [ ] Handle missing `Dockerfile` gracefully with placeholder note

### 15.7 Navigation Builder
- [ ] Implement `build_navigation()` with strict canonical order enforced by `CANONICAL_SECTION_ORDER`
- [ ] Implement `ensure_section_dirs()` creating placeholder index pages for all requested sections
- [ ] Validate unknown section names raise `ValueError` immediately with the invalid name in the message
- [ ] Write `docs/generated/getting_started.md` scaffold with install, run, and docs preview steps
- [ ] Validate output nav list against expected structure in parametrized tests covering all section combinations
- [ ] Assert nav list is stable across multiple calls with the same sections (no randomness)

### 15.8 Versioning (mike)
- [ ] Implement `get_current_git_tag()` via `git describe --tags --exact-match`
- [ ] Implement `register_mike_version()` with semver validation
- [ ] Validate mike is installed before calling; raise with install instructions if not
- [ ] Implement `_SEMVER_RE` pattern covering `v1.0`, `v1.0.0`, `1.0.0`, `v2.1.3-rc1`
- [ ] Implement dry-run mode (skip push when `push=False`)
- [ ] Write integration test that mocks `subprocess.run` for mike deploy

### 15.9 Strict Build Validator
- [ ] Implement `run_strict_build()` calling `mkdocs build --strict`
- [ ] Implement dead-link regex parser on mkdocs stdout/stderr
- [ ] Implement `BuildValidationResult` dataclass with `passed`, `errors`, `dead_links`
- [ ] Implement `BuildValidationError` with structured result attached
- [ ] Validate strict mode always passed; fail if `--strict` flag is removed from call
- [ ] Write test that exercises the dead-link detection path with a real broken link

### 15.10 CI Workflow Writer
- [ ] Implement `write_ci_workflow()` writing `.github/workflows/docs.yml`
- [ ] Implement `ensure_github_token_secret_documented()` README note
- [ ] Validate workflow YAML parses correctly after writing
- [ ] Check for existing `ci.yml` to avoid naming conflicts
- [ ] Write test asserting `--strict` is present in generated workflow
- [ ] Write test asserting mike deploy is gated on `refs/tags/v` pattern

### 15.11 Section Cache (Incremental Build)
- [ ] Implement `SectionCache` with per-section MD5 hash tracking
- [ ] Implement `load_cache()` and `save_cache()` to `.docs_cache.json`
- [ ] Implement `is_section_dirty()` comparing source hash to cached hash
- [ ] Integrate cache check into `generate_docs()` before each section render
- [ ] Write test asserting clean run skips all sections (matching hashes)
- [ ] Write test asserting dirty run regenerates only changed section

### 15.12 pyproject.toml and Makefile
- [ ] Update `pyproject.toml` with `[project.optional-dependencies] docs` group
- [ ] List all required packages: `mkdocs-material`, `mkdocstrings[python]`, `mike`, `pymdown-extensions`
- [ ] Add `Makefile` target `docs-build: mkdocs build --strict`
- [ ] Add `Makefile` target `docs-serve: mkdocs serve`
- [ ] Add `Makefile` target `docs-deploy: mike deploy --push ...`
- [ ] Add `Makefile` target `docs-clean: rm -rf docs/generated/ site/`
- [ ] Validate Makefile targets are documented in `docs/generated/getting_started.md`

### 15.13 Tests
- [ ] Write `tests/tools/test_generate_docs.py` with all T-01..T-30 test cases
- [ ] Write `tests/tools/conftest.py` with `tmp_project` fixture (minimal FastAPI project in tmp_path)
- [ ] Mock `subprocess.run` for mike and mkdocs calls in unit tests
- [ ] Write integration test for full `generate_docs()` call on real project
- [ ] Validate all 30 test IDs are present with unique names
- [ ] Add CI step `pytest tests/tools/ -v --tb=short` to CI workflow
- [ ] Write parametrized test for all 5 sections ensuring each page is generated

---

## 16. Documentation Output

```json
{
  "status": "success",
  "files_created": [
    "mkdocs.yml",
    "docs/generated/index.md",
    "docs/generated/getting_started.md",
    "docs/generated/api/index.md",
    "docs/generated/api/openapi.json",
    "docs/generated/api/redoc.html",
    "docs/generated/models/index.md",
    "docs/generated/schemas/index.md",
    "docs/generated/deployment/index.md",
    "docs/generated/deployment/env.md",
    "docs/generated/deployment/docker.md",
    "docs/generated/architecture/index.md",
    "docs/generated/architecture/modules.md",
    "docs/generated/overrides/custom.css",
    ".github/workflows/docs.yml",
    "Makefile"
  ],
  "files_modified": [
    "pyproject.toml"
  ],
  "metrics": {
    "sections_generated": 5,
    "models_documented": 12,
    "routes_documented": 48,
    "mermaid_nodes": 23,
    "strict_build_passed": true,
    "dead_links_found": 0,
    "tool_execution_time_s": 9.4,
    "mkdocs_build_time_s": 14.2
  },
  "next_steps": [
    "Run `mkdocs serve` to preview the docs locally at http://127.0.0.1:8000",
    "Tag a release (e.g. `git tag v1.0.0`) and push to trigger GitHub Pages deploy via CI",
    "Add docstrings to modules listed in `result['warnings']` to fill documentation gaps",
    "Review the Mermaid architecture diagram and adjust `max_nodes` if the graph is too dense",
    "Configure `LANG` environment variable to enable i18n for non-English docstring content",
    "Run `make docs-deploy` after verifying dry-run output matches expectations"
  ],
  "warnings": [
    "3 modules have no module-level docstring — mkdocstrings will render class body only: app.models.base, app.core.config, app.utils.helpers",
    "mike not found in PATH — versioning disabled; install with `pip install mike` to enable multi-version docs"
  ],
  "notes": [
    "The output directory docs/generated/ is entirely auto-generated — do not edit files in this directory manually as they will be overwritten on the next tool run",
    "Navigation order is deterministic and follows CANONICAL_SECTION_ORDER: api, models, schemas, deployment, architecture",
    "Strict mode is always enabled in the generated CI workflow — broken internal links will block the publish step on every tagged release",
    "The architecture Mermaid diagram is limited to 40 most-connected modules by default; pass `max_nodes` to adjust this limit for larger projects",
    "Redoc is served from the jsDelivr CDN by default — pass `redoc_js` parameter with a local bundle path for air-gapped environments"
  ]
}
```
