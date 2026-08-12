---
spec_id: "TOOL-114"
tool_name: "add_secret_rotation"
version: "1.0.0"
status: "ratified"
invariants:
  - "INV-ROT-001"
  - "INV-ROT-002"
  - "INV-ROT-003"
  - "INV-ROT-004"
  - "INV-ROT-005"
  - "INV-ROT-006"
  - "INV-ROT-007"
  - "INV-ROT-008"
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
quality_standards:
  - "QS-1"
  - "QS-10"
  - "QS-11"
  - "QS-12"
  - "QS-13"
  - "QS-14"
  - "QS-15"
  - "QS-16"
  - "QS-17"
  - "QS-18"
  - "QS-2"
  - "QS-3"
  - "QS-4"
  - "QS-5"
  - "QS-6"
  - "QS-7"
  - "QS-8"
  - "QS-9"
tags:
  - "performance"
  - "data"
  - "realtime"
  - "api"
  - "testing"
---
# TOOL-114 — add_secret_rotation

## 1. Overview

| Field | Value |
|---|---|
| **Tool ID** | TOOL-114 |
| **MCP name** | `fastapi_add_secret_rotation` |
| **Entry point** | `adapt/extend/infrastructure/add_secret_rotation.py::add_secret_rotation` |
| **Tags** | `security`, `secrets`, `vault`, `aws`, `rotation`, `leak-detection` |
| **Input** | `ToolInput(project_dir, dry_run=False)` |
| **Output** | `ToolResult(status, files_created, files_modified, notes, next_steps, execution_time_ms)` |
| **Idempotency fingerprint** | `"SecretProvider" in app/core/secret_rotation.py` |
| **Prerequisite check** | `app/` directory exists |
| **Files created (min)** | 3 (`secret_rotation.py`, `leak_detector.py`, `rotate_secrets.py`) |
| **Files modified (min)** | 2 (`app/core/config.py`, `requirements.txt`) |
| **Test file** | `adapt/extend/infrastructure/test_add_secret_rotation.py` |

---

## 2. Purpose

Production FastAPI applications store secrets — database passwords, API keys, signing tokens — that must rotate periodically. Without provider abstraction this becomes a copy-paste operation with no safety net. `add_secret_rotation` installs a complete secret lifecycle system in five steps:

1. **Provider abstraction** — `SecretProvider` ABC with three concrete implementations: `EnvSecretProvider` (reads `os.getenv`), `VaultSecretProvider` (hvac, lazy import), `AwsSecretProvider` (boto3, lazy import). The active provider is chosen at startup from `SECRET_PROVIDER` env var (`env` | `vault` | `aws`).

2. **Dual-key rotation window** — `rotate()` stores the new value under `<name>` and the old value under `<name>_previous`. During a rolling restart both keys are valid, preventing instant auth failures.

3. **Startup validation** — `validate_secrets_at_startup()` iterates all registered secret names and asserts none match `_WEAK_PATTERNS = ["changethis", "secret", "password", "admin", "test"]`. Raises `RuntimeError` if any weak pattern is detected.

4. **LeakDetectorMiddleware** — ASGI middleware registered in `app/middleware/leak_detector.py`. Before each response is forwarded to the client it scans the response body bytes for substrings matching registered secret values. If a match is found the body is replaced with a `REDACTED` message and the event is logged. Secret values are never concatenated into log messages — only boolean presence is recorded.

5. **CLI** — `scripts/rotate_secrets.py` with `argparse` providing `--name`, `--list`, `--validate` sub-commands so ops teams can trigger rotations without redeploying.

External dependencies (`hvac`, `boto3`) are never imported at module top level. Both appear only inside the class body of `VaultSecretProvider` and `AwsSecretProvider` respectively, so the app boots without them installed — only the configured provider is loaded at runtime.

Config injection anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` to guarantee the four new fields are placed inside the `Settings` class body with 4-space indent.

---

## 3. Performance SLOs

| Metric | Target |
|---|---|
| Tool execution time | < 2 s on a cold fixture project |
| `execution_time_ms` field | > 0 (always recorded) |
| Leak scan overhead per request | < 1 ms (linear scan of response body) |
| Files created | exactly 3 |
| Files modified | exactly 2 (`config.py`, `requirements.txt`) |
| Max function LOC in generated `app/` | ≤ 50 |

---

## 4. Before / After

### 4.1 Project state — before

```
app/
  core/
    config.py     # Settings class; no secret rotation fields
  main.py
requirements.txt  # no hvac or boto3 entries
```

### 4.2 Project state — after

```
app/
  core/
    config.py          # 4 new SECRET_* fields injected
    secret_rotation.py # SecretProvider, EnvSecretProvider,
                       # VaultSecretProvider, AwsSecretProvider,
                       # rotate(), validate_secrets_at_startup()
  middleware/
    leak_detector.py   # LeakDetectorMiddleware + scan_for_leaks()
