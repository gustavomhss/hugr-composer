"""TOOL-049: generate_docs — MkDocs Material documentation scaffold for FastAPI.

Generates a deterministic, versioned MkDocs Material site with:
- API reference rendered via Redoc embed
- Model/schema docs via mkdocstrings
- Architecture diagrams (Mermaid) from import dependency graph
- Versioning via ``mike``
- Strict mode (dead-link detection)
- CI deploy workflow

The tool is idempotent: if ``mkdocs.yml`` already exists and contains the
``material`` theme fingerprint, returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.evolve.generate_docs import generate_docs

    result = generate_docs(
        ToolInput(project_dir="/path/to/project"),
        include_sections=["api", "models", "architecture"],
        deploy_target="github_pages",
    )
    print(result.status)
    print(result.files_created)
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir

_CANONICAL_SECTIONS = ["api", "models", "schemas", "deployment", "architecture"]
_VALID_DEPLOY_TARGETS = frozenset({"none", "github_pages", "s3", "netlify"})


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def generate_docs(
    inp: ToolInput,
    output_dir: str = "docs/generated",
    include_sections: list[str] | None = None,
    deploy_target: str = "none",
    theme: str = "material",
) -> ToolResult:
    """Scaffold a MkDocs Material documentation site for the project.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.
        output_dir: Destination for generated docs source (relative to project).
        include_sections: Subset of ``api``, ``models``, ``schemas``,
            ``deployment``, ``architecture``. ``None`` = all sections.
        deploy_target: ``none``, ``github_pages``, ``s3``, or ``netlify``.
        theme: MkDocs theme name (default ``material``).

    Returns:
        ``ToolResult`` describing every file created or modified.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err)


    if deploy_target not in _VALID_DEPLOY_TARGETS:
        return ToolResult(
            status="error",
            error=f"Unknown deploy_target '{deploy_target}'. Choose: {sorted(_VALID_DEPLOY_TARGETS)}",
            execution_time_ms=_elapsed_ms(start),
        )

    # Idempotency guard
    mkdocs_yml = project / "mkdocs.yml"
    if mkdocs_yml.exists() and "material" in mkdocs_yml.read_text():
        return ToolResult(
            status="no_op",
            notes=["mkdocs.yml with Material theme already present — skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    # Resolve sections in canonical order
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

    files_created: list[str] = []
    files_modified: list[str] = []

    docs_src = project / output_dir
    docs_src.mkdir(parents=True, exist_ok=True)

    # Step 1: mkdocs.yml
    site_name = _detect_project_name(project)
    mkdocs_yml.write_text(_mkdocs_config(site_name, output_dir, sections, theme, deploy_target))
    files_created.append(str(mkdocs_yml))

    # Step 2: index page
    index_file = docs_src / "index.md"
    index_file.write_text(_index_page(site_name))
    files_created.append(str(index_file))

    # Step 3: Section pages
    for section in sections:
        section_file = docs_src / f"{section}.md"
        section_file.write_text(_section_page(section, project))
        files_created.append(str(section_file))

    # Step 4: Mermaid diagram (architecture section)
    if "architecture" in sections:
        diagram_file = docs_src / "architecture_diagram.md"
        dep_graph = _build_dep_graph(project)
        diagram_file.write_text(_mermaid_diagram_page(dep_graph))
        files_created.append(str(diagram_file))

    # Step 5: Redoc embed (api section)
    if "api" in sections:
        redoc_file = docs_src / "api_reference.html"
        redoc_file.write_text(_redoc_embed(site_name))
        files_created.append(str(redoc_file))

    # Step 6: CI workflow
    ci_file = _write_ci_workflow(project, deploy_target, output_dir)
    files_created.append(str(ci_file))

    # Step 7: Publish script
    publish_script = project / "scripts" / "publish_docs.sh"
    publish_script.parent.mkdir(exist_ok=True)
    publish_script.write_text(_publish_script(deploy_target))
    files_created.append(str(publish_script))

    # Step 8: pyproject.toml — add mkdocs dependencies (note only)
    pyproject = project / "pyproject.toml"
    if pyproject.exists():
        _patch_pyproject(pyproject)
        files_modified.append(str(pyproject))

    # Step 9: Makefile targets
    makefile = project / "Makefile"
    if makefile.exists():
        _patch_makefile(makefile)
        files_modified.append(str(makefile))

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


# ---------------------------------------------------------------------------
# Content generators
# ---------------------------------------------------------------------------


def _detect_project_name(project: Path) -> str:
    """Detect the project/app name from pyproject.toml or directory name.

    Args:
        project: Project root directory.

    Returns:
        Human-readable project name string.
    """
    pyproject = project / "pyproject.toml"
    if pyproject.exists():
        for line in pyproject.read_text().splitlines():
            if line.startswith("name"):
                parts = line.split("=", 1)
                if len(parts) == 2:
                    return parts[1].strip().strip('"\'')
    return project.name.replace("_", " ").title()


def _mkdocs_config(
    site_name: str,
    output_dir: str,
    sections: list[str],
    theme: str,
    deploy_target: str,
) -> str:
    """Return mkdocs.yml content.

    Args:
        site_name: Project/site name.
        output_dir: Docs source directory (relative to project).
        sections: Ordered list of included sections.
        theme: MkDocs theme name.
        deploy_target: Deploy target identifier.

    Returns:
        YAML string for mkdocs.yml.
    """
    nav_entries = "\n".join(
        f"  - {s.capitalize()}: {s}.md" for s in sections
    )
    return textwrap.dedent(f"""\
        site_name: {site_name}
        docs_dir: {output_dir}
        strict: true

        theme:
          name: {theme}
          features:
            - navigation.tabs
            - navigation.top
            - search.highlight
            - content.code.copy

        plugins:
          - search
          - mkdocstrings:
              handlers:
                python:
                  options:
                    show_source: true
                    show_root_heading: true

        markdown_extensions:
          - admonition
          - pymdownx.superfences:
              custom_fences:
                - name: mermaid
                  class: mermaid
                  format: !!python/name:pymdownx.superfences.fence_code_format
          - pymdownx.highlight

        nav:
          - Home: index.md
        {nav_entries}

        # Versioning via mike
        # extra:
        #   version:
        #     provider: mike
    """)


def _index_page(site_name: str) -> str:
    """Return content for docs/index.md.

    Args:
        site_name: Project name.

    Returns:
        Markdown string.
    """
    return textwrap.dedent(f"""\
        # {site_name}

        Welcome to the {site_name} documentation.

        ## Quick Start

        ```bash
        pip install {site_name.lower().replace(" ", "-")}
        uvicorn app.main:app --reload
        ```

        ## Sections

        - **API** — Interactive API reference (Redoc)
        - **Models** — SQLAlchemy model documentation
        - **Schemas** — Pydantic schema reference
        - **Deployment** — Docker and CI/CD guides
        - **Architecture** — Dependency diagrams

        ---

        *Generated by generate_docs tool. Run `mkdocs build --strict` to validate.*
    """)


def _section_page(section: str, project: Path) -> str:
    """Return content for a documentation section page.

    Args:
        section: Section identifier string.
        project: Project root directory.

    Returns:
        Markdown string.
    """
    titles = {
        "api": "API Reference",
        "models": "Models",
        "schemas": "Schemas",
        "deployment": "Deployment",
        "architecture": "Architecture",
    }
    title = titles.get(section, section.capitalize())

    if section == "api":
        return f"# {title}\n\nSee [interactive API reference](api_reference.html).\n"
    if section == "models":
        return textwrap.dedent(f"""\
            # {title}

            ::: app.models
                options:
                  members: true
                  show_source: false
        """)
    if section == "schemas":
        return textwrap.dedent(f"""\
            # {title}

            ::: app.schemas
                options:
                  members: true
                  show_source: false
        """)
    if section == "deployment":
        return textwrap.dedent(f"""\
            # {title}

            ## Docker

            ```bash
            docker compose up --build
            ```

            ## Environment Variables

            | Variable | Description | Default |
            |----------|-------------|---------|
            | `DATABASE_URL` | PostgreSQL connection string | required |
            | `SECRET_KEY` | JWT signing key | required |
        """)
    if section == "architecture":
        return textwrap.dedent(f"""\
            # {title}

            See [architecture diagram](architecture_diagram.md) for the
            module-level import dependency graph.
        """)
    return f"# {title}\n\nTODO: add content for {section}.\n"


def _mermaid_diagram_page(dep_graph: dict[str, set[str]]) -> str:
    """Return a Mermaid diagram page from the dependency graph.

    Args:
        dep_graph: Module path → set of imported module paths.

    Returns:
        Markdown string with embedded Mermaid flowchart.
    """
    # Limit to app/ modules to keep the diagram readable
    filtered = {
        k: v
        for k, v in dep_graph.items()
        if k.startswith("app/") and any(d.startswith("app") for d in v)
    }
    edges: list[str] = []
    for module, deps in list(filtered.items())[:20]:  # cap at 20 nodes
        short_m = module.replace("app/", "").replace("/", ".").removesuffix(".py")
        for dep in list(deps)[:5]:
            if dep.startswith("app"):
                short_d = dep.replace("app.", "").replace("/", ".")
                edges.append(f"    {short_m} --> {short_d}")
    diagram = "\n".join(edges) if edges else "    app --> models\n    app --> schemas"
    return textwrap.dedent(f"""\
        # Architecture Diagram

        Module-level import dependency graph (auto-generated).

        ```mermaid
        flowchart TD
        {diagram}
        ```

        *Regenerate by running `generate_docs` after code changes.*
    """)


def _redoc_embed(site_name: str) -> str:
    """Return an HTML page embedding the Redoc API explorer.

    Args:
        site_name: Project/API name.

    Returns:
        HTML string.
    """
    return textwrap.dedent(f"""\
        <!DOCTYPE html>
        <html>
        <head>
          <title>{site_name} API Reference</title>
          <meta charset="utf-8"/>
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <link href="https://fonts.googleapis.com/css?family=Montserrat:300,400,700|Roboto:300,400,700" rel="stylesheet">
          <style>body {{ margin: 0; padding: 0; }}</style>
        </head>
        <body>
          <redoc spec-url="../openapi.json"></redoc>
          <script src="https://cdn.redoc.ly/redoc/latest/bundles/redoc.standalone.js"></script>
        </body>
        </html>
    """)


def _write_ci_workflow(project: Path, deploy_target: str, output_dir: str) -> Path:
    """Write the GitHub Actions docs CI workflow.

    Args:
        project: Project root directory.
        deploy_target: Deploy target identifier.
        output_dir: Docs source directory.

    Returns:
        Path to the created workflow file.
    """
    ci_dir = project / ".github" / "workflows"
    ci_dir.mkdir(parents=True, exist_ok=True)
    workflow_file = ci_dir / "docs.yml"

    deploy_step = ""
    if deploy_target == "github_pages":
        deploy_step = textwrap.dedent("""\
              - name: Deploy to GitHub Pages
                run: mike deploy --push --update-aliases ${{ github.ref_name }} latest
                env:
                  GIT_COMMITTER_NAME: github-actions
                  GIT_COMMITTER_EMAIL: actions@github.com
        """)

    content = textwrap.dedent(f"""\
        name: Documentation
        on:
          push:
            branches: [main]
          pull_request:
            paths:
              - "{output_dir}/**"
              - "app/**/*.py"
              - "mkdocs.yml"
        jobs:
          docs:
            runs-on: ubuntu-latest
            steps:
              - uses: actions/checkout@v4
                with:
                  fetch-depth: 0
              - uses: actions/setup-python@v5
                with:
                  python-version: "3.12"
              - run: pip install mkdocs-material mkdocstrings[python] mike
              - name: Build docs (strict)
                run: mkdocs build --strict
        {deploy_step}
    """)
    workflow_file.write_text(content)
    return workflow_file


def _publish_script(deploy_target: str) -> str:
    """Return content for scripts/publish_docs.sh.

    Args:
        deploy_target: Deploy target identifier.

    Returns:
        Shell script string.
    """
    if deploy_target == "github_pages":
        return textwrap.dedent("""\
            #!/usr/bin/env bash
            set -euo pipefail
            VERSION=$(python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])" 2>/dev/null || echo "latest")
            mike deploy --push --update-aliases "$VERSION" latest
            echo "Docs published: $VERSION"
        """)
    return textwrap.dedent(f"""\
        #!/usr/bin/env bash
        set -euo pipefail
        mkdocs build --strict
        echo "Docs built. Deploy target: {deploy_target}"
        echo "CUSTOMIZE: add your deploy command here."
    """)


def _patch_pyproject(pyproject: Path) -> None:
    """Add mkdocs dependencies comment to pyproject.toml.

    Args:
        pyproject: Path to pyproject.toml.
    """
    src = pyproject.read_text()
    if "mkdocs-material" in src:
        return
    note = "\n# Docs deps (add to [project.optional-dependencies]):\n# mkdocs-material>=9.5\n# mkdocstrings[python]>=0.25\n# mike>=2.1\n"
    pyproject.write_text(src.rstrip() + note)


def _patch_makefile(makefile: Path) -> None:
    """Append docs Makefile targets.

    Args:
        makefile: Path to the project Makefile.
    """
    src = makefile.read_text()
    if "docs-serve" in src:
        return
    targets = textwrap.dedent("""\

        ## Documentation
        .PHONY: docs-serve docs-build docs-publish
        docs-serve:
        \tmkdocs serve

        docs-build:
        \tmkdocs build --strict

        docs-publish:
        \tbash scripts/publish_docs.sh
    """)
    makefile.write_text(src + targets)


def _build_dep_graph(project: Path) -> dict[str, set[str]]:
    """Build a lightweight import dependency graph for diagram generation.

    Args:
        project: Project root directory.

    Returns:
        Dict mapping module file path → set of imported module strings.
    """
    from collections import defaultdict

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


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*.

    Args:
        start: Reference time from ``time.monotonic()``.

    Returns:
        Elapsed milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)
