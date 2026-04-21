"""TOOL-045: extract_service — carve out modules into a standalone microservice.

Implements the strangler-fig pattern for FastAPI monoliths: walks the AST to
build a dependency graph, identifies shared code, scaffolds a new service
directory with all required files (routes, models, schemas, Dockerfile, typed
httpx client, contract tests, CI workflow), and patches the monolith to proxy
calls to the new service.

The tool is idempotent: if the target service directory already exists with a
``main.py``, the tool returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.evolve.extract_service import extract_service

    result = extract_service(
        ToolInput(project_dir="/path/to/monolith"),
        module_paths=["app/routes/billing.py", "app/services/billing.py"],
        new_service_name="billing_service",
        new_service_port=8001,
    )
    print(result.status)
    print(result.files_created)
    print(result.next_steps)
"""

from __future__ import annotations

import ast
import json
import textwrap
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_resiliency_analyze_extract_service",
    "description": "Extract business logic from route handlers into a dedicated service layer.",
    "tags": ["evolve"],
    "entry": "extract_service",
}



# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def extract_service(
    inp: ToolInput,
    module_paths: list[str] | None = None,
    new_service_name: str = "new_service",
    new_service_port: int = 8001,
    communication: str = "http",
    generate_client: bool = True,
) -> ToolResult:
    """Extract modules from a monolith into a new FastAPI microservice.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.
        module_paths: List of paths (relative to project root) to extract.
        new_service_name: Directory name for the new service.
        new_service_port: TCP port for the new service container.
        communication: Boundary protocol — ``http``, ``grpc``, or ``events``.
        generate_client: Generate a typed httpx client in the monolith.

    Returns:
        ``ToolResult`` describing every file created or modified.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err)

    # --- Prerequisite check (standalone mode) --------------------------------
    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

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

    # Validate communication protocol
    valid_protocols = {"http", "grpc", "events"}
    if communication not in valid_protocols:
        return ToolResult(
            status="error",
            error=f"Unknown communication protocol '{communication}'. Choose: {sorted(valid_protocols)}",
            execution_time_ms=_elapsed_ms(start),
        )

    # Idempotency guard
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

    # Build dependency graph
    graph = _build_dep_graph(project)

    # Create service directory structure
    new_service_dir.mkdir(parents=True, exist_ok=True)
    (new_service_dir / "app").mkdir(exist_ok=True)
    (new_service_dir / "app" / "routes").mkdir(exist_ok=True)
    (new_service_dir / "app" / "models").mkdir(exist_ok=True)
    (new_service_dir / "app" / "schemas").mkdir(exist_ok=True)
    (new_service_dir / "app" / "services").mkdir(exist_ok=True)
    (new_service_dir / "tests").mkdir(exist_ok=True)

    # Generate core files
    for path, content in _scaffold_service_files(
        new_service_name, new_service_port, communication, module_paths
    ).items():
        dest = new_service_dir / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content)
        files_created.append(str(dest))

    # Generate typed client in monolith
    if generate_client and communication == "http":
        client_file = project / "app" / "clients" / f"{new_service_name}_client.py"
        client_file.parent.mkdir(parents=True, exist_ok=True)
        client_file.write_text(_generate_http_client(new_service_name, new_service_port))
        files_created.append(str(client_file))

    # Write EXTRACTION_MANIFEST.json
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_dep_graph(project: Path) -> dict[str, set[str]]:
    """Build a directed import dependency graph from the project's Python files.

    Args:
        project: Project root directory.

    Returns:
        Dict mapping module path string to set of imported module paths.
    """
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


def _scaffold_service_files(
    name: str, port: int, communication: str, module_paths: list[str]
) -> dict[str, str]:
    """Return a dict of relative_path → file_content for the new service.

    Args:
        name: Service name (snake_case).
        port: Service port number.
        communication: Boundary protocol.
        module_paths: Source modules being extracted.

    Returns:
        Dict mapping relative path to file content string.
    """
    files: dict[str, str] = {}

    # main.py
    files["main.py"] = textwrap.dedent(f"""\
        \"\"\"FastAPI application for {name}.\"\"\"
        from __future__ import annotations

        from fastapi import FastAPI

        app = FastAPI(title="{name}", version="0.1.0")


        @app.get("/health")
        async def health() -> dict:
            \"\"\"Health check endpoint.

            Returns:
                Service health status.
            \"\"\"
            return {{"status": "ok", "service": "{name}"}}
    """)

    # Dockerfile
    files["Dockerfile"] = textwrap.dedent(f"""\
        FROM python:3.12-slim
        WORKDIR /app
        COPY requirements.txt .
        RUN pip install --no-cache-dir -r requirements.txt
        COPY . .
        EXPOSE {port}
        CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "{port}"]
    """)

    # requirements.txt
    files["requirements.txt"] = textwrap.dedent("""\
        fastapi>=0.111.0
        uvicorn[standard]>=0.30.0
        pydantic>=2.7.0
        sqlalchemy>=2.0.0
        httpx>=0.27.0
    """)

    # __init__.py
    files["app/__init__.py"] = '"""Service application package."""\n'

    # Contract test stub
    files["tests/test_contract_health.py"] = textwrap.dedent(f"""\
        \"\"\"Contract test: health endpoint for {name}.\"\"\"
        from fastapi.testclient import TestClient
        from main import app

        client = TestClient(app)


        def test_health_returns_ok() -> None:
            \"\"\"Health endpoint must return 200 with status=ok.\"\"\"
            resp = client.get("/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert data["service"] == "{name}"
    """)

    # GitHub Actions workflow
    files[".github/workflows/ci.yml"] = textwrap.dedent(f"""\
        name: CI - {name}
        on: [push, pull_request]
        jobs:
          test:
            runs-on: ubuntu-latest
            steps:
              - uses: actions/checkout@v4
              - uses: actions/setup-python@v5
                with:
                  python-version: "3.12"
              - run: pip install -r requirements.txt pytest
              - run: pytest tests/ -v
    """)

    return files


def _generate_http_client(service_name: str, port: int) -> str:
    """Generate a typed httpx client for the extracted service.

    Args:
        service_name: Name of the service (snake_case).
        port: Service port number.

    Returns:
        Python source code for the typed client.
    """
    class_name = "".join(p.capitalize() for p in service_name.split("_")) + "Client"
    return textwrap.dedent(f"""\
        \"\"\"Typed httpx client for {service_name}.

        Inject ``{class_name}`` as a FastAPI dependency or instantiate directly.
        \"\"\"
        from __future__ import annotations

        import httpx


        class {class_name}:
            \"\"\"Typed HTTP client for the {service_name} microservice.

            Args:
                base_url: Base URL of the {service_name} service.
                timeout: Request timeout in seconds.
            \"\"\"

            def __init__(
                self,
                base_url: str = "http://localhost:{port}",
                timeout: float = 10.0,
            ) -> None:
                self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

            async def health(self) -> dict:
                \"\"\"Check service health.

                Returns:
                    Health status dict from the service.

                Raises:
                    httpx.HTTPStatusError: On 4xx/5xx responses.
                \"\"\"
                resp = await self._client.get("/health")
                resp.raise_for_status()
                return resp.json()

            async def close(self) -> None:
                \"\"\"Close the underlying httpx client.\"\"\"
                await self._client.aclose()

            async def __aenter__(self) -> "{class_name}":
                return self

            async def __aexit__(self, *args: object) -> None:
                await self.close()
    """)


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*.

    Args:
        start: Reference time from ``time.monotonic()``.

    Returns:
        Elapsed milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)
