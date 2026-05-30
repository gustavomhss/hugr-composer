"""TOOL-049: generate_docs — MkDocs Material documentation scaffold for FastAPI.

Generates a deterministic MkDocs Material site with API reference (Redoc),
model/schema docs (mkdocstrings), architecture diagram (Mermaid), versioning
(mike), strict mode, and a CI deploy workflow.

The tool is idempotent: if ``mkdocs.yml`` already exists and contains the
``material`` theme fingerprint, returns ``status="no_op"``.

Warnings:
    - generate_docs does NOT guarantee complete coverage. Only docstring-
      annotated symbols are picked up by mkdocstrings; unannotated routes
      and models are coverage gaps, NOT silently documented.
    - Strict mode (``mkdocs build --strict``) is enabled — dead-link
      detection fails the build, so cross-references must remain valid.
    - The architecture diagram is capped at 20 nodes / 5 edges per node to
      keep the Mermaid rendering readable; the full import graph is NOT
      reproduced.
"""

from __future__ import annotations

import ast
import time
from collections import defaultdict
from pathlib import Path

from adapt._base import render, render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

_HERE = Path(__file__).parent

_CANONICAL_SECTIONS = ["api", "models", "schemas", "deployment", "architecture"]
_VALID_DEPLOY_TARGETS = frozenset({"none", "github_pages", "s3", "netlify"})

_SECTION_TITLES = {
    "api": "API Reference",
    "models": "Models",
    "schemas": "Schemas",
    "deployment": "Deployment",
    "architecture": "Architecture",
}


MCP_TOOL = {
    "name": "fastapi_resiliency_generate_docs",
    "description": "Generate developer documentation from the project's code and OpenAPI spec.",
    "tags": ["evolve"],
    "entry": "generate_docs",
}


