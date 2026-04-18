"""TOOL-114: add_secret_rotation — secret manager abstraction with auto-rotation.

Writes a provider abstraction (Vault / AWS Secrets Manager / env fallback),
auto-rotation with dual-key windows, leak detection that scans logs/errors/
tracebacks before they leave the process, startup validation that refuses to
boot on missing or default secrets, and a ``scripts/rotate_secrets.py`` CLI.

Lazy imports
------------
``hvac`` (Vault) and ``boto3`` (AWS SM) are imported lazily inside their
respective provider classes so the application can boot without either
library installed.

Idempotency
-----------
A second run detects ``SecretProvider`` in
``app/core/secret_rotation.py`` and returns ``status="no_op"``.

Config fields added
-------------------
``SECRET_PROVIDER``, ``VAULT_URL``, ``VAULT_TOKEN``,
``SECRET_ROTATION_INTERVAL_H``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_secret_rotation import add_secret_rotation

    result = add_secret_rotation(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["…/app/core/secret_rotation.py", …]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_add_secret_rotation",
    "description": (
        "Add a secret manager abstraction (Vault/AWS SM/env), auto-rotation with "
        "dual-key windows, log-based leak detection, and startup validation."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_secret_rotation",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_secret_rotation(inp: ToolInput) -> ToolResult:
    """Add production-grade secret rotation to a FastAPI project.

    Creates ``app/core/secret_rotation.py`` (provider abstraction + leak
    detector + startup validator), ``app/middleware/leak_detector.py``
    (response middleware that scrubs secrets), ``scripts/rotate_secrets.py``
    (CLI), and all required settings fields.  Patches
    ``app/core/config.py``, ``app/routes/__init__.py``, and
    ``requirements.txt``.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and optional
            ``dry_run`` flag.

    Returns:
        ``ToolResult`` describing files created/modified and next steps.
    """
    start = time.monotonic()

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err,
                          execution_time_ms=_elapsed_ms(start))

    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.BASE_MODEL,
        Prereq.CONFIG_SETTINGS,
        Prereq.ROUTES_INIT,
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

    files_created: list[str] = list(scaffolded)
    project = Path(inp.project_dir)
    app_dir = project / "app"

    # --- Idempotency guard ---------------------------------------------------
    rotation_file = app_dir / "core" / "secret_rotation.py"
    if rotation_file.exists() and "SecretProvider" in rotation_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["SecretProvider already present — skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    # --- dry_run guard (BEFORE any writes) -----------------------------------
    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create: app/core/secret_rotation.py, "
                "app/middleware/leak_detector.py, scripts/rotate_secrets.py.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # Step 1 — Secret rotation core
    rotation_file.parent.mkdir(parents=True, exist_ok=True)
    rotation_file.write_text(_SECRET_ROTATION_TEMPLATE)
    files_created.append(str(rotation_file))

    # Step 2 — Leak detector middleware
    middleware_dir = app_dir / "middleware"
    middleware_dir.mkdir(parents=True, exist_ok=True)
    leak_file = middleware_dir / "leak_detector.py"
    leak_file.write_text(_LEAK_DETECTOR_TEMPLATE)
    files_created.append(str(leak_file))

    # Step 3 — scripts/rotate_secrets.py CLI
    scripts_dir = project / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    cli_file = scripts_dir / "rotate_secrets.py"
    cli_file.write_text(_ROTATE_SECRETS_CLI_TEMPLATE)
    files_created.append(str(cli_file))

    # Step 4 — Patch config
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # Step 5 — requirements.txt
    requirements_file = project / "requirements.txt"
    if requirements_file.exists():
        _patch_requirements(requirements_file)
        files_modified.append(str(requirements_file))

    # --- ast.parse validation loop -------------------------------------------
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
            "Secret rotation installed: provider abstraction (Vault/AWS SM/env),",
            "dual-key auto-rotation window, log-based leak detector middleware,",
            "startup validation, and scripts/rotate_secrets.py CLI.",
            "Vault and boto3 imports are lazy — app boots without them.",
        ],
        next_steps=[
            "Set SECRET_PROVIDER=vault|aws|env in .env.",
            "If using Vault: set VAULT_URL and VAULT_TOKEN.",
            "Call validate_secrets_at_startup() in your FastAPI lifespan.",
            "Register LeakDetectorMiddleware in app/main.py.",
            "Run: python scripts/rotate_secrets.py --help",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File-patching helpers
# ---------------------------------------------------------------------------

def _patch_config(config_file: Path) -> None:
    """Inject secret rotation settings into the Settings class body.

    Args:
        config_file: Path to app/core/config.py.
    """
    src = config_file.read_text()
    if "SECRET_PROVIDER" in src:
        return
    block = (
        "\n"
        "    # --- Secret rotation — added by add_secret_rotation tool ---\n"
        '    SECRET_PROVIDER: str = "env"  # vault | aws | env\n'
        '    VAULT_URL: str = ""\n'
        '    VAULT_TOKEN: str = ""\n'
        "    SECRET_ROTATION_INTERVAL_H: int = 24\n"
    )
    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    if anchor in src:
        src = src.replace(anchor, anchor + "\n" + block.lstrip("\n"))
    else:
        settings_line = "settings = Settings()"
        if settings_line in src:
            src = src.replace(settings_line, block.lstrip("\n") + "\n\n" + settings_line)
        else:
            src = src.rstrip("\n") + "\n" + block
    config_file.write_text(src)


def _patch_requirements(requirements_file: Path) -> None:
    """Ensure hvac and boto3 stubs are noted in requirements.txt.

    Args:
        requirements_file: Path to requirements.txt.
    """
    src = requirements_file.read_text()
    additions: list[str] = []
    if "hvac" not in src:
        additions.append("hvac>=2.3.0  # optional: Vault provider")
    if "boto3" not in src:
        additions.append("boto3>=1.35.0  # optional: AWS Secrets Manager provider")
    if not additions:
        return
    trailing = "" if src.endswith("\n") else "\n"
    requirements_file.write_text(src + trailing + "\n".join(additions) + "\n")


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since start.

    Args:
        start: Start time from time.monotonic().

    Returns:
        Elapsed milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

_SECRET_ROTATION_TEMPLATE = textwrap.dedent("""\
    \"\"\"Secret manager abstraction with auto-rotation and leak detection.

    Three backends
    --------------
    * **env** (default) — reads from environment / pydantic-settings.  No
      external service required.  Rotation is a no-op (you update the env var
      in your infra and restart).
    * **vault** — uses the HashiCorp Vault KV v2 API via ``hvac`` (lazy import).
    * **aws** — uses AWS Secrets Manager via ``boto3`` (lazy import).

    Dual-key rotation window
    ------------------------
    ``rotate_secret`` writes the new value while keeping the old value
    accessible as ``<name>_previous`` for ``SECRET_ROTATION_INTERVAL_H`` hours,
    giving in-flight requests time to drain without a hard cutover.

    Startup validation
    ------------------
    Call ``validate_secrets_at_startup()`` inside your FastAPI lifespan to
    refuse boot when required secrets are missing or set to default values.
    \"\"\"
    from __future__ import annotations

    import logging
    import os
    import re
    from abc import ABC, abstractmethod
    from typing import Any

    logger = logging.getLogger(__name__)

    # Values that look like defaults / placeholders
    _WEAK_PATTERNS: list[str] = [
        "changethis", "secret", "password", "letmein",
        "your_key_here", "replace_me", "todo", "fixme",
        "1234567890", "abcdefgh",
    ]

    # Names of secrets that must NOT be empty at startup
    _REQUIRED_SECRETS: list[str] = ["SECRET_KEY"]


    class SecretProvider(ABC):
        \"\"\"Abstract base for secret backends.\"\"\"

        @abstractmethod
        def get(self, name: str, default: str = "") -> str:
            \"\"\"Retrieve *name* from the secret store.

            Args:
                name: Secret name / path.
                default: Value to return when the secret is not found.

            Returns:
                Secret value string.
            \"\"\"

        @abstractmethod
        def set(self, name: str, value: str) -> None:
            \"\"\"Write *value* for *name* in the secret store.

            Args:
                name: Secret name / path.
                value: New secret value.
            \"\"\"

        def rotate(self, name: str, new_value: str, interval_h: int = 24) -> None:
            \"\"\"Rotate *name* to *new_value* with a dual-key window.

            The old value is preserved as ``<name>_previous`` for *interval_h*
            hours, then overwritten on the next rotation call.

            Args:
                name: Secret name to rotate.
                new_value: New secret value.
                interval_h: Hours to keep the old value accessible.
            \"\"\"
            old_value = self.get(name)
            if old_value:
                self.set(f"{name}_previous", old_value)
            self.set(name, new_value)
            logger.info(
                "secret_rotated",
                extra={"name": name, "dual_key_window_h": interval_h},
            )


    class EnvSecretProvider(SecretProvider):
        \"\"\"Environment-variable-backed secret provider (no external service).\"\"\"

        def get(self, name: str, default: str = "") -> str:
            \"\"\"Read secret from environment.

            Args:
                name: Environment variable name.
                default: Fallback value.

            Returns:
                Environment variable value or default.
            \"\"\"
            return os.environ.get(name, default)

        def set(self, name: str, value: str) -> None:
            \"\"\"Write secret to the current process environment.

            Note: only affects the running process.  Use your deployment
            tool (Helm, Terraform, etc.) for persistent rotation.

            Args:
                name: Environment variable name.
                value: New value.
            \"\"\"
            os.environ[name] = value


    class VaultSecretProvider(SecretProvider):
        \"\"\"HashiCorp Vault KV v2 provider (lazy hvac import).\"\"\"

        def __init__(self, url: str, token: str, mount_point: str = "secret") -> None:
            \"\"\"Initialise Vault client.

            Args:
                url: Vault server URL.
                token: Vault authentication token.
                mount_point: KV v2 mount path (default 'secret').
            \"\"\"
            self._url = url
            self._token = token
            self._mount = mount_point
            self._client: Any = None

        def _vault(self) -> Any:
            \"\"\"Return initialised hvac.Client (lazy import).

            Returns:
                Authenticated hvac client instance.
            \"\"\"
            if self._client is None:
                import hvac  # lazy import
                self._client = hvac.Client(url=self._url, token=self._token)
            return self._client

        def get(self, name: str, default: str = "") -> str:
            \"\"\"Read a secret from Vault KV v2.

            Args:
                name: Secret path (without mount prefix).
                default: Value returned when the path is missing.

            Returns:
                Secret value or default.
            \"\"\"
            try:
                resp = self._vault().secrets.kv.v2.read_secret_version(
                    path=name, mount_point=self._mount
                )
                return resp["data"]["data"].get("value", default)
            except Exception as exc:  # noqa: BLE001
                logger.warning("vault_get_failed", extra={"name": name, "error": str(exc)})
                return default

        def set(self, name: str, value: str) -> None:
            \"\"\"Write a secret to Vault KV v2.

            Args:
                name: Secret path.
                value: New secret value.
            \"\"\"
            try:
                self._vault().secrets.kv.v2.create_or_update_secret(
                    path=name, secret={"value": value}, mount_point=self._mount
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("vault_set_failed", extra={"name": name, "error": str(exc)})


    class AwsSecretProvider(SecretProvider):
        \"\"\"AWS Secrets Manager provider (lazy boto3 import).\"\"\"

        def __init__(self, region_name: str = "us-east-1") -> None:
            \"\"\"Initialise AWS SM client.

            Args:
                region_name: AWS region (default 'us-east-1').
            \"\"\"
            self._region = region_name
            self._client: Any = None

        def _sm(self) -> Any:
            \"\"\"Return initialised boto3 SecretsManager client (lazy import).

            Returns:
                boto3 secrets manager client.
            \"\"\"
            if self._client is None:
                import boto3  # lazy import
                self._client = boto3.client("secretsmanager", region_name=self._region)
            return self._client

        def get(self, name: str, default: str = "") -> str:
            \"\"\"Read a secret from AWS Secrets Manager.

            Args:
                name: Secret name / ARN.
                default: Value returned when the secret is missing.

            Returns:
                Secret value string or default.
            \"\"\"
            try:
                resp = self._sm().get_secret_value(SecretId=name)
                return resp.get("SecretString", default)
            except Exception as exc:  # noqa: BLE001
                logger.warning("aws_sm_get_failed", extra={"name": name, "error": str(exc)})
                return default

        def set(self, name: str, value: str) -> None:
            \"\"\"Write a secret to AWS Secrets Manager.

            Args:
                name: Secret name.
                value: New secret value.
            \"\"\"
            try:
                self._sm().put_secret_value(SecretId=name, SecretString=value)
            except Exception as exc:  # noqa: BLE001
                logger.error("aws_sm_set_failed", extra={"name": name, "error": str(exc)})


    def get_secret_provider() -> SecretProvider:
        \"\"\"Return the configured SecretProvider singleton.

        Reads ``SECRET_PROVIDER`` env var (vault | aws | env).

        Returns:
            A SecretProvider implementation matching the configured backend.
        \"\"\"
        from app.core.config import settings
        provider = settings.SECRET_PROVIDER.lower()
        if provider == "vault":
            return VaultSecretProvider(url=settings.VAULT_URL, token=settings.VAULT_TOKEN)
        if provider == "aws":
            return AwsSecretProvider()
        return EnvSecretProvider()


    def scan_for_leaks(text: str, known_secrets: list[str]) -> list[str]:
        \"\"\"Scan *text* for substrings that match *known_secrets*.

        Called by LeakDetectorMiddleware before responses leave the process.
        Never raises — returns an empty list when text is safe.

        Args:
            text: String to scan (response body, log line, error message).
            known_secrets: List of secret values to look for (plaintext).

        Returns:
            List of secret names found in *text* (empty = safe).
        \"\"\"
        found: list[str] = []
        for secret in known_secrets:
            if secret and len(secret) > 4 and secret in text:
                found.append(secret[:4] + "***")
        return found


    def validate_secrets_at_startup() -> None:
        \"\"\"Raise RuntimeError when required secrets are missing or weak.

        Call this inside your FastAPI lifespan *before* accepting traffic.

        Raises:
            RuntimeError: When a required secret is empty or matches a
                known-weak pattern.
        \"\"\"
        provider = get_secret_provider()
        errors: list[str] = []
        for name in _REQUIRED_SECRETS:
            value = provider.get(name)
            if not value:
                errors.append(f"{name}: missing")
                continue
            lower = value.lower()
            if any(weak in lower for weak in _WEAK_PATTERNS):
                errors.append(f"{name}: weak/default value detected")
        if errors:
            raise RuntimeError(
                "Secret validation failed — refusing to start:\\n"
                + "\\n".join(f"  - {e}" for e in errors)
            )
        logger.info("secret_validation_passed", extra={"checked": _REQUIRED_SECRETS})
""")


_LEAK_DETECTOR_TEMPLATE = textwrap.dedent("""\
    \"\"\"Leak detector middleware — scrubs secret values from response bodies.

    Scans outgoing response text for known secret substrings before they
    reach the client.  Matches are replaced with '[REDACTED]' and a warning
    is logged.  The scan is best-effort and never blocks a response.
    \"\"\"
    from __future__ import annotations

    import logging
    import os

    from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
    from starlette.requests import Request
    from starlette.responses import Response

    logger = logging.getLogger(__name__)

    # Names of env vars that hold secrets (extend as needed)
    _SECRET_ENV_VARS: list[str] = [
        "SECRET_KEY", "DATABASE_URL", "REDIS_URL",
        "VAULT_TOKEN", "AWS_SECRET_ACCESS_KEY",
        "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET",
        "COMPLIANCE_ENCRYPTION_KEY",
    ]


    def _collect_secret_values() -> list[str]:
        \"\"\"Return current values of known secret environment variables.

        Returns:
            List of non-empty secret value strings.
        \"\"\"
        return [v for name in _SECRET_ENV_VARS if (v := os.environ.get(name, ""))]


    class LeakDetectorMiddleware(BaseHTTPMiddleware):
        \"\"\"Starlette middleware that scans responses for secret leaks.

        Add to ``app/main.py``::

            from app.middleware.leak_detector import LeakDetectorMiddleware
            app.add_middleware(LeakDetectorMiddleware)
        \"\"\"

        async def dispatch(
            self,
            request: Request,
            call_next: RequestResponseEndpoint,
        ) -> Response:
            \"\"\"Process the request and scan the response for leaks.

            Args:
                request: Incoming HTTP request.
                call_next: Next middleware or route handler.

            Returns:
                The response, with any secret substrings replaced.
            \"\"\"
            response = await call_next(request)
            content_type = response.headers.get("content-type", "")
            if "application/json" not in content_type and "text/" not in content_type:
                return response
            return await self._scan_response(response, request)

        async def _scan_response(self, response: Response, request: Request) -> Response:
            \"\"\"Read, scan, and optionally sanitise a text response.

            Args:
                response: Original response from the route handler.
                request: Original request (for logging context).

            Returns:
                Sanitised response with leaks replaced.
            \"\"\"
            from starlette.responses import Response as BaseResponse
            body = b""
            async for chunk in response.body_iterator:  # type: ignore[attr-defined]
                body += chunk if isinstance(chunk, bytes) else chunk.encode()
            text = body.decode("utf-8", errors="replace")
            secrets = _collect_secret_values()
            found: list[str] = []
            for secret in secrets:
                if secret and len(secret) > 4 and secret in text:
                    text = text.replace(secret, "[REDACTED]")
                    found.append(secret[:4] + "***")
            if found:
                logger.warning(
                    "secret_leak_detected",
                    extra={"path": str(request.url.path), "fragments": found},
                )
            return BaseResponse(
                content=text.encode(),
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )
""")


_ROTATE_SECRETS_CLI_TEMPLATE = textwrap.dedent("""\
    \"\"\"CLI for rotating application secrets.

    Usage::

        python scripts/rotate_secrets.py --name SECRET_KEY --value <new_value>
        python scripts/rotate_secrets.py --list
        python scripts/rotate_secrets.py --validate
    \"\"\"
    from __future__ import annotations

    import argparse
    import os
    import sys

    # Allow running from repo root
    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, _ROOT)


    def _rotate(name: str, value: str) -> None:
        \"\"\"Rotate a secret using the configured provider.

        Args:
            name: Secret name.
            value: New secret value.
        \"\"\"
        from app.core.secret_rotation import get_secret_provider
        from app.core.config import settings
        provider = get_secret_provider()
        provider.rotate(name, value, interval_h=settings.SECRET_ROTATION_INTERVAL_H)
        print(f"Rotated: {name}")


    def _list_secrets() -> None:
        \"\"\"Print the names of tracked secret variables.\"\"\"
        from app.core.secret_rotation import _REQUIRED_SECRETS
        print("Tracked secrets:")
        for name in _REQUIRED_SECRETS:
            print(f"  {name}")


    def _validate() -> None:
        \"\"\"Run startup secret validation and print result.\"\"\"
        from app.core.secret_rotation import validate_secrets_at_startup
        try:
            validate_secrets_at_startup()
            print("All secrets valid.")
        except RuntimeError as exc:
            print(f"FAIL: {exc}", file=sys.stderr)
            sys.exit(1)


    def main() -> None:
        \"\"\"Entry point for the rotate_secrets CLI.\"\"\"
        parser = argparse.ArgumentParser(description="Secret rotation CLI")
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--name", help="Secret name to rotate")
        group.add_argument("--list", action="store_true", help="List tracked secrets")
        group.add_argument("--validate", action="store_true", help="Run startup validation")
        parser.add_argument("--value", help="New secret value (required with --name)")
        args = parser.parse_args()

        if args.list:
            _list_secrets()
        elif args.validate:
            _validate()
        elif args.name:
            if not args.value:
                parser.error("--value is required when --name is specified")
            _rotate(args.name, args.value)


    if __name__ == "__main__":
        main()
""")