scripts/
  rotate_secrets.py    # CLI with --name / --list / --validate
requirements.txt       # hvac>=2.3.0 and boto3>=1.35.0 appended
```

### 4.3 SecretProvider ABC + EnvSecretProvider

```python
# app/core/secret_rotation.py (generated)
"""Secret manager abstraction with auto-rotation and leak detection."""

from __future__ import annotations

import abc
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_WEAK_PATTERNS = ["changethis", "secret", "password", "admin", "test"]


class SecretProvider(abc.ABC):
    """Abstract base class for all secret providers."""

    @abc.abstractmethod
    def get(self, name: str) -> Optional[str]:
        """Return the current secret value for *name*."""

    @abc.abstractmethod
    def set(self, name: str, value: str) -> None:
        """Store *value* under *name*."""

    def rotate(self, name: str, new_value: str) -> None:
        """Implement dual-key rotation: save old as <name>_previous."""
        current = self.get(name)
        if current:
            self.set(f"{name}_previous", current)
        self.set(name, new_value)


class EnvSecretProvider(SecretProvider):
    """Read-only provider backed by os.environ."""

    def get(self, name: str) -> Optional[str]:
        return os.environ.get(name)

    def set(self, name: str, value: str) -> None:
        os.environ[name] = value
```

### 4.4 VaultSecretProvider (hvac lazy import)

```python
class VaultSecretProvider(SecretProvider):
    """HashiCorp Vault provider; hvac is imported lazily."""

    def __init__(self, url: str, token: str) -> None:
        self._url = url
        self._token = token
        self._client: object = None

    def _ensure_client(self) -> None:
        if self._client is None:
            import hvac  # lazy — installed only when provider=vault
            self._client = hvac.Client(url=self._url, token=self._token)

    def get(self, name: str) -> Optional[str]:
        self._ensure_client()
        # ... vault KV read
```

### 4.5 Config patch

```python
# app/core/config.py — injected block (anchored after ACCESS_TOKEN_EXPIRE_MINUTES)

    # --- Secret rotation — added by add_secret_rotation tool ---
    SECRET_PROVIDER: str = "env"  # vault | aws | env
    VAULT_URL: str = ""
    VAULT_TOKEN: str = ""
    SECRET_ROTATION_INTERVAL_H: int = 24
```

### 4.6 LeakDetectorMiddleware

```python
# app/middleware/leak_detector.py (generated)