def generate_docs(
    inp: ToolInput,
    output_dir: str = "docs/generated",
    include_sections: list[str] | None = None,
    deploy_target: str = "none",
    theme: str = "material",
) -> ToolResult:
    """Scaffold a MkDocs Material documentation site for the project."""
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err)

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.CONFIG_SETTINGS,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=[
                "These prerequisites cannot be auto-created.",
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    if scaffolded:
        files_created.extend(scaffolded)

    if deploy_target not in _VALID_DEPLOY_TARGETS:
        return ToolResult(
            status="error",
            error=f"Unknown deploy_target '{deploy_target}'. Choose: {sorted(_VALID_DEPLOY_TARGETS)}",
            execution_time_ms=_elapsed_ms(start),
        )

    mkdocs_yml = project / "mkdocs.yml"
    if mkdocs_yml.exists() and "material" in mkdocs_yml.read_text():
        return ToolResult(
            status="no_op",
            notes=["mkdocs.yml with Material theme already present — skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if include_sections is None:
        sections = _CANONICAL_SECTIONS[:]
    else:
        sections = [s for s in _CANONICAL_SECTIONS if s in include_sections]

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                f"[dry_run] sections={sections} deploy_target={deploy_target}",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to generate docs."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    docs_src = project / output_dir
    docs_src.mkdir(parents=True, exist_ok=True)

    site_name = _detect_project_name(project)
    nav_entries = "\n".join(f"  - {s.capitalize()}: {s}.md" for s in sections)
    mkdocs_yml.write_text(
        render(
            _HERE,
            "mkdocs.yml.tmpl",
            {
                "site_name": site_name,
                "output_dir": output_dir,
                "theme": theme,
                "nav_entries": nav_entries,
            },
        )
    )
    files_created.append(str(mkdocs_yml))

    index_file = docs_src / "index.md"
    index_file.write_text(
        render(
            _HERE,
            "index.md.tmpl",
            {"site_name": site_name, "pkg_slug": site_name.lower().replace(" ", "-")},
        )
    )
    files_created.append(str(index_file))

    for section in sections:
        section_file = docs_src / f"{section}.md"
        section_file.write_text(_render_section(section))
        files_created.append(str(section_file))

    if "architecture" in sections:
        diagram_file = docs_src / "architecture_diagram.md"
        dep_graph = _build_dep_graph(project)
        diagram_file.write_text(
            render(
                _HERE,
                "architecture_diagram.md.tmpl",
                {"diagram": _format_diagram(dep_graph)},
            )
        )
        files_created.append(str(diagram_file))

    if "api" in sections:
        redoc_file = docs_src / "api_reference.html"
        redoc_file.write_text(render(_HERE, "redoc_embed.html.tmpl", {"site_name": site_name}))
        files_created.append(str(redoc_file))

    ci_file = _write_ci_workflow(project, deploy_target, output_dir)
    files_created.append(str(ci_file))

    publish_script = project / "scripts" / "publish_docs.sh"
    publish_script.parent.mkdir(exist_ok=True)
    publish_script.write_text(_render_publish_script(deploy_target))
    files_created.append(str(publish_script))

    pyproject = project / "pyproject.toml"
    if pyproject.exists() and _patch_pyproject(pyproject):
        files_modified.append(str(pyproject))

    makefile = project / "Makefile"
    if makefile.exists() and _patch_makefile(makefile):
        files_modified.append(str(makefile))

    _emit_project_test(project, files_created)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            f"MkDocs Material docs scaffolded at {output_dir}/",
            f"Sections: {', '.join(sections)}",
            f"Deploy target: {deploy_target}",
            "Strict mode enabled: dead links = hard failure.",
        ],
        next_steps=[
            "pip install mkdocs-material mkdocstrings[python] mike",
            "mkdocs serve  # preview locally at http://localhost:8000",
            "mkdocs build --strict  # validate (fails on dead links)",
            f"bash scripts/publish_docs.sh  # deploy to {deploy_target}",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _detect_project_name(project: Path) -> str:
    """Detect the project/app name from pyproject.toml or directory name."""
    pyproject = project / "pyproject.toml"
    if pyproject.exists():
        for line in pyproject.read_text().splitlines():
            if line.startswith("name"):
                parts = line.split("=", 1)
                if len(parts) == 2:
                    return parts[1].strip().strip("\"'")
    return project.name.replace("_", " ").title()


def _render_section(section: str) -> str:
    """Render a section page (markdown)."""
    title = _SECTION_TITLES.get(section, section.capitalize())
    if section == "api":
        return f"# {title}\n\nSee [interactive API reference](api_reference.html).\n"
    tmpl_map = {
        "models": "section_models.md.tmpl",
        "schemas": "section_schemas.md.tmpl",
        "deployment": "section_deployment.md.tmpl",
        "architecture": "section_architecture.md.tmpl",
    }
    if section in tmpl_map:
        return render(_HERE, tmpl_map[section], {"title": title})
    return f"# {title}\n\nTODO: add content for {section}.\n"


def _format_diagram(dep_graph: dict[str, set[str]]) -> str:
    """Format the Mermaid edge list (capped at 20 nodes / 5 edges per node)."""
    filtered = {
        k: v
        for k, v in dep_graph.items()
        if k.startswith("app/") and any(d.startswith("app") for d in v)
    }
    edges: list[str] = []
    for module, deps in list(filtered.items())[:20]:
        short_m = module.replace("app/", "").replace("/", ".").removesuffix(".py")
        for dep in list(deps)[:5]:
            if dep.startswith("app"):
                short_d = dep.replace("app.", "").replace("/", ".")
                edges.append(f"    {short_m} --> {short_d}")
    return "\n".join(edges) if edges else "    app --> models\n    app --> schemas"


def _write_ci_workflow(project: Path, deploy_target: str, output_dir: str) -> Path:
    """Write the GitHub Actions docs CI workflow."""
    ci_dir = project / ".github" / "workflows"
    ci_dir.mkdir(parents=True, exist_ok=True)
    workflow_file = ci_dir / "docs.yml"

    deploy_step = ""
    if deploy_target == "github_pages":
        # Preserve original behaviour: f-string `{{ ... }}` rendered as `{ ... }`,
        # so the actual emitted text is `${ github.ref_name }` (single braces).
        deploy_step = (
            "      - name: Deploy to GitHub Pages\n"
            "        run: mike deploy --push --update-aliases ${ github.ref_name } latest\n"
            "        env:\n"
            "          GIT_COMMITTER_NAME: github-actions\n"
            "          GIT_COMMITTER_EMAIL: actions@github.com\n"
        )

    workflow_file.write_text(
        render(
            _HERE,
            "ci_docs.yml.tmpl",
            {"output_dir": output_dir, "deploy_step": deploy_step},
        )
    )
    return workflow_file


def _render_publish_script(deploy_target: str) -> str:
    """Render the publish script for the chosen deploy target."""
    if deploy_target == "github_pages":
        return render(_HERE, "publish_pages.sh.tmpl", {})
    return render(_HERE, "publish_generic.sh.tmpl", {"deploy_target": deploy_target})


def _patch_pyproject(pyproject: Path) -> bool:
    """Append mkdocs dependency note to pyproject.toml if missing."""
    src = pyproject.read_text()
    if "mkdocs-material" in src:
        return False
    note = "\n# Docs deps (add to [project.optional-dependencies]):\n# mkdocs-material>=9.5\n# mkdocstrings[python]>=0.25\n# mike>=2.1\n"
    pyproject.write_text(src.rstrip() + note)
    return True


def _patch_makefile(makefile: Path) -> bool:
    """Append docs Makefile targets if missing."""
    src = makefile.read_text()
    if "docs-serve" in src:
        return False
    targets = (
        "\n## Documentation\n"
        ".PHONY: docs-serve docs-build docs-publish\n"
        "docs-serve:\n"
        "\tmkdocs serve\n\n"
        "docs-build:\n"
        "\tmkdocs build --strict\n\n"
        "docs-publish:\n"
        "\tbash scripts/publish_docs.sh\n"
    )
    makefile.write_text(src + targets)
    return True


def _build_dep_graph(project: Path) -> dict[str, set[str]]:
    """Build a lightweight import dependency graph for diagram generation."""
    graph: dict[str, set[str]] = defaultdict(set)
    for py_file in sorted(project.rglob("*.py")):
        if ".venv" in py_file.parts or "__pycache__" in py_file.parts:
            continue
        module_id = str(py_file.relative_to(project))
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                graph[module_id].add(node.module)
    return dict(graph)


def _emit_project_test(project: Path, created: list[str]) -> None:
    """Emit tests/test_generate_docs_emitted.py into the generated project."""
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_generate_docs_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_generate_docs_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*."""
    return int((time.monotonic() - start) * 1000)
