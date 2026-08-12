"""TOOL-047: generate_sdk — multi-language SDK generation from OpenAPI schema.

Extracts the OpenAPI schema from a FastAPI app, invokes the best-in-class
generator for each target language, and produces typed client packages.

The tool is idempotent: if the ``sdks/<language>/`` directory already
contains a ``.schema_hash`` matching the current schema, that language is
skipped.

Warnings:
    - generate_sdk is NOT a source-of-truth claim. The emitted SDK is a
      snapshot of the OpenAPI schema at generation time; any hand-edit, or
      any drift between the live ``app.openapi()`` and the captured
      ``sdks/openapi.json``, is silently retained until the next regen. The
      CI workflow watches the schema hash to surface drift.
    - When the language-native generator is not installed, the tool writes
      a fallback STUB only (not a real typed client); a warning is recorded.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from adapt._base import render, render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

_HERE = Path(__file__).parent

_VALID_LANGUAGES = frozenset({"python", "typescript", "go", "rust", "java"})

_GENERATORS: dict[str, str] = {
    "python": "openapi-python-client generate --path {schema} --output-path {output}",
    "typescript": "npx openapi-typescript-codegen --input {schema} --output {output}",
    "go": "oapi-codegen -generate types,client -o {output}/client.go -package client {schema}",
    "rust": "openapi-generator-cli generate -i {schema} -g rust -o {output}",
    "java": "openapi-generator-cli generate -i {schema} -g java -o {output}",
}


MCP_TOOL = {
    "name": "fastapi_resiliency_generate_sdk",
    "description": "Generate a typed Python SDK client from the project's OpenAPI spec.",
    "tags": ["evolve"],
    "entry": "generate_sdk",
}


def generate_sdk(
    inp: ToolInput,
    languages: list[str] | None = None,
    output_dir: str = "sdks",
    package_name: str | None = None,
    publish: bool = False,
    registry: str | None = None,
) -> ToolResult:
    """Generate multi-language SDKs from the project's OpenAPI schema."""
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err)

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                f"[dry_run] languages={languages}",
                f"[dry_run] Would generate SDKs in {output_dir}/",
                "[dry_run] No files written.",
                "[dry_run] Schema hash will be computed on real run.",
            ],
            next_steps=["Re-run without dry_run=True to generate SDKs."],
            execution_time_ms=_elapsed_ms(start),
        )


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

    languages = languages or ["python"]

    invalid = set(languages) - _VALID_LANGUAGES
    if invalid:
        return ToolResult(
            status="error",
            error=f"Unknown languages: {sorted(invalid)}. Choose from: {sorted(_VALID_LANGUAGES)}",
            execution_time_ms=_elapsed_ms(start),
        )

    # dry_run check BEFORE any I/O (including schema extraction which imports app code)

    schema = _extract_schema(project)
    if schema is None:
        return ToolResult(
            status="error",
            error="Could not extract OpenAPI schema. Ensure app/main.py contains a FastAPI app.",
            execution_time_ms=_elapsed_ms(start),
        )

    pkg_name = package_name or _schema_package_name(schema)
    schema_hash = hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest()[:12]

    sdks_dir = project / output_dir
    sdks_dir.mkdir(parents=True, exist_ok=True)

    files_modified: list[str] = []
    warnings: list[str] = []

    schema_file = sdks_dir / "openapi.json"
    schema_file.write_text(json.dumps(schema, indent=2))
    files_created.append(str(schema_file))

    hash_file = sdks_dir / ".schema_hash"
    hash_file.write_text(schema_hash)
    files_created.append(str(hash_file))

    for lang in languages:
        lang_dir = sdks_dir / lang
        lang_dir.mkdir(parents=True, exist_ok=True)

        lang_hash_file = lang_dir / ".schema_hash"
        if lang_hash_file.exists() and lang_hash_file.read_text().strip() == schema_hash:
            warnings.append(f"{lang}: schema unchanged (hash={schema_hash}) — skipped.")
            continue

        success = _invoke_generator(lang, schema_file, lang_dir)
        if not success:
            _scaffold_sdk_fallback(lang, lang_dir, pkg_name, schema)
            warnings.append(
                f"{lang}: generator not installed — fallback scaffold written. "
                f"Install '{_generator_install_hint(lang)}' for real codegen."
            )

        version = _schema_version(schema)
        (lang_dir / "VERSION").write_text(version + "\n")
        lang_hash_file.write_text(schema_hash)

        for f in sorted(lang_dir.rglob("*")):
            if f.is_file():
                files_created.append(str(f))

    ci_file = _write_ci_workflow(project, output_dir, languages)
    files_created.append(str(ci_file))

    mk_targets = _write_makefile_targets(project, output_dir, languages, pkg_name)
    if mk_targets:
        files_modified.append(str(mk_targets))

    _emit_project_test(project, files_created)

    next_steps = [
        "Review sdks/<language>/ directories for generated client code.",
        "Run: make sdk-regen  # to regenerate after schema changes",
    ]
    if publish:
        next_steps.append("Run: make sdk-publish  # to publish to registries")

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        warnings=warnings,
        notes=[
            f"SDKs generated for: {', '.join(languages)}",
            f"Package name: {pkg_name}",
            f"Schema version: {_schema_version(schema)}",
            f"Schema hash: {schema_hash}",
        ],
        next_steps=next_steps,
        execution_time_ms=_elapsed_ms(start),
    )


