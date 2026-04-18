"""TOOL-124: add_api_fuzzer — schema-aware adversarial fuzzing for FastAPI.

Generates an ``APIFuzzer`` that reads the OpenAPI schema, builds adversarial
inputs per field type (boundary ints, unicode edge cases, SQL payloads, XSS
vectors, empty/null/huge strings), hits each endpoint N times, and reports
any non-JSON 5xx/timeout/crash results.  No external dependencies required.

Idempotent: a second run detects ``APIFuzzer`` in
``app/fuzzer/__init__.py`` and returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.testing_tools.add_api_fuzzer import add_api_fuzzer

    result = add_api_fuzzer(ToolInput(project_dir="/path/to/project"))
    print(result.status)         # "success"
    print(result.files_created)  # [.../app/fuzzer/__init__.py, ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_add_api_fuzzer",
    "description": (
        "Add schema-aware API fuzzing: APIFuzzer reads OpenAPI schema, generates adversarial "
        "inputs per field type (boundary ints, unicode, SQL payloads, XSS vectors, empty/null/"
        "huge strings). FuzzRunner hits each endpoint N times, reports non-JSON 5xx/timeout/"
        "crash. scripts/run_fuzz.py CLI. Config: FUZZ_ITERATIONS, FUZZ_TIMEOUT_S, "
        "FUZZ_EXCLUDE_PATHS. No external deps."
    ),
    "tags": ["extend", "testing_tools"],
    "entry": "add_api_fuzzer",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_api_fuzzer(inp: ToolInput) -> ToolResult:
    """Add schema-aware API fuzzing to a FastAPI project.

    Writes ``app/fuzzer/`` package and ``scripts/run_fuzz.py``, patches
    ``app/core/config.py`` with fuzz knobs.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err,
                          execution_time_ms=_elapsed_ms(start))

    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

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
            notes=["Generate a base project first: fastapi_generate_project(...)"],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    if scaffolded:
        files_created.extend(scaffolded)

    project = Path(inp.project_dir)
    app_dir = project / "app"

    # --- Idempotency guard ---------------------------------------------------
    fuzzer_init = app_dir / "fuzzer" / "__init__.py"
    if fuzzer_init.exists() and "APIFuzzer" in fuzzer_init.read_text():
        return ToolResult(
            status="no_op",
            notes=["APIFuzzer already present — API fuzzer already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/fuzzer/ package with APIFuzzer, generators, runner.",
                "[dry_run] Would create scripts/run_fuzz.py CLI.",
                "[dry_run] Would patch app/core/config.py with fuzz config fields.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # --- Step 1: fuzzer package ----------------------------------------------
    fuzzer_dir = app_dir / "fuzzer"
    fuzzer_dir.mkdir(parents=True, exist_ok=True)

    _write_fuzzer_init(fuzzer_init)
    files_created.append(str(fuzzer_init))

    _write_generators(fuzzer_dir / "generators.py")
    files_created.append(str(fuzzer_dir / "generators.py"))

    _write_runner(fuzzer_dir / "runner.py")
    files_created.append(str(fuzzer_dir / "runner.py"))

    # --- Step 2: scripts/run_fuzz.py -----------------------------------------
    scripts_dir = project / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    _write_cli_script(scripts_dir / "run_fuzz.py")
    files_created.append(str(scripts_dir / "run_fuzz.py"))

    # --- Step 3: Patch config.py ---------------------------------------------
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # --- Validate generated .py files ----------------------------------------
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

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "API fuzzer enabled: APIFuzzer reads OpenAPI schema from /openapi.json.",
            "Generators cover: boundary ints, unicode edge cases, SQL payloads, XSS vectors, "
            "empty/null/huge strings (1 MB).",
            "FuzzRunner hits each discovered endpoint N times and collects non-JSON 5xx/timeout.",
            "Zero external dependencies — pure Python stdlib + httpx (already in requirements).",
            "Run: python scripts/run_fuzz.py --base-url http://localhost:8000",
        ],
        next_steps=[
            "Set FUZZ_ITERATIONS in .env (default: 10 per endpoint).",
            "Set FUZZ_TIMEOUT_S in .env (default: 5).",
            "Set FUZZ_EXCLUDE_PATHS=/docs,/openapi.json in .env to skip read-only routes.",
            "Run: python scripts/run_fuzz.py --base-url http://localhost:8000",
            "Pipe results to a file: python scripts/run_fuzz.py --output fuzz_report.json",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers — each < 50 LOC
# ---------------------------------------------------------------------------

def _write_fuzzer_init(dest: Path) -> None:
    """Write app/fuzzer/__init__.py — APIFuzzer schema reader.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"API fuzzer — schema-aware adversarial test input generator.\"\"\"

        from __future__ import annotations

        import logging
        import os
        from typing import Any

        logger = logging.getLogger(__name__)


        class APIFuzzer:
            \"\"\"Reads OpenAPI schema and generates adversarial inputs per field type.

            Args:
                base_url: Target server base URL (e.g. 'http://localhost:8000').
                schema: Pre-loaded OpenAPI schema dict.  When None the schema is
                    fetched from ``{base_url}/openapi.json`` by FuzzRunner.
            \"\"\"

            def __init__(self, base_url: str, schema: dict[str, Any] | None = None) -> None:
                self.base_url = base_url.rstrip("/")
                self._schema: dict[str, Any] = schema or {}

            def set_schema(self, schema: dict[str, Any]) -> None:
                \"\"\"Replace the loaded schema.

                Args:
                    schema: OpenAPI 3.x schema dict from /openapi.json.
                \"\"\"
                self._schema = schema

            def endpoint_list(self) -> list[dict[str, Any]]:
                \"\"\"Return a list of endpoint descriptors from the loaded schema.

                Each descriptor has 'method', 'path', and 'body_schema' keys.

                Returns:
                    List of dicts describing each POST/PUT/PATCH endpoint.
                \"\"\"
                endpoints = []
                paths = self._schema.get("paths", {})
                exclude_raw = os.getenv("FUZZ_EXCLUDE_PATHS", "/docs,/openapi.json,/redoc")
                excluded = [p.strip() for p in exclude_raw.split(",") if p.strip()]
                for path, methods in paths.items():
                    if any(path.startswith(ex) for ex in excluded):
                        continue
                    for method in ("post", "put", "patch"):
                        if method not in methods:
                            continue
                        op = methods[method]
                        body_schema = _extract_body_schema(op, self._schema)
                        endpoints.append({
                            "method": method.upper(),
                            "path": path,
                            "body_schema": body_schema,
                        })
                return endpoints

            def generate_payloads(
                self, body_schema: dict[str, Any] | None
            ) -> list[dict[str, Any]]:
                \"\"\"Generate a list of adversarial payload dicts for a body schema.

                Args:
                    body_schema: JSON Schema dict for the request body.  When
                        None a set of structurally adversarial payloads is returned.

                Returns:
                    List of dicts ready to be JSON-serialised as request bodies.
                \"\"\"
                from app.fuzzer.generators import build_payloads_for_schema

                return build_payloads_for_schema(body_schema or {})


        def _extract_body_schema(
            op: dict[str, Any], full_schema: dict[str, Any]
        ) -> dict[str, Any] | None:
            \"\"\"Extract the request body JSON schema from an OpenAPI operation dict.

            Args:
                op: Operation dict from the OpenAPI paths object.
                full_schema: Full OpenAPI schema (used for $ref resolution).

            Returns:
                A JSON Schema dict, or None if no request body is defined.
            \"\"\"
            rb = op.get("requestBody", {})
            content = rb.get("content", {})
            json_content = content.get("application/json", {})
            schema = json_content.get("schema")
            if schema is None:
                return None
            if "$ref" in schema:
                ref = schema["$ref"].lstrip("#/").split("/")
                node: Any = full_schema
                for part in ref:
                    node = node.get(part, {})
                return node if isinstance(node, dict) else None
            return schema
        """))


