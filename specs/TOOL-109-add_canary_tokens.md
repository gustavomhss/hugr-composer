---
spec_id: "TOOL-109"
tool_name: "add_canary_tokens"
version: "1.0.0"
status: "ratified"
invariants:
  - "INV-CT-01"
  - "INV-CT-02"
  - "INV-CT-03"
  - "INV-CT-04"
  - "INV-CT-05"
  - "INV-CT-06"
  - "INV-CT-07"
  - "INV-CT-08"
  - "INV-CT-09"
  - "INV-CT-10"
completeness_criteria:
  - "CC-01"
  - "CC-02"
  - "CC-03"
  - "CC-04"
  - "CC-05"
  - "CC-06"
  - "CC-07"
  - "CC-08"
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
  - "CC-N-1"
quality_standards:
  - "QS-02"
  - "QS-03"
  - "QS-04"
  - "QS-1"
  - "QS-10"
  - "QS-11"
  - "QS-12"
  - "QS-13"
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
  - "resiliency"
  - "realtime"
  - "compliance"
---
# TOOL-109: add_canary_tokens

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_canary_tokens` |
| Category | EXTEND > Infrastructure |
| Complexity | High |
| Dependencies | FastAPI, pydantic-settings, SQLAlchemy 2.0 (optional decoy seed) |
| Signature | `add_canary_tokens(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_canary_tokens", "description": "Add canary tokens (honeypot endpoints, fake credentials, decoy DB records) for intrusion detection.", "tags": ["extend", "infrastructure"], "entry": "add_canary_tokens"}` |
| Files created (typical) | 5 — `app/core/canary/registry.py`, `app/core/canary/alerter.py`, `app/api/routes/canary_honeypot.py`, `app/core/canary/fake_credentials.py`, `app/core/canary/decoy_seeder.py` |
| Files modified (typical) | 2 — `app/core/config.py`, `app/routes/__init__.py` |

---

## 2. Purpose

The `fastapi_add_canary_tokens` tool installs a production-grade canary token (honeypot) intrusion detection system into a FastAPI project. A canary token is a trap: a resource that should never be accessed by legitimate users but will be accessed by attackers who have obtained credentials or are conducting reconnaissance. When a canary is triggered, an alert fires — typically a webhook to a SIEM or Slack channel — giving defenders an early warning signal before the attacker reaches real data.

This tool implements three canary strategies. **Honeypot endpoints** — fake routes (`/internal/config`, `/admin/backup`, `/debug/env`) that always return HTTP 200 with plausible fake data. A real admin would never need these; any access is an indicator of compromise. **Fake credentials** — `CANARY_AWS_ACCESS_KEY_ID`, `CANARY_DATABASE_URL` with placeholder values that can be "leaked" in a controlled way. If these credentials are used against a real AWS account or database (with a corresponding monitor), access triggers an alert. **Decoy database records** — `seed_decoy_records()` inserts two fake admin users with `is_canary_email()` detectable email addresses (`canary-admin-1@example-canary.com`) using `ON CONFLICT DO NOTHING` so re-seeding is safe.

The `CanaryRegistry` stores pre-registered `CanaryToken` objects (frozen dataclass, fingerprint = sha256[:16]) and exposes `register`, `get`, `all_tokens`. Five tokens are pre-registered: three honeypot, one credential, one decoy_record. The `fire_canary_alert` function posts to `CANARY_ALERT_WEBHOOK_URL` as a fire-and-forget coroutine that catches all exceptions (`BLE001` pattern) so a webhook failure never breaks the response. `httpx` is imported lazily inside `_post_webhook()` to avoid a module-level dependency. `build_request_context` masks `Authorization` and `Cookie` headers with `***` before logging.

CRITICAL design rule: honeypot endpoints **always return HTTP 200 with fake data** — they must never raise `HTTPException` or return error codes, because an attacker testing for honeypots would probe for 4xx responses.

The tool patches `app/core/config.py` with `CANARY_ENABLED: bool = True` and `CANARY_ALERT_WEBHOOK_URL: str = ""`. The idempotency fingerprint is `class CanaryRegistry` in `app/core/canary/registry.py`.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | CI budget; measured via `execution_time_ms` |
| Files created | ≥ 4 | Registry, alerter, honeypot routes, credentials, decoy seeder |
| Files modified | ≥ 1 | Config at minimum |
| Max function LOC in generated code | ≤ 50 | Auditable; AST-checked |
| Honeypot response time | < 5 ms | In-memory fake data; no I/O |
| Alert webhook latency | Fire-and-forget | Never blocks the response; max 30 s background |
| Decoy seed operation | Idempotent | `ON CONFLICT DO NOTHING` |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── main.py
│   ├── core/
│   │   └── config.py        # No CANARY_* fields
│   └── api/routes/
│       └── (no honeypot routes)
```

Attackers with stolen credentials can probe the API silently for minutes before any alert fires.

### 4.2 Canary registry and token: AFTER

```python
# app/core/canary/registry.py
"""Canary token registry — the central store for all canary assets."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True)
class CanaryToken:
    """An immutable canary token with a computed fingerprint."""

    name: str
    token_type: str  # "honeypot", "credential", "decoy_record"
    description: str

    @property
    def fingerprint(self) -> str:
        """16-char SHA-256 prefix of name+type."""
        raw = f"{self.name}:{self.token_type}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


class CanaryRegistry:
    """In-memory store of registered canary tokens.

    All canary tokens are class-level to survive across instances.
    """

    _tokens: ClassVar[dict[str, CanaryToken]] = {}

    def register(self, name: str, token_type: str, description: str) -> CanaryToken:
        """Register a new canary token and return it."""
        token = CanaryToken(name=name, token_type=token_type, description=description)
        self.__class__._tokens[name] = token
        return token

    def get(self, name: str) -> CanaryToken | None:
        """Look up a canary token by name."""
        return self.__class__._tokens.get(name)

    def all_tokens(self) -> list[CanaryToken]:
        """Return all registered canary tokens."""
        return list(self.__class__._tokens.values())


_registry = CanaryRegistry()
# Pre-register production canaries
_registry.register("honeypot_config", "honeypot", "GET /internal/config")
_registry.register("honeypot_backup", "honeypot", "GET /admin/backup")
_registry.register("honeypot_env", "honeypot", "GET /debug/env")
_registry.register("credential_aws", "credential", "Fake AWS credentials")
_registry.register("decoy_record", "decoy_record", "Fake admin DB records")
```

### 4.3 Alert module (fire-and-forget, never raises): AFTER

```python
# app/core/canary/alerter.py
"""Canary alert dispatcher — fire-and-forget webhook notifications."""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


def build_request_context(request_info: dict) -> dict:
    """Build a safe request context, masking auth headers."""
    context = dict(request_info)
    headers = dict(context.get("headers", {}))
    for sensitive_key in ("authorization", "cookie", "x-api-key"):
        if sensitive_key in headers:
            headers[sensitive_key] = "***"
    context["headers"] = headers
    return context


async def _post_webhook(url: str, payload: dict) -> None:
    """Send the alert payload to the webhook URL."""
    try:
        import httpx  # noqa: PLC0415 — lazy import, no module-level dep
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(url, json=payload)
    except Exception:  # noqa: BLE001
        logger.warning("Canary webhook post failed", exc_info=True)


async def fire_canary_alert(
    token_name: str,
    request_context: dict,
    webhook_url: str,
) -> None:
    """Fire an alert for a triggered canary token.

    Never raises — alert failure must not affect the response.
    """
    if not webhook_url:
        logger.warning("Canary triggered but CANARY_ALERT_WEBHOOK_URL not set: %s", token_name)
        return
    payload = {
        "canary": token_name,
        "context": build_request_context(request_context),
    }
    try:
        asyncio.ensure_future(_post_webhook(webhook_url, payload))
    except Exception:  # noqa: BLE001
        pass
```

### 4.4 Honeypot routes (always HTTP 200, no raise): AFTER

```python
# app/api/routes/canary_honeypot.py
"""Honeypot routes — always return HTTP 200 with fake data.

DO NOT raise HTTPException from these handlers. An attacker testing
for honeypots will probe for 4xx/5xx responses. Return plausible-
looking 200 responses to make the trap indistinguishable from real
endpoints.
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from app.core.canary.alerter import fire_canary_alert
from app.core.config import settings

router = APIRouter(tags=["_canary"])

_FAKE_CONFIG = {"db_host": "db-internal.example.com", "debug": False}
_FAKE_BACKUP = {"backup_id": "bkp-20260101", "status": "complete", "size_mb": 1024}
_FAKE_ENV = {"ENVIRONMENT": "production", "VERSION": "1.0.0"}


@router.get("/internal/config")
async def honeypot_config(request: Request) -> dict:
    """Honeypot: fake internal config endpoint."""
    ctx = {"path": str(request.url), "method": request.method, "headers": dict(request.headers)}
    await fire_canary_alert("honeypot_config", ctx, settings.CANARY_ALERT_WEBHOOK_URL)
    return _FAKE_CONFIG


@router.get("/admin/backup")
async def honeypot_backup(request: Request) -> dict:
    """Honeypot: fake admin backup endpoint."""
    ctx = {"path": str(request.url), "method": request.method, "headers": dict(request.headers)}
    await fire_canary_alert("honeypot_backup", ctx, settings.CANARY_ALERT_WEBHOOK_URL)
    return _FAKE_BACKUP


@router.get("/debug/env")
async def honeypot_env(request: Request) -> dict:
    """Honeypot: fake debug env endpoint."""
    ctx = {"path": str(request.url), "method": request.method, "headers": dict(request.headers)}
    await fire_canary_alert("honeypot_env", ctx, settings.CANARY_ALERT_WEBHOOK_URL)
    return _FAKE_ENV
```

### 4.5 Fake credentials module: AFTER

```python
# app/core/canary/fake_credentials.py
"""Placeholder canary credentials — never real values."""
from __future__ import annotations

# These are placeholder values only — never use real credentials here.
# Replace with monitored fake credentials for production canary use.
CANARY_AWS_ACCESS_KEY_ID: str = "AKIAIOSFODNN7EXAMPLE"
CANARY_DATABASE_URL: str = "postgresql://canary:canary@db.example.com/canary"
```

### 4.6 Decoy seeder: AFTER

```python
# app/core/canary/decoy_seeder.py
"""Seed decoy admin records for canary detection."""
from __future__ import annotations

_CANARY_DOMAIN = "@example-canary.com"
_DECOY_EMAILS = [f"canary-admin-{i}{_CANARY_DOMAIN}" for i in range(1, 3)]


def is_canary_email(email: str) -> bool:
    """Return True if *email* is a known canary decoy address."""
    return email in _DECOY_EMAILS


async def seed_decoy_records(db) -> None:  # type: ignore[type-arg]
    """Insert two decoy admin users into the database.

    Uses ON CONFLICT DO NOTHING so re-seeding is safe.
    """
    try:
        for email in _DECOY_EMAILS:
            await db.execute(
                "INSERT INTO users (email, is_admin) VALUES (:email, true) "
                "ON CONFLICT DO NOTHING",
                {"email": email},
            )
        await db.commit()
    except Exception:  # noqa: BLE001
        pass
```

### 4.7 Config patch (inside `class Settings`)

```python
# app/core/config.py  (diff, added by _patch_config)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # --- canary token settings — added by add_canary_tokens tool ---
    CANARY_ENABLED: bool = True
    CANARY_ALERT_WEBHOOK_URL: str = ""
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Tool is idempotent on second run** | `"class CanaryRegistry" in registry.py` → `status="no_op"` |
| QS-2 | **`dry_run=True` writes zero files** | Early return before any write |
| QS-3 | **Every generated `.py` AST-parses** | `ast.parse` on each created `.py` |
| QS-4 | **No generated function exceeds 50 LOC** | AST walk; all handlers kept short |
| QS-5 | **Honeypots always return HTTP 200** | No `raise HTTPException` in `canary_honeypot.py` |
| QS-6 | **Alert never raises** | `except Exception: pass` / `BLE001` pattern in `alerter.py` |
| QS-7 | **Auth/Cookie headers masked before logging** | `build_request_context` replaces sensitive headers with `***` |
| QS-8 | **`httpx` imported lazily** | `import httpx` inside `_post_webhook` function body only |
| QS-9 | **5 tokens pre-registered** | 3 honeypot + 1 credential + 1 decoy_record |
| QS-10 | **Decoy seed uses `ON CONFLICT DO NOTHING`** | `seed_decoy_records` is idempotent |
| QS-11 | **No TODO/FIXME/HACK** | Scan all generated `.py` |
| QS-12 | **`CANARY_*` inside `class Settings`** | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES` |
| QS-13 | **`execution_time_ms` is positive** | `_elapsed_ms(start)` on all return paths |

---

## 6. Completeness Criteria

Every criterion is tied to a real assertion in `adapt/extend/infrastructure/test_add_canary_tokens.py`.

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | Tool returns `status="success"` on a fresh project | `result.status == "success"` | `test_success_status` |
| CC-02 | Second run returns `status="no_op"` with zero file ops | `r2.status == "no_op"` and both lists empty | `test_idempotent` |
| CC-03 | `dry_run=True` writes zero bytes to filesystem | `before == after` over all `.py` | `test_dry_run` |
| CC-04 | Tool creates at least 4 new files | `len(files_created) >= 4` | `test_files_created_count` |
| CC-05 | Tool modifies at least 1 existing file | `len(files_modified) >= 1` | `test_files_modified_count` |
| CC-06 | Every generated `.py` AST-parses cleanly | `ast.parse` over all `.py` | `test_all_py_parse` |
| CC-07 | No generated function exceeds 50 LOC in `app/` | AST walk, `max_loc <= 50` | `test_no_function_over_50_loc` |
| CC-08 | `CANARY_ENABLED` and `CANARY_ALERT_WEBHOOK_URL` inside `class Settings` | String scan + indent | `test_config_fields_patched` |
| CC-10 | Canary router registered in `app/routes/__init__.py` | `"canary"` in content | `test_routes_init_patched` |
| CC-11 | `registry.py` has `CanaryRegistry`, `CanaryToken`, `register` | All three tokens | `test_canary_registry_created` |
| CC-12 | 5 tokens pre-registered: honeypot×3, credential×1, decoy_record×1 | `_registry.register(...)` calls counted | `test_preregistered_tokens` |
| CC-13 | `CanaryToken` has `fingerprint` (sha256[:16]) | `"fingerprint"` in registry source | `test_fingerprint_property` |
| CC-14 | `alerter.py` has `fire_canary_alert` and `build_request_context` | Both names in file | `test_alerter_created` |
| CC-15 | `alerter.py` catches all exceptions in alert path (`BLE001`) | `except Exception` in alerter | `test_alerter_never_raises` |
| CC-16 | `build_request_context` masks `authorization` and `cookie` with `***` | Both keys + `***` in alerter | `test_header_masking` |
| CC-17 | Honeypot routes `/internal/config`, `/admin/backup`, `/debug/env` present | All three paths in honeypot file | `test_honeypot_paths` |
| CC-18 | Honeypot handlers return `_FAKE_*` dicts — no `raise HTTPException` | `"raise HTTPException"` absent; `_FAKE` present | `test_honeypot_returns_200` |
| CC-19 | `fake_credentials.py` has `CANARY_AWS_ACCESS_KEY_ID` and `CANARY_DATABASE_URL` | Both names in file | `test_fake_credentials_module` |
| QS-02 | Credential values are placeholders only | Check for `EXAMPLE` / `example` (not real) | `test_placeholder_values` |
| CC-20 | `decoy_seeder.py` has `seed_decoy_records` and `is_canary_email` | Both names in file | `test_decoy_seeder_created` |
| CC-21 | Decoy seeder catches exceptions | `except Exception` in `decoy_seeder.py` | `test_decoy_seeder_safe` |
| QS-04 | `httpx` not imported at module level | Top-level import scan | `test_httpx_not_top_level` |
| CC-N-1 | `execution_time_ms` is a positive integer | `result.execution_time_ms > 0` | `test_execution_time_recorded` |
| CC-N | `next_steps` mentions `webhook` or `canary` | Token in lowercased join | `test_next_steps_present` |
| CC-LAST | Two runs leave the project AST-parseable | `ast.parse` after two runs | `test_idempotent_project_still_parses` |
| QS-03 | No TODO/FIXME/HACK comments | Scan all generated `.py` | `test_no_todo_fixme_hack` |

---

## 7. Definition of Done (DoD)

- [ ] All 26 Completeness Criteria verified by `test_add_canary_tokens.py`
- [ ] `add_canary_tokens.py` runs `ast.parse` on every created `.py` before returning success
- [ ] Fingerprint `"class CanaryRegistry" in registry.py` triggers `status="no_op"`
- [ ] `dry_run=True` returns success with empty `files_created`/`files_modified`
- [ ] 5 tokens pre-registered in `registry.py` (3 honeypot + 1 credential + 1 decoy_record)
- [ ] Honeypot handlers return `_FAKE_*` dicts — no `raise HTTPException` anywhere
- [ ] `fire_canary_alert` catches all exceptions; webhook failure never propagates
- [ ] `httpx` imported lazily inside `_post_webhook` body only
- [ ] `build_request_context` masks `authorization` and `cookie` headers with `***`
- [ ] `seed_decoy_records` uses `ON CONFLICT DO NOTHING` and catches all exceptions
- [ ] `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30`
- [ ] `execution_time_ms` set on every return path
- [ ] `MCP_TOOL` descriptor exposes `{name, description, tags, entry}` quartet

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-CT-01 | Tool is ALWAYS idempotent | `"class CanaryRegistry" in registry.py` → `no_op` | `test_idempotent` |
| INV-CT-02 | `dry_run=True` NEVER writes to disk | Early return before write | `test_dry_run` |
| INV-CT-03 | Every generated `.py` MUST parse | `ast.parse` loop | `test_all_py_parse` |
| INV-CT-04 | Honeypots MUST return HTTP 200 — NEVER raise | No `raise HTTPException` in `canary_honeypot.py` | `test_honeypot_returns_200` |
| INV-CT-05 | Alert MUST never raise — fire-and-forget | `except Exception: pass` in alerter | `test_alerter_never_raises` |
| INV-CT-06 | `httpx` MUST NOT be at module level | Lazy import inside `_post_webhook` | `test_httpx_not_top_level` |
| INV-CT-07 | Auth/Cookie headers MUST be masked | `authorization` → `***` in `build_request_context` | `test_header_masking` |
| INV-CT-08 | `CanaryToken.fingerprint` MUST use sha256[:16] | `hashlib.sha256(...)[:16]` in `registry.py` | `test_fingerprint_property` |
| INV-CT-09 | `CANARY_*` MUST be inside `class Settings` | `_patch_config` anchor | `test_config_fields_patched` |
| INV-CT-10 | `ToolResult.execution_time_ms` MUST be positive | `_elapsed_ms(start)` on all branches | `test_execution_time_recorded` |

---

## 9. User Stories

### 9.1 Core install flow (US-01 .. US-05)

**US-01: Install canary tokens into a clean FastAPI project**
- **As a** security engineer
- **I want** one tool call to add honeypots and decoy records
- **So that** intrusion attempts trigger alerts before real damage
- **Given:** A FastAPI project with `app/core/config.py`
- **When:** `add_canary_tokens(ToolInput(project_dir=...))`
- **Then:**
  - Returns `ToolResult.status == "success"` (CC-01)
  - ≥ 4 files created (CC-04)
  - Verified by `test_success_status`, `test_files_created_count`

**US-02: Re-run safely**
- **As a** CI job
- **I want** `status="no_op"` on second run
- **Given:** `class CanaryRegistry` already in `registry.py`
- **When:** Tool invoked again
- **Then:** `r2.status == "no_op"` — verified by `test_idempotent`

**US-03: Dry-run preview**
- **Given:** Fresh project
- **When:** `add_canary_tokens(ToolInput(project_dir=..., dry_run=True))`
- **Then:** Zero filesystem changes — verified by `test_dry_run`

**US-04: Config fields are env-var overridable**
- **As a** platform engineer
- **I want** `CANARY_ENABLED` and `CANARY_ALERT_WEBHOOK_URL` in `Settings`
- **When:** Tool runs
- **Then:** Fields inside class body — verified by `test_config_fields_patched`

**US-05: Generated code is auditable**
- **As a** security reviewer
- **I want** all functions ≤ 50 LOC
- **Given:** Tool emitted all 5 files
- **When:** AST walk over `app/`
- **Then:** `max_loc <= 50` — verified by `test_no_function_over_50_loc`

### 9.2 Canary logic (US-06 .. US-10)

**US-06: Honeypot returns 200 to fool attackers**
- **As an** attacker probing for honeypots
- **I want** to see errors or unusual status codes
- **Given:** Honeypot endpoints installed
- **When:** `GET /internal/config` (no auth headers)
- **Then:** HTTP 200 with plausible JSON — attacker has no signal

**US-07: Alert fires on honeypot access**
- **As a** security operations team
- **I want** a webhook alert when `/admin/backup` is accessed
- **Given:** `CANARY_ALERT_WEBHOOK_URL` set in env
- **When:** `GET /admin/backup`
- **Then:** `fire_canary_alert("honeypot_backup", ...)` called; webhook POST fired

**US-08: Alert failure never breaks response**
- **As a** product user
- **I want** the API to work even if the SIEM is down
- **Given:** Webhook URL unreachable
- **When:** Honeypot triggered
- **Then:** HTTP 200 still returned; exception swallowed (INV-CT-05)

**US-09: Detect access to decoy admin accounts**
- **As a** security analyst
- **I want** to know when `canary-admin-1@example-canary.com` logs in
- **Given:** `is_canary_email(email)` in `decoy_seeder.py`
- **When:** Login attempt with canary email
- **Then:** `is_canary_email(email) == True`; trigger alert

**US-10: Fingerprint uniquely identifies each token**
- **As a** SIEM
- **I want** a stable 16-char ID per canary token
- **Given:** `CanaryToken.fingerprint` computed as sha256[:16]
- **When:** Same name + type
- **Then:** Fingerprint is deterministic — verified by CC-13

### 9.3 Integration (US-11 .. US-13)

**US-11: Routes init updated**
- **As a** FastAPI developer
- **I want** canary router registered
- **Given:** `app/routes/__init__.py` exists
- **When:** Tool runs
- **Then:** `"canary"` in `routes/__init__.py` — verified by CC-10

**US-12: Project parseable after two runs**
- **Given:** Tool applied twice
- **When:** `ast.parse` over all `.py`
- **Then:** Zero errors — verified by CC-LAST

**US-13: No TODO/FIXME/HACK in generated files**
- **Given:** Canary system installed
- **When:** Scan for `TODO`/`FIXME`/`HACK`
- **Then:** Zero occurrences — verified by QS-03

---

## 10. Error Handling

| Scenario | Behaviour | Status |
|----------|-----------|--------|
| `project_dir` does not exist | Returns `status="error"` | `"error"` |
| `app/core/config.py` absent | `ensure_prerequisites` raises | `"error"` |
| Webhook unreachable | `_post_webhook` catches exception silently | Silent |
| DB unavailable at decoy seed | `seed_decoy_records` catches exception | Silent |

---

## 11. Dependencies

| Package | Why needed |
|---------|------------|
| `hashlib` (stdlib) | SHA-256 fingerprint on `CanaryToken` |
| `asyncio` (stdlib) | `ensure_future` for fire-and-forget alert |
| `httpx` (lazy) | Webhook POST inside `_post_webhook` |
| `pydantic-settings` | `Settings` in target project |
| `SQLAlchemy 2.0` (optional) | Decoy record seeding |

`httpx` must already be in `requirements.txt` or is added if absent. Import is lazy.

---

## 12. Security Considerations

| Concern | Mitigation |
|---------|-----------|
| Honeypot detection by attacker | Routes return HTTP 200 with plausible data — no 4xx/5xx tells |
| Auth headers in alert payload | `build_request_context` masks `authorization`/`cookie`/`x-api-key` with `***` |
| Fake credentials look real | Placeholder values use `EXAMPLE` suffix; never real AWS keys |
| Decoy users in DB | `is_canary_email` allows quick identification at login time |

---

## 13. Observability

| Signal | Where |
|--------|-------|
| `execution_time_ms` | `ToolResult.execution_time_ms` |
| Canary triggered | Webhook POST + `logger.warning` |
| Missing webhook URL | `logger.warning("CANARY_ALERT_WEBHOOK_URL not set")` |
| Decoy login | `is_canary_email(email)` check at auth layer |

---

## 14. Configuration Reference

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `CANARY_ENABLED` | `bool` | `True` | Master switch; when False all canary logic is skipped |
| `CANARY_ALERT_WEBHOOK_URL` | `str` | `""` | Webhook URL to POST when a canary fires; leave empty to log-only |

---

## 15. Migration / Rollback

**Rollback is mechanical:**
- Delete `app/core/canary/` (4 files)
- Delete `app/api/routes/canary_honeypot.py`
- Remove `CANARY_*` from `app/core/config.py`
- Remove canary router from `app/routes/__init__.py`
- Delete decoy DB records if seeded

No schema migrations. No new tables unless decoy_seeder uses existing `users` table.

---

## 16. Test File Reference

**Location:** `adapt/extend/infrastructure/test_add_canary_tokens.py`

**Test runner:**
```bash
PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_canary_tokens.py -v
# or standalone:
PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_canary_tokens.py
```

**Full test inventory:**

| Test function | CC ID | What it asserts |
|---------------|-------|-----------------|
| `test_success_status` | CC-01 | `result.status == "success"` on fresh project |
| `test_idempotent` | CC-02 | Second run → `status="no_op"`, no file ops |
| `test_dry_run` | CC-03 | `dry_run=True` → zero filesystem changes |
| `test_files_created_count` | CC-04 | `len(files_created) >= 4`, all paths exist |
| `test_files_modified_count` | CC-05 | `len(files_modified) >= 1`, all paths exist |
| `test_all_py_parse` | CC-06 | All generated `.py` pass `ast.parse` |
| `test_no_function_over_50_loc` | CC-07 | No function in `app/` exceeds 50 LOC |
| `test_config_fields_patched` | CC-08 | `CANARY_ENABLED` inside `class Settings` |
| `test_routes_init_patched` | CC-10 | `"canary"` in `routes/__init__.py` |
| `test_canary_registry_created` | CC-11 | `CanaryRegistry`, `CanaryToken`, `register` in `registry.py` |
| `test_preregistered_tokens` | CC-12 | 5 pre-registered tokens (honeypot×3, credential, decoy_record) |
| `test_fingerprint_property` | CC-13 | `fingerprint` present in registry source |
| `test_alerter_created` | CC-14 | `fire_canary_alert` + `build_request_context` in `alerter.py` |
| `test_alerter_never_raises` | CC-15 | `except Exception` in alerter (BLE001) |
| `test_header_masking` | CC-16 | `authorization` + `***` masking in `build_request_context` |
| `test_honeypot_paths` | CC-17 | `/internal/config`, `/admin/backup`, `/debug/env` in honeypot file |
| `test_honeypot_returns_200` | CC-18 | `_FAKE` present; `raise HTTPException` absent |
| `test_fake_credentials_module` | CC-19 | `CANARY_AWS_ACCESS_KEY_ID` + `CANARY_DATABASE_URL` in file |
| `test_placeholder_values` | QS-02 | Placeholder values contain `EXAMPLE` or `example` |
| `test_decoy_seeder_created` | CC-20 | `seed_decoy_records` + `is_canary_email` in `decoy_seeder.py` |
| `test_decoy_seeder_safe` | CC-21 | `except Exception` in `decoy_seeder.py` |
| `test_httpx_not_top_level` | QS-04 | No module-level `httpx` import |
| `test_execution_time_recorded` | CC-N-1 | `execution_time_ms > 0` |
| `test_next_steps_present` | CC-N | `next_steps` mentions `webhook` or `canary` |
| `test_idempotent_project_still_parses` | CC-LAST | Two runs → all `.py` still parse |
| `test_no_todo_fixme_hack` | QS-03 | No `TODO`/`FIXME`/`HACK` in generated files |