class LeakDetectorMiddleware(BaseHTTPMiddleware):
    """Scan response body for accidental secret exposure."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        if scan_for_leaks(body):
            logger.warning("leak_detector.secret_in_response", extra={"path": request.url.path})
            return Response(content=b"REDACTED", status_code=200, ...)
        return Response(content=body, ...)
```

---

## 5. Quality Standards

| ID | Standard |
|---|---|
| QS-1 | `status == "success"` on first run against a fresh fixture project |
| QS-2 | Second run returns `status == "no_op"` with empty `files_created` and `files_modified` |
| QS-3 | `dry_run=True` returns `status == "success"` and writes zero bytes to disk |
| QS-4 | `files_created` contains ≥ 3 entries; all paths exist on disk |
| QS-5 | `files_modified` contains ≥ 2 entries; all paths exist on disk |
| QS-6 | Every generated `.py` file passes `ast.parse()` without `SyntaxError` |
| QS-7 | No function in `app/` exceeds 50 LOC (verified via AST walk) |
| QS-8 | All four `SECRET_*` config fields appear in `config.py` with 4-space indent inside `Settings` |
| QS-9 | `hvac` is NOT imported at module top level in `secret_rotation.py` |
| QS-10 | `boto3` is NOT imported at module top level in `secret_rotation.py` |
| QS-11 | `SecretProvider` ABC and `EnvSecretProvider` class exist in `secret_rotation.py` |
| QS-12 | `LeakDetectorMiddleware` exists in `app/middleware/leak_detector.py` with `scan_for_leaks` or `REDACTED` |
| QS-13 | `scripts/rotate_secrets.py` exists with `def main` and `argparse` CLI |
| QS-14 | `rotate` method and `previous` dual-key pattern exist in `secret_rotation.py` |
| QS-15 | `validate_secrets_at_startup` function exists and references `changethis` or `_WEAK_PATTERNS` |
| QS-16 | `requirements.txt` contains both `hvac` and `boto3` entries |
| QS-17 | No secret values are concatenated into log statements (regex check on logger calls) |
| QS-18 | `execution_time_ms > 0` in all `ToolResult` instances |

---

## 6. Completeness Criteria

| ID | Test function | What it verifies |
|---|---|---|
| CC-01 | `test_success_status` | Tool returns `status='success'` on a fresh project |
| CC-02 | `test_idempotent` | Second run returns `status='no_op'`; `files_created` and `files_modified` both empty |
| CC-03 | `test_dry_run` | `dry_run=True` returns success without writing any bytes to disk |
| CC-04 | `test_files_created_count` | At least 3 files created; all exist on disk |
| CC-05 | `test_files_modified_count` | At least 2 files modified (config, requirements); all exist on disk |
| CC-06 | `test_all_py_parse` | Every generated `.py` file AST-parses clean |
| CC-07 | `test_no_function_over_50_loc` | No function in `app/` exceeds 50 LOC |
| CC-08 | `test_config_fields_patched` | `SECRET_PROVIDER`, `VAULT_URL`, `VAULT_TOKEN`, `SECRET_ROTATION_INTERVAL_H` present with 4-space indent |
| CC-09 | `test_secret_rotation_file_exists` | `app/core/secret_rotation.py` exists with `SecretProvider` and `EnvSecretProvider` |
| CC-10 | `test_vault_provider_lazy_import` | `hvac` NOT imported at module top level |
| CC-11 | `test_boto3_lazy_import` | `boto3` NOT imported at module top level |
| CC-12 | `test_leak_detector_created` | `app/middleware/leak_detector.py` exists with `LeakDetectorMiddleware` and leak scanning |
| CC-13 | `test_rotate_secrets_cli_created` | `scripts/rotate_secrets.py` exists with `def main` and `argparse` |
| CC-14 | `test_dual_key_rotation_present` | `rotate` method and `previous` dual-key pattern in `secret_rotation.py` |
| CC-15 | `test_startup_validation_present` | `validate_secrets_at_startup` exists; references weak-pattern detection |
| CC-16 | `test_requirements_patched` | `requirements.txt` contains `hvac` and `boto3` |
| CC-17 | `test_no_secrets_in_logs` | `logger.*` calls never concatenate `{value}`, `{token}`, or `{secret}` |
| CC-18 | `test_execution_time_recorded` | `execution_time_ms > 0` |
| CC-19 | `test_next_steps_present` | `next_steps` non-empty; mentions `SECRET_PROVIDER` or `vault` |
| CC-20 | `test_idempotent_project_still_parses` | All `.py` files parse after two consecutive runs |

---

## 7. Definition of Done

- [ ] All 20 tests in `test_add_secret_rotation.py` pass
- [ ] `SecretProvider` ABC + 3 concrete implementations (`Env`, `Vault`, `Aws`) generated
- [ ] `hvac` and `boto3` imported lazily — only inside class methods
- [ ] Dual-key rotation window implemented via `rotate()` + `<name>_previous`
- [ ] `validate_secrets_at_startup()` checks `_WEAK_PATTERNS`
- [ ] `LeakDetectorMiddleware` scans response bodies; secret values never logged
- [ ] `scripts/rotate_secrets.py` CLI with `--name`, `--list`, `--validate`
- [ ] Config fields injected with 4-space indent inside `Settings` class
- [ ] `requirements.txt` updated with `hvac>=2.3.0` and `boto3>=1.35.0`
- [ ] `execution_time_ms` recorded; `next_steps` non-empty

---

## 8. Invariants

| ID | Invariant |
|---|---|
| INV-ROT-001 | `hvac` is NEVER imported at module top level in `secret_rotation.py` |
| INV-ROT-002 | `boto3` is NEVER imported at module top level in `secret_rotation.py` |
| INV-ROT-003 | Secret values are NEVER concatenated into any log statement |
| INV-ROT-004 | `rotate()` ALWAYS stores the old value as `<name>_previous` before overwriting |
| INV-ROT-005 | Idempotency fingerprint is `"SecretProvider" in app/core/secret_rotation.py` |
| INV-ROT-006 | Config block is anchored to `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` |
| INV-ROT-007 | `LeakDetectorMiddleware` response scanning never blocks the request path on exception |
| INV-ROT-008 | All generated `.py` files pass `ast.parse()` before `ToolResult` is returned |

---

## 9. User Stories

| ID | Story |
|---|---|
| US-01 | As a platform engineer, I want to rotate database passwords without redeploying, so that I can comply with 90-day rotation policies. |
| US-02 | As a security engineer, I want a LeakDetectorMiddleware that catches accidental secret exposure in API responses, so that secrets never reach clients. |
| US-03 | As an operator, I want a `scripts/rotate_secrets.py` CLI, so that I can trigger rotations from a CI pipeline without writing code. |
| US-04 | As a developer, I want `validate_secrets_at_startup()` to reject weak patterns at boot, so that weak default secrets never reach production. |
| US-05 | As a platform architect, I want hvac and boto3 to be lazy imports, so that the app boots successfully even when only the `env` provider is configured. |
| US-06 | As an SRE, I want dual-key rotation (old value stored as `<name>_previous`), so that rolling restarts do not cause instant auth failures during rotation. |

---

## 10. Design Decisions

| Decision | Rationale |
|---|---|
| Three concrete providers behind a single ABC | Enables provider swapping via env var without code change |
| Lazy `hvac`/`boto3` imports | App must start without optional cloud SDKs installed |
| `_WEAK_PATTERNS` constant list | Allows expansion without changing function signature |
| Dual-key window via `<name>_previous` | Standard pattern for zero-downtime secret rotation |
| `scan_for_leaks()` scans full response body | Catches serialization bugs that embed secrets in JSON |
| Config anchored on `ACCESS_TOKEN_EXPIRE_MINUTES` | Guarantees 4-space indent inside `Settings` class |
| `argparse` CLI in `scripts/` | Usable from CI/CD pipelines without importing app code |
| Secret values never in log format strings | Prevents log-aggregation systems from capturing secrets |

---

## 11. Dependencies

| Package | Version | Purpose | Import style |
|---|---|---|---|
| `hvac` | `>=2.3.0` | HashiCorp Vault client | Lazy (inside `VaultSecretProvider`) |
| `boto3` | `>=1.35.0` | AWS Secrets Manager client | Lazy (inside `AwsSecretProvider`) |
| `starlette` | (FastAPI dep) | `BaseHTTPMiddleware` for `LeakDetectorMiddleware` | Top-level |

---

## 12. Error Handling

| Scenario | Behavior |
|---|---|
| `secret_rotation.py` already contains `SecretProvider` | Return `status="no_op"` immediately |
| `app/` directory missing | Return `status="error"` with descriptive `error` field |
| Generated `.py` has `SyntaxError` | Return `status="error"`; file is NOT committed to disk |
| `hvac` not installed at runtime | `ImportError` raised lazily inside `VaultSecretProvider._ensure_client()` |
| `boto3` not installed at runtime | `ImportError` raised lazily inside `AwsSecretProvider._ensure_client()` |
| `validate_secrets_at_startup()` finds weak pattern | Raises `RuntimeError` to prevent server startup |
| `LeakDetectorMiddleware` exception during scan | Exception is caught; original response forwarded unmodified |

---

## 13. Security Considerations

- `LeakDetectorMiddleware` must catch all exceptions — a scanner crash must never block a legitimate response.
- The `_WEAK_PATTERNS` list must be checked case-insensitively.
- Secret values must NEVER appear in any log statement at any level — only boolean detection results are logged.
- `hvac` and `boto3` are intentionally optional — missing SDKs produce `ImportError` only when the provider is used, not at startup.
- `rotate()` stores `<name>_previous` as a deliberate dual-window, not as a backup — operators must clean it up after rollout.
- `validate_secrets_at_startup()` should be called inside the FastAPI lifespan, not at import time.

---

## 14. Testing Guide

```bash
# Run the full test suite
PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_secret_rotation.py -v

# Run standalone (no pytest required)
PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_secret_rotation.py

# Run a single test
PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_secret_rotation.py::test_vault_provider_lazy_import -v

# Check idempotency manually
python3 -c "
from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_secret_rotation import add_secret_rotation
from tests.common.fixture_factory import create_fixture_project
p = create_fixture_project(name='rot_manual')
r1 = add_secret_rotation(ToolInput(project_dir=str(p)))
r2 = add_secret_rotation(ToolInput(project_dir=str(p)))
print('r1:', r1.status, 'created:', len(r1.files_created))
print('r2:', r2.status, 'created:', len(r2.files_created))
"
```

---

## 15. Files Reference

| File | Role |
|---|---|
| `adapt/extend/infrastructure/add_secret_rotation.py` | Tool entry point |
| `adapt/extend/infrastructure/test_add_secret_rotation.py` | 20-test structural test suite |
| `app/core/secret_rotation.py` | SecretProvider ABC, 3 providers, rotate(), validate_secrets_at_startup() |
| `app/middleware/leak_detector.py` | LeakDetectorMiddleware |
| `scripts/rotate_secrets.py` | CLI: --name, --list, --validate |
| `app/core/config.py` | Patched with SECRET_PROVIDER, VAULT_URL, VAULT_TOKEN, SECRET_ROTATION_INTERVAL_H |
| `requirements.txt` | Patched with hvac>=2.3.0, boto3>=1.35.0 |

---

## 16. Changelog

| Version | Date | Change |
|---|---|---|
| 1.0.0 | 2026-04-15 | Initial spec — 20 CCs, dual-key rotation, lazy imports, LeakDetectorMiddleware |
