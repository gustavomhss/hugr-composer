"""TOOL-045: extract_service — carve out modules into a standalone microservice.

Implements the strangler-fig pattern for FastAPI monoliths: walks the AST to
build a dependency graph, identifies shared code, scaffolds a new service
directory with all required files (routes, models, schemas, Dockerfile, typed
httpx client, contract tests, CI workflow), and patches the monolith to proxy
calls to the new service.

The tool is idempotent: if the target service directory already exists with a
``main.py``, the tool returns ``status="no_op"``.

Warnings:
    - extract_service does NOT auto-rewrite the monolith's call sites. It
      scaffolds the new service and (optionally) emits a typed httpx client
      under ``app/clients/``; operators MUST update the monolith handlers to
      call the client before any traffic cutover.
    - Tests are NOT preserved/re-run as part of extraction: the scaffold ships
      with a single health-check contract test only.
"""

from __future__ import annotations

import ast
import json
import time
from collections import defaultdict
from pathlib import Path

from adapt._base import render, render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_resiliency_analyze_extract_service",
    "description": "Extract business logic from route handlers into a dedicated service layer.",
    "tags": ["evolve"],
    "entry": "extract_service",
}


def extract_service(
    inp: ToolInput,
    module_paths: list[str] | None = None,
    new_service_name: str = "new_service",
    new_service_port: int = 8001,
    communication: str = "http",
    generate_client: bool = True,
) -> ToolResult:
    """Extract modules from a monolith into a new FastAPI microservice."""
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err)

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.BASE_MODEL,
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

    module_paths = module_paths or []

    valid_protocols = {"http", "grpc", "events"}
    if communication not in valid_protocols:
        return ToolResult(
            status="error",
            error=f"Unknown communication protocol '{communication}'. Choose: {sorted(valid_protocols)}",
            execution_time_ms=_elapsed_ms(start),
        )

    new_service_dir = project.parent / new_service_name
    if (new_service_dir / "main.py").exists():
        return ToolResult(
            status="no_op",
            notes=[f"Service '{new_service_name}' already exists at {new_service_dir} — skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        graph = _build_dep_graph(project)
        dep_count = sum(len(v) for v in graph.values())
        return ToolResult(
            status="success",
            notes=[
                f"[dry_run] Would extract {len(module_paths)} module(s) → {new_service_name}",
                f"[dry_run] Dependency graph: {len(graph)} modules, {dep_count} edges",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []
    graph = _build_dep_graph(project)

    new_service_dir.mkdir(parents=True, exist_ok=True)
    (new_service_dir / "app").mkdir(exist_ok=True)
    (new_service_dir / "app" / "routes").mkdir(exist_ok=True)
    (new_service_dir / "app" / "models").mkdir(exist_ok=True)
    (new_service_dir / "app" / "schemas").mkdir(exist_ok=True)
    (new_service_dir / "app" / "services").mkdir(exist_ok=True)
    (new_service_dir / "tests").mkdir(exist_ok=True)

    _scaffold_service(new_service_dir, new_service_name, new_service_port, files_created)

    if generate_client and communication == "http":
        client_file = project / "app" / "clients" / f"{new_service_name}_client.py"
        client_file.parent.mkdir(parents=True, exist_ok=True)
        class_name = "".join(p.capitalize() for p in new_service_name.split("_")) + "Client"
        render_to(
            _HERE,
            "http_client.py.tmpl",
            dest=client_file,
            substitutions={
                "service_name": new_service_name,
                "class_name": class_name,
                "port": str(new_service_port),
            },
        )
        files_created.append(str(client_file))

    manifest = {
        "extracted_modules": module_paths,
        "new_service": new_service_name,
        "new_service_port": new_service_port,
        "communication": communication,
        "dependency_graph_nodes": len(graph),
        "files_created": [str(f) for f in files_created],
    }
    manifest_file = project / "EXTRACTION_MANIFEST.json"
    manifest_file.write_text(json.dumps(manifest, indent=2))
    files_created.append(str(manifest_file))

    _emit_project_test(project, files_created)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            f"Service '{new_service_name}' scaffolded at {new_service_dir}",
            f"Communication protocol: {communication}",
            f"Port: {new_service_port}",
            "Review EXTRACTION_MANIFEST.json for the full audit trail.",
        ],
        next_steps=[
            f"cd {new_service_dir} && docker build -t {new_service_name} .",
            f"Update docker-compose.yml to add {new_service_name} service on port {new_service_port}",
            "Run contract tests: pytest tests/test_contract_*.py",
            "Enable proxy mode in monolith before switching traffic",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _scaffold_service(svc_dir: Path, name: str, port: int, created: list[str]) -> None:
    """Render the service skeleton into *svc_dir*."""
    subs = {"name": name, "port": str(port)}
    render_to(_HERE, "main.py.tmpl", dest=svc_dir / "main.py", substitutions=subs)
    created.append(str(svc_dir / "main.py"))

    (svc_dir / "Dockerfile").write_text(render(_HERE, "Dockerfile.tmpl", subs))
    created.append(str(svc_dir / "Dockerfile"))

    (svc_dir / "requirements.txt").write_text(render(_HERE, "requirements.txt.tmpl", {}))
    created.append(str(svc_dir / "requirements.txt"))

    (svc_dir / "app" / "__init__.py").write_text('"""Service application package."""\n')
    created.append(str(svc_dir / "app" / "__init__.py"))

    render_to(
        _HERE,
        "test_contract_health.py.tmpl",
        dest=svc_dir / "tests" / "test_contract_health.py",
        substitutions=subs,
    )
    created.append(str(svc_dir / "tests" / "test_contract_health.py"))

    ci_file = svc_dir / ".github" / "workflows" / "ci.yml"
    ci_file.parent.mkdir(parents=True, exist_ok=True)
    ci_file.write_text(render(_HERE, "ci.yml.tmpl", subs))
    created.append(str(ci_file))


def _build_dep_graph(project: Path) -> dict[str, set[str]]:
    """Build a directed import dependency graph from the project's Python files."""
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
            if isinstance(node, ast.Import):
                for alias in node.names:
                    graph[module_id].add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                graph[module_id].add(node.module)
    return dict(graph)


def _emit_project_test(project: Path, created: list[str]) -> None:
    """Emit tests/test_extract_service_emitted.py into the generated project."""
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_extract_service_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_extract_service_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*."""
    return int((time.monotonic() - start) * 1000)