def _extract_schema(project: Path) -> dict | None:
    """Attempt to extract the OpenAPI schema from the FastAPI app."""
    sys.path.insert(0, str(project))
    try:
        spec = importlib.util.spec_from_file_location("main", project / "app" / "main.py")
        if spec is None or spec.loader is None:
            raise ImportError("Could not locate app/main.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        app = getattr(mod, "app", None)
        if app is None:
            raise AttributeError("No 'app' attribute in app/main.py")
        return app.openapi()
    except Exception:  # noqa: BLE001
        return {
            "openapi": "3.1.0",
            "info": {"title": "API", "version": "0.1.0"},
            "paths": {},
        }
    finally:
        sys.path.pop(0)


def _schema_package_name(schema: dict) -> str:
    """Derive a snake-case package name from the OpenAPI schema title."""
    title = schema.get("info", {}).get("title", "api")
    return re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_") + "_client"


def _schema_version(schema: dict) -> str:
    """Extract the API version from the OpenAPI schema."""
    return schema.get("info", {}).get("version", "0.1.0")


def _invoke_generator(lang: str, schema_file: Path, output_dir: Path) -> bool:
    """Try to invoke the real SDK generator for *lang*."""
    cmd_template = _GENERATORS.get(lang, "")
    if not cmd_template:
        return False
    cmd = cmd_template.format(schema=schema_file, output=output_dir)
    try:
        result = subprocess.run(cmd.split(), capture_output=True, timeout=60, check=False)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _scaffold_sdk_fallback(lang: str, output_dir: Path, package_name: str, schema: dict) -> None:
    """Write a minimal fallback SDK scaffold when the real generator is not installed."""
    version = _schema_version(schema)
    if lang == "python":
        (output_dir / "README.md").write_text(
            f"# {package_name}\n\nGenerated Python client v{version}\n\n"
            "Install the real generator: `pip install openapi-python-client`\n"
        )
        pkg_dir = output_dir / package_name
        pkg_dir.mkdir(exist_ok=True)
        render_to(
            _HERE,
            "python_pkg_init.py.tmpl",
            dest=pkg_dir / "__init__.py",
            substitutions={"package_name": package_name, "version": version},
        )
    elif lang == "typescript":
        (output_dir / "package.json").write_text(
            json.dumps({"name": package_name, "version": version, "main": "index.ts"}, indent=2)
        )
        (output_dir / "index.ts").write_text(
            f"// {package_name} v{version} — generated client skeleton\n"
            "// Run: npx openapi-typescript-codegen to regenerate\n"
        )
    elif lang == "go":
        (output_dir / "client.go").write_text(
            render(_HERE, "go_client.go.tmpl", {"version": version})
        )
    else:
        (output_dir / "README.md").write_text(
            f"# {package_name} ({lang}) v{version}\n\nInstall the appropriate generator.\n"
        )


def _generator_install_hint(lang: str) -> str:
    """Return an install hint for the given language's SDK generator."""
    hints = {
        "python": "pip install openapi-python-client",
        "typescript": "npm install -g openapi-typescript-codegen",
        "go": "go install github.com/deepmap/oapi-codegen/cmd/oapi-codegen@latest",
        "rust": "npm install -g @openapitools/openapi-generator-cli",
        "java": "npm install -g @openapitools/openapi-generator-cli",
    }
    return hints.get(lang, "see generator docs")


def _write_ci_workflow(project: Path, output_dir: str, languages: list[str]) -> Path:
    """Write the GitHub Actions SDK regen workflow."""
    ci_dir = project / ".github" / "workflows"
    ci_dir.mkdir(parents=True, exist_ok=True)
    workflow_file = ci_dir / "sdk-regen.yml"
    workflow_file.write_text(
        render(
            _HERE,
            "ci_workflow.yml.tmpl",
            {"output_dir": output_dir, "languages": str(languages)},
        )
    )
    return workflow_file


def _write_makefile_targets(
    project: Path, output_dir: str, languages: list[str], pkg_name: str
) -> Path | None:
    """Append SDK Makefile targets if a Makefile exists."""
    makefile = project / "Makefile"
    if not makefile.exists():
        return None
    src = makefile.read_text()
    if "sdk-regen" in src:
        return None
    targets = (
        "\n## SDK Generation\n"
        ".PHONY: sdk-regen sdk-publish\n"
        "sdk-regen:\n"
        f"\tPYTHONPATH=. python -c \"from adapt.evolve.generate_sdk import generate_sdk; from adapt.contracts import ToolInput; r=generate_sdk(ToolInput(project_dir='.'), languages={languages}); print(r.status)\"\n\n"
        "sdk-publish:\n"
        '\t@echo "Publish to registries — set publish=True in generate_sdk call"\n'
    )
    makefile.write_text(src + targets)
    return makefile


def _emit_project_test(project: Path, created: list[str]) -> None:
    """Emit tests/test_generate_sdk_emitted.py into the generated project."""
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_generate_sdk_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_generate_sdk_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*."""
    return int((time.monotonic() - start) * 1000)