def _write_generators(dest: Path) -> None:
    """Write app/fuzzer/generators.py — adversarial value generators.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Adversarial test value generators for the API fuzzer.\"\"\"

        from __future__ import annotations

        from typing import Any


        # ---------------------------------------------------------------------------
        # Field-level generators
        # ---------------------------------------------------------------------------

        def int_values() -> list[Any]:
            \"\"\"Return boundary and adversarial integer values.\"\"\"
            return [0, 1, -1, 2**31 - 1, -(2**31), 2**63 - 1, -(2**63),
                    99999999999, -99999999999, None, "not_an_int", 1.5]


        def string_values() -> list[Any]:
            \"\"\"Return adversarial string values (empty, huge, SQL, XSS, unicode).\"\"\"
            sql_payloads = ["' OR '1'='1", "'; DROP TABLE users; --",
                            "1; SELECT * FROM information_schema.tables"]
            xss_vectors = ['<script>alert(1)</script>', '"><img src=x onerror=alert(1)>',
                           "javascript:alert(1)"]
            unicode_edge = ["\\x00", "\\uffff", "\\u202e", "A" * 1_048_576, ""]
            control_chars = ["\\r\\n", "\\n" * 3, "\\t" * 3]
            null_and_type_confuse: list[Any] = [None, 0, False, [], {}]
            return sql_payloads + xss_vectors + unicode_edge + control_chars + null_and_type_confuse


        def bool_values() -> list[Any]:
            \"\"\"Return adversarial boolean values.\"\"\"
            return [True, False, None, 1, 0, "true", "false", "yes", "no"]


        def number_values() -> list[Any]:
            \"\"\"Return adversarial float/number values.\"\"\"
            return [0.0, -0.0, 1e308, -1e308, float("inf"), float("-inf"),
                    float("nan"), None, "not_a_number"]


        def array_values() -> list[Any]:
            \"\"\"Return adversarial array values.\"\"\"
            return [[], [None], list(range(10000)), [string_values()[0]]]


        _FIELD_TYPE_GENERATORS = {
            "integer": int_values,
            "number": number_values,
            "string": string_values,
            "boolean": bool_values,
            "array": array_values,
        }

        _MAX_PAYLOADS_PER_SCHEMA = 20


        def build_payloads_for_schema(schema: dict[str, Any]) -> list[dict[str, Any]]:
            \"\"\"Build a list of adversarial payload dicts for a JSON schema.

            Each payload has one field set to an adversarial value while others
            carry a minimal valid default so the request is structurally parseable.

            Args:
                schema: JSON Schema dict describing the request body properties.

            Returns:
                List of adversarial payload dicts (capped at _MAX_PAYLOADS_PER_SCHEMA).
            \"\"\"
            props = schema.get("properties", {})
            if not props:
                return [_empty_payload(), _huge_payload(), _nested_null()]

            payloads: list[dict[str, Any]] = []
            defaults = _default_values(props)

            for field_name, field_schema in list(props.items())[:8]:
                field_type = field_schema.get("type", "string")
                gen = _FIELD_TYPE_GENERATORS.get(field_type, string_values)
                for value in gen()[:3]:
                    payload = dict(defaults)
                    payload[field_name] = value
                    payloads.append(payload)
                    if len(payloads) >= _MAX_PAYLOADS_PER_SCHEMA:
                        return payloads

            return payloads or [_empty_payload()]


        def _default_values(props: dict[str, Any]) -> dict[str, Any]:
            \"\"\"Build a minimal valid payload from property definitions.

            Args:
                props: OpenAPI properties dict.

            Returns:
                Dict mapping each field to a minimal valid default value.
            \"\"\"
            defaults: dict[str, Any] = {}
            for name, schema in props.items():
                t = schema.get("type", "string")
                defaults[name] = {"integer": 1, "number": 1.0, "boolean": True,
                                  "array": [], "object": {}}.get(t, "test")
            return defaults


        def _empty_payload() -> dict[str, Any]:
            \"\"\"Return an empty payload dict.\"\"\"
            return {}


        def _huge_payload() -> dict[str, Any]:
            \"\"\"Return a payload with a 1 MB string value.\"\"\"
            return {"data": "A" * 1_048_576}


        def _nested_null() -> dict[str, Any]:
            \"\"\"Return a deeply nested null payload.\"\"\"
            return {"a": {"b": {"c": None}}}
        """))


