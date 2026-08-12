"""TOOL-103: add_request_fingerprint — automatic request deduplication.

Generates ``app/fingerprint/`` package (``RequestFingerprinter`` SHA-256 hash
of user_id+method+path+sorted(body), ``FingerprintStore`` Redis-with-memory
fallback) and ``app/middleware/fingerprint.py`` (``FingerprintMiddleware``:
auto-dedup unsafe methods, returns cached response with
``Idempotent-Replayed: true``).

Emitted code lives in ``templates/*.py.tmpl``; this module is orchestration
only.

The tool is idempotent: a second run detects ``RequestFingerprinter`` in
``app/fingerprint/hasher.py`` and returns ``status="no_op"``.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.config_patcher import patch_settings_fields
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_resiliency_add_request_fingerprint",
    "description": (
        "Add automatic request deduplication: SHA-256 fingerprint of user+method+path+body. "
        "Returns cached response on duplicate with Idempotent-Replayed header. "
        "Redis store with in-memory fallback."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_request_fingerprint",
    "imports_primitives": [],
    "imports_adapters": [],

}


def add_request_fingerprint(inp: ToolInput) -> ToolResult:
    """Add request fingerprinting + deduplication to a FastAPI project."""
    start = time.monotonic()
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.CONFIG_SETTINGS,
        Prereq.REQUIREMENTS_TXT,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=[
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    project = Path(inp.project_dir)
    app_dir = project / "app"
    fingerprint_file = app_dir / "fingerprint" / "hasher.py"

    if fingerprint_file.exists() and "RequestFingerprinter" in fingerprint_file.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "RequestFingerprinter already present — fingerprinting already enabled, skipped."
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/fingerprint/ package with hasher, store.",
                "[dry_run] Would add FingerprintMiddleware to app/main.py.",
                "[dry_run] Would patch app/core/config.py with FINGERPRINT_* fields.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    files_modified: list[str] = []

    fp_dir = app_dir / "fingerprint"
    fp_dir.mkdir(parents=True, exist_ok=True)

    init_file = fp_dir / "__init__.py"
    render_to(_HERE, "fp_init.py.tmpl", dest=init_file, substitutions={})
    files_created.append(str(init_file))

    render_to(_HERE, "fp_hasher.py.tmpl", dest=fingerprint_file, substitutions={})
    files_created.append(str(fingerprint_file))

    store_file = fp_dir / "store.py"
    render_to(_HERE, "fp_store.py.tmpl", dest=store_file, substitutions={})
    files_created.append(str(store_file))

    middleware_dir = app_dir / "middleware"
    middleware_dir.mkdir(parents=True, exist_ok=True)
    middleware_file = middleware_dir / "fingerprint.py"
    render_to(_HERE, "fp_middleware.py.tmpl", dest=middleware_file, substitutions={})
    files_created.append(str(middleware_file))

    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        patch_settings_fields(
            config_file,
            fields=[
                ("FINGERPRINT_ENABLED", "FINGERPRINT_ENABLED: bool = False"),
                ("FINGERPRINT_TTL_S", "FINGERPRINT_TTL_S: int = 60"),
                ("FINGERPRINT_METHODS", 'FINGERPRINT_METHODS: str = "POST,PUT,PATCH"'),
            ],
        )
        files_modified.append(str(config_file))

    for path_str in files_created:
        p = Path(path_str)
        if p.suffix == ".py" and p.is_file():
            try:
                ast.parse(p.read_text())
            except SyntaxError as exc:
                return ToolResult(
                    status="error",
                    error=f"Generated file has syntax error: {p}: {exc}",
                    execution_time_ms=_elapsed_ms(start),
                )

    _emit_project_test(project, files_created)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "Request fingerprinting added: SHA-256 hash of user_id+method+path+sorted(body).",
            "FingerprintStore: Redis primary with in-memory fallback (works without Redis).",
            "FingerprintMiddleware: deduplicates POST/PUT (configurable), adds Idempotent-Replayed header.",
            "Duplicate detection within FINGERPRINT_TTL_S window (default: 60 s).",
            "⚠ FingerprintMiddleware IS NOT auto-wired into app/main.py — you must call "
            "app.add_middleware(FingerprintMiddleware) yourself for dedup to apply.",
            "⚠ Cached response body is held in an in-process dict — replay is NOT shared "
            "across worker processes, even when the duplicate-detection store uses Redis.",
        ],
        next_steps=[
            "Set FINGERPRINT_ENABLED=true in .env (default: false).",
            "Optional: set FINGERPRINT_TTL_S (default: 60 seconds).",
            "Optional: set FINGERPRINT_METHODS=POST,PUT,PATCH (comma-separated).",
            "pip install 'redis[hiredis]' for Redis store (falls back to memory without Redis).",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _emit_project_test(project: Path, created: list[str]) -> None:
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_request_fingerprint_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_request_fingerprint_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