def _write_runner(dest: Path) -> None:
    """Write app/fuzzer/runner.py — FuzzRunner async HTTP fuzzer.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"FuzzRunner — hits each endpoint with adversarial payloads and reports issues.\"\"\"

        from __future__ import annotations

        import asyncio
        import logging
        import os
        import time
        from typing import Any

        logger = logging.getLogger(__name__)


        class FuzzResult:
            \"\"\"Container for a single fuzz attempt result.

            Attributes:
                method: HTTP method used.
                path: Endpoint path tested.
                payload: The adversarial payload sent.
                status_code: HTTP response status code.
                is_json: Whether the response body was valid JSON.
                elapsed_ms: Round-trip latency in milliseconds.
                error: Exception message if the request itself failed.
            \"\"\"

            def __init__(
                self,
                method: str,
                path: str,
                payload: dict,
                status_code: int,
                is_json: bool,
                elapsed_ms: int,
                error: str | None = None,
            ) -> None:
                self.method = method
                self.path = path
                self.payload = payload
                self.status_code = status_code
                self.is_json = is_json
                self.elapsed_ms = elapsed_ms
                self.error = error

            def is_finding(self) -> bool:
                \"\"\"Return True when this result represents a fuzz finding.

                A finding is a non-JSON 5xx, a request timeout, or a crash.
                \"\"\"
                if self.error:
                    return True
                if self.status_code >= 500 and not self.is_json:
                    return True
                return False

            def to_dict(self) -> dict[str, Any]:
                \"\"\"Serialise this result to a plain dict.\"\"\"
                return {
                    "method": self.method,
                    "path": self.path,
                    "status_code": self.status_code,
                    "is_json": self.is_json,
                    "elapsed_ms": self.elapsed_ms,
                    "is_finding": self.is_finding(),
                    "error": self.error,
                }


        class FuzzRunner:
            \"\"\"Orchestrates fuzzing: fetch schema, generate payloads, run requests.

            Args:
                base_url: Target server base URL.
                iterations: Number of payloads to try per endpoint.
                timeout_s: Per-request timeout in seconds.
            \"\"\"

            def __init__(
                self,
                base_url: str,
                iterations: int | None = None,
                timeout_s: int | None = None,
            ) -> None:
                self.base_url = base_url.rstrip("/")
                self.iterations = iterations or int(os.getenv("FUZZ_ITERATIONS", "10"))
                self.timeout_s = timeout_s or int(os.getenv("FUZZ_TIMEOUT_S", "5"))

            async def run(self) -> list[FuzzResult]:
                \"\"\"Fetch the schema, generate payloads, and run all fuzz requests.

                Returns:
                    List of FuzzResult objects.  Filter with ``.is_finding()`` for
                    actionable issues only.
                \"\"\"
                import httpx  # noqa: PLC0415

                from app.fuzzer import APIFuzzer

                async with httpx.AsyncClient(
                    base_url=self.base_url,
                    timeout=self.timeout_s,
                ) as client:
                    schema = await self._fetch_schema(client)
                    fuzzer = APIFuzzer(self.base_url, schema=schema)
                    endpoints = fuzzer.endpoint_list()
                    logger.info("Fuzzing %d endpoints (%d iterations each)",
                                len(endpoints), self.iterations)
                    results: list[FuzzResult] = []
                    for ep in endpoints:
                        payloads = fuzzer.generate_payloads(ep["body_schema"])
                        for payload in payloads[: self.iterations]:
                            result = await self._fuzz_one(
                                client, ep["method"], ep["path"], payload
                            )
                            results.append(result)
                    return results

            async def _fetch_schema(self, client: Any) -> dict[str, Any]:
                \"\"\"Download the OpenAPI schema from the target server.

                Args:
                    client: Async httpx client.

                Returns:
                    OpenAPI schema dict.
                \"\"\"
                try:
                    resp = await client.get("/openapi.json")
                    return resp.json()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Failed to fetch schema: %s", exc)
                    return {}

            async def _fuzz_one(
                self,
                client: Any,
                method: str,
                path: str,
                payload: dict[str, Any],
            ) -> FuzzResult:
                \"\"\"Send one adversarial request and return a FuzzResult.

                Args:
                    client: Async httpx client.
                    method: HTTP method (POST, PUT, PATCH).
                    path: Endpoint path to target.
                    payload: Adversarial body payload.

                Returns:
                    FuzzResult describing the outcome.
                \"\"\"
                t0 = time.monotonic()
                try:
                    resp = await client.request(method, path, json=payload)
                    elapsed = int((time.monotonic() - t0) * 1000)
                    is_json = True
                    try:
                        resp.json()
                    except Exception:  # noqa: BLE001
                        is_json = False
                    return FuzzResult(method, path, payload, resp.status_code,
                                      is_json, elapsed)
                except Exception as exc:  # noqa: BLE001
                    elapsed = int((time.monotonic() - t0) * 1000)
                    return FuzzResult(method, path, payload, 0, False, elapsed,
                                      error=str(exc))
        """))


def _write_cli_script(dest: Path) -> None:
    """Write scripts/run_fuzz.py — CLI runner for the API fuzzer.

    Args:
        dest: Absolute path for the CLI script.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"CLI script to run the API fuzzer against a running FastAPI server.

        Usage::

            python scripts/run_fuzz.py --base-url http://localhost:8000
            python scripts/run_fuzz.py --base-url http://localhost:8000 --output fuzz_report.json

        Options:
            --base-url     Target server base URL (required).
            --iterations   Payloads per endpoint (default: FUZZ_ITERATIONS env var or 10).
            --timeout      Per-request timeout in seconds (default: FUZZ_TIMEOUT_S or 5).
            --output       Write JSON report to this file (default: stdout).
        \"\"\"

        from __future__ import annotations

        import argparse
        import asyncio
        import json
        import sys
        from pathlib import Path


        def _parse_args() -> argparse.Namespace:
            \"\"\"Parse CLI arguments for the fuzz runner.\"\"\"
            parser = argparse.ArgumentParser(description="Schema-aware API fuzzer for FastAPI")
            parser.add_argument("--base-url", required=True, help="Target server base URL")
            parser.add_argument("--iterations", type=int, default=None,
                                help="Payloads per endpoint (overrides FUZZ_ITERATIONS)")
            parser.add_argument("--timeout", type=int, default=None,
                                help="Per-request timeout in seconds (overrides FUZZ_TIMEOUT_S)")
            parser.add_argument("--output", default=None,
                                help="Write JSON report to file (default: stdout)")
            return parser.parse_args()


        def _emit_report(report: dict, output_path: str | None, findings: list) -> int:
            \"\"\"Write the fuzz report to stdout or a file and return exit code.

            Args:
                report: Full fuzz report dict ready to JSON-serialise.
                output_path: Optional file path to write the report to.
                findings: List of finding dicts for exit code calculation.

            Returns:
                0 when no findings, 1 when findings were detected.
            \"\"\"
            output_json = json.dumps(report, indent=2)
            if output_path:
                Path(output_path).write_text(output_json)
                print(f"Report written to {output_path}", file=sys.stderr)
            else:
                print(output_json)
            if findings:
                print(f"\\n{len(findings)} finding(s) detected!", file=sys.stderr)
                return 1
            print("No findings.", file=sys.stderr)
            return 0


        async def _main() -> int:
            \"\"\"Run the fuzzer and return the exit code.

            Returns:
                0 when no findings, 1 when findings were detected, 2 on error.
            \"\"\"
            args = _parse_args()
            script_dir = Path(__file__).resolve().parent
            project_root = script_dir.parent
            if str(project_root) not in sys.path:
                sys.path.insert(0, str(project_root))
            try:
                from app.fuzzer.runner import FuzzRunner
            except ImportError as exc:
                print(f"ERROR: Cannot import FuzzRunner: {exc}", file=sys.stderr)
                print("Make sure you are running from the project root.", file=sys.stderr)
                return 2
            runner = FuzzRunner(
                base_url=args.base_url,
                iterations=args.iterations,
                timeout_s=args.timeout,
            )
            print(f"Fuzzing {args.base_url} ...", file=sys.stderr)
            results = await runner.run()
            findings = [r.to_dict() for r in results if r.is_finding()]
            all_results = [r.to_dict() for r in results]
            report = {
                "base_url": args.base_url,
                "total_requests": len(results),
                "findings": len(findings),
                "results": all_results,
            }
            return _emit_report(report, args.output, findings)


        if __name__ == "__main__":
            sys.exit(asyncio.run(_main()))
        """))


def _patch_config(config_file: Path) -> None:
    """Inject fuzzer settings into app/core/config.py.

    Fields are inserted inside the ``class Settings`` body with 4-space
    indent so Pydantic picks them up as class-level field declarations.

    Args:
        config_file: Path to ``app/core/config.py``.
    """
    src = config_file.read_text()
    if "FUZZ_ITERATIONS" in src:
        return

    fuzz_fields = (
        "\n"
        "    # API fuzzer settings — added by add_api_fuzzer tool\n"
        "    FUZZ_ITERATIONS: int = 10\n"
        "    FUZZ_TIMEOUT_S: int = 5\n"
        '    FUZZ_EXCLUDE_PATHS: str = "/docs,/openapi.json,/redoc"\n'
    )

    if "settings = Settings()" in src:
        src = src.replace(
            "settings = Settings()",
            fuzz_fields + "\n\nsettings = Settings()",
        )
    else:
        src = src.rstrip("\n") + fuzz_fields
    config_file.write_text(src)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start* (from ``time.monotonic()``).

    Args:
        start: Start time from ``time.monotonic()``.

    Returns:
        Elapsed time in milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)
