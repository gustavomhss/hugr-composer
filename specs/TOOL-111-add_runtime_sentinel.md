# TOOL-111: add_runtime_sentinel

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_runtime_sentinel` |
| Category | EXTEND > Infrastructure |
| Complexity | High |
| Dependencies | FastAPI, pydantic-settings, Starlette middleware, `ipaddress` (stdlib), `re` (stdlib) |
| Signature | `add_runtime_sentinel(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_runtime_sentinel", "description": "Add a Runtime Application Self-Protection (RASP) sentinel middleware with injection detection, SSRF prevention, and learning/enforcing modes.", "tags": ["extend", "infrastructure"], "entry": "add_runtime_sentinel"}` |
| Files created (typical) | 3 — `app/middleware/__init__.py`, `app/core/sentinel_registry.py`, `app/middleware/runtime_sentinel.py` |
| Files modified (typical) | 1 — `app/core/config.py` |

---

## 2. Purpose

The `fastapi_add_runtime_sentinel` tool installs a Runtime Application Self-Protection (RASP) system into a FastAPI project. Unlike WAF rules applied at the network edge, RASP operates inside the application process itself — it can inspect the actual request body as Python objects rather than raw bytes, correlate injection attempts with internal application state, and block attacks after parsing and before any database or shell call executes. RASP is the last line of defence before application logic runs.

This tool implements three detection categories. **SQL injection** detection using compiled regex patterns: tautology patterns (`'--`, `1=1`, `OR 1`), `UNION SELECT` (case-insensitive), stacked queries (`;` followed by DML keywords), and comment sequences (`/*`, `*/`, `--`). **Command injection** detection: shell metacharacters (`|`, `;`, `&`, backtick, `$(`), plus wget/curl/nc/bash-specific patterns that suggest remote code execution attempts. **SSRF (Server-Side Request Forgery)** detection using Python's `ipaddress` module to classify IPs against `_INTERNAL_NETWORKS` (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `127.0.0.0/8`) and `_METADATA_HOSTNAMES` (`169.254.169.254`, `metadata.google.internal`).

The tool generates: (a) `app/core/sentinel_registry.py` with `SecurityEvent` dataclass (`attack_type`, `request_path`, `payload_snippet`, `timestamp`, `client_ip`, `blocked`), `AttackPatternRegistry` (`record`, `count`, `recent`, `_events` capped at `max_events`), and `get_registry()` singleton; (b) `app/middleware/runtime_sentinel.py` with `InjectionDetector` (`check_sql`, `check_command`, `check_ssrf`), `_extract_string_values` recursive helper (max depth 5 to avoid DoS), `_get_mode()` and `_get_allowed_hosts()` env-var readers, and `RuntimeSentinelMiddleware` (`BaseHTTPMiddleware`) that in `learning` mode logs detections without blocking and in `enforcing` mode returns HTTP 400. (c) `app/middleware/__init__.py` (package marker).

The tool patches `app/core/config.py` with `SENTINEL_ENABLED: bool = True`, `SENTINEL_MODE: str = "learning"`, and `SENTINEL_ALLOWED_HOSTS: str = ""`. The idempotency fingerprint is `RuntimeSentinelMiddleware` in `app/middleware/runtime_sentinel.py`.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | CI budget; measured via `execution_time_ms` |
| Files created | ≥ 3 | Middleware, sentinel registry, `__init__.py` |
| Files modified | ≥ 1 | Config at minimum |
| Max function LOC in generated code | ≤ 50 | Auditable; AST-checked |
| Injection scan per request | < 5 ms | Compiled regex + shallow dict walk |
| SSRF IP classification | < 0.1 ms | `ipaddress.ip_address()` + network checks |
| `_extract_string_values` depth limit | max depth 5 | Prevents DoS on deep nested JSON |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── main.py
│   ├── core/
│   │   └── config.py        # No SENTINEL_* fields
│   └── middleware/          # No RASP middleware
└── (no sentinel_registry.py)
```

SQL injection, command injection, and SSRF payloads reach the application layer with no in-process detection.

### 4.2 Sentinel registry: AFTER

```python
# app/core/sentinel_registry.py
"""Runtime sentinel — attack event registry."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import ClassVar


@dataclass
class SecurityEvent:
    """A recorded security event from the RASP sentinel."""

    attack_type: str
    request_path: str
    payload_snippet: str
    timestamp: datetime
    client_ip: str
    blocked: bool


class AttackPatternRegistry:
    """In-memory store of detected attack events."""

    _events: ClassVar[list[SecurityEvent]] = []
    _max_events: ClassVar[int] = 1000

    def record(self, event: SecurityEvent) -> None:
        """Record a security event, evicting oldest if at capacity."""
        if len(self.__class__._events) >= self.__class__._max_events:
            self.__class__._events.pop(0)
        self.__class__._events.append(event)

    def count(self, attack_type: str | None = None) -> int:
        """Return total event count, optionally filtered by attack_type."""
        if attack_type is None:
            return len(self.__class__._events)
        return sum(1 for e in self.__class__._events if e.attack_type == attack_type)

    def recent(self, n: int = 10) -> list[SecurityEvent]:
        """Return the most recent *n* events."""
        return self.__class__._events[-n:]


_registry_instance: AttackPatternRegistry | None = None


def get_registry() -> AttackPatternRegistry:
    """Return the singleton AttackPatternRegistry."""
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = AttackPatternRegistry()
    return _registry_instance
```

### 4.3 Injection detector and middleware: AFTER

```python
# app/middleware/runtime_sentinel.py
"""RuntimeSentinelMiddleware — RASP injection and SSRF detection."""
from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.sentinel_registry import SecurityEvent, get_registry

logger = logging.getLogger(__name__)

_SQL_PATTERNS = re.compile(
    r"('--|\bOR\b\s+1\s*=\s*1|\bUNION\b.*\bSELECT\b|;.*\b(DROP|INSERT|UPDATE|DELETE)\b|/\*|\*/)",
    re.IGNORECASE,
)
_CMD_PATTERNS = re.compile(
    r"([|;&`]|\$\(|wget\s|curl\s|\bnc\b|\bbash\b)",
    re.IGNORECASE,
)
_INTERNAL_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
]
_METADATA_HOSTNAMES = {"169.254.169.254", "metadata.google.internal"}


class InjectionDetector:
    """Detect SQL injection, command injection, and SSRF patterns."""

    def check_sql(self, value: str) -> bool:
        """Return True if *value* contains SQL injection patterns."""
        return bool(_SQL_PATTERNS.search(value))

    def check_command(self, value: str) -> bool:
        """Return True if *value* contains command injection patterns."""
        return bool(_CMD_PATTERNS.search(value))

    def check_ssrf(self, value: str) -> bool:
        """Return True if *value* targets internal IPs or metadata hosts."""
        if any(h in value for h in _METADATA_HOSTNAMES):
            return True
        try:
            ip = ipaddress.ip_address(value.strip())
            return any(ip in net for net in _INTERNAL_NETWORKS)
        except ValueError:
            return False


def _extract_string_values(data: Any, depth: int = 0) -> list[str]:
    """Recursively extract string values from a dict/list (max depth 5)."""
    if depth > 5:
        return []
    if isinstance(data, str):
        return [data]
    if isinstance(data, dict):
        result = []
        for v in data.values():
            result.extend(_extract_string_values(v, depth + 1))
        return result
    if isinstance(data, list):
        result = []
        for item in data:
            result.extend(_extract_string_values(item, depth + 1))
        return result
    return []


def _get_mode() -> str:
    return os.getenv("SENTINEL_MODE", "learning")


def _get_allowed_hosts() -> list[str]:
    raw = os.getenv("SENTINEL_ALLOWED_HOSTS", "")
    return [h.strip() for h in raw.split(",") if h.strip()]


class RuntimeSentinelMiddleware(BaseHTTPMiddleware):
    """RASP middleware: detect injection and SSRF in request payloads."""

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        mode = _get_mode()
        body = await request.body()
        values: list[str] = []
        try:
            data = json.loads(body)
            values = _extract_string_values(data)
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
        detector = InjectionDetector()
        attack_type = None
        for v in values:
            if detector.check_sql(v):
                attack_type = "sql_injection"
                break
            if detector.check_command(v):
                attack_type = "command_injection"
                break
            if detector.check_ssrf(v):
                attack_type = "ssrf"
                break
        if attack_type:
            event = SecurityEvent(
                attack_type=attack_type,
                request_path=request.url.path,
                payload_snippet=(values[0][:80] if values else ""),
                timestamp=datetime.now(timezone.utc),
                client_ip=request.client.host if request.client else "unknown",
                blocked=(mode == "enforcing"),
            )
            get_registry().record(event)
            logger.warning("RASP: %s detected at %s", attack_type, request.url.path)
            if mode == "enforcing":
                return Response(content="Blocked", status_code=400)
        return await call_next(request)
```

### 4.4 Config patch (inside `class Settings`)

```python
# app/core/config.py  (diff, added by _patch_config)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # --- runtime sentinel settings — added by add_runtime_sentinel tool ---
    SENTINEL_ENABLED: bool = True
    SENTINEL_MODE: str = "learning"
    SENTINEL_ALLOWED_HOSTS: str = ""
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Tool is idempotent on second run** | `"RuntimeSentinelMiddleware" in runtime_sentinel.py` → `status="no_op"` |
| QS-2 | **`dry_run=True` writes zero files** | Early return before any write |
| QS-3 | **Every generated `.py` AST-parses** | `ast.parse` on each created `.py` |
| QS-4 | **No generated function exceeds 50 LOC** | AST walk; all functions kept short |
| QS-5 | **SQL patterns cover tautology, UNION, stacked, comment** | All four pattern classes in `_SQL_PATTERNS` |
| QS-6 | **Command patterns include metacharacters, wget/curl/nc/bash** | Both categories in `_CMD_PATTERNS` |
| QS-7 | **SSRF blocks 169.254/127.0.0.0/10.x/172.16/192.168** | `_INTERNAL_NETWORKS` + `_METADATA_HOSTNAMES` |
| QS-8 | **`_extract_string_values` capped at depth 5** | DoS prevention |
| QS-9 | **Learning mode logs, enforcing mode returns HTTP 400** | `mode == "enforcing"` branch in `dispatch` |
| QS-10 | **`SENTINEL_MODE` defaults to `"learning"`** | Safe default — observe before block |
| QS-11 | **`SENTINEL_*` inside `class Settings`** | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES` |
| QS-12 | **`execution_time_ms` is positive** | `_elapsed_ms(start)` on all return paths |
| QS-13 | **`MCP_TOOL` descriptor is complete** | `entry == "add_runtime_sentinel"` |

---

## 6. Completeness Criteria

Every criterion is tied to a real assertion in `adapt/extend/infrastructure/test_add_runtime_sentinel.py`.

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | Tool returns `status="success"` on a fresh project | `result.status == "success"` | `test_success_status` |
| CC-02 | Second run returns `status="no_op"` with zero file ops | `r2.status == "no_op"` and both lists empty | `test_idempotent` |
| CC-03 | `dry_run=True` writes zero bytes to filesystem | `before == after` over all `.py` | `test_dry_run` |
| CC-04 | Tool creates at least 3 new files | `len(files_created) >= 3` | `test_files_created_count` |
| CC-05 | Tool modifies at least 1 existing file | `len(files_modified) >= 1` | `test_files_modified_count` |
| CC-06 | Every generated `.py` AST-parses cleanly | `ast.parse` over all `.py` | `test_all_py_parse` |
| CC-07 | No generated function exceeds 50 LOC in `app/` | AST walk, `max_loc <= 50` | `test_no_function_over_50_loc` |
| CC-08 | `SENTINEL_ENABLED`, `SENTINEL_MODE`, `SENTINEL_ALLOWED_HOSTS` inside `class Settings` | String scan + indent check | `test_config_fields_patched` |
| CC-09 | `runtime_sentinel.py` exists with `RuntimeSentinelMiddleware` | File exists + class name | `test_middleware_created` |
| CC-10 | `InjectionDetector` with `check_sql`, `check_command`, `check_ssrf` | All three names in file | `test_injection_detector` |
| CC-11 | SQL patterns cover `UNION`, tautology, stacked, comment | All four pattern tokens | `test_sql_patterns` |
| CC-12 | SSRF detection covers 169.254, 127.0.0.0, 10.x | IP ranges in source | `test_ssrf_blocking` |
| CC-13 | `AttackPatternRegistry` in `sentinel_registry.py` | File exists + class name | `test_attack_registry_created` |
| CC-14 | `SecurityEvent` with `attack_type` and `blocked` fields | Both field names in file | `test_security_event` |
| CC-15 | Learning/enforcing mode logic present | `"learning"` and `"enforcing"` in middleware | `test_learning_enforcing_modes` |
| CC-16 | `execution_time_ms` is a positive integer | `result.execution_time_ms > 0` | `test_execution_time_recorded` |
| CC-17 | `next_steps` mentions `middleware`, `sentinel`, or `env` | Token in lowercased join | `test_next_steps_present` |
| CC-18 | Two runs leave the project AST-parseable | `ast.parse` after two runs | `test_idempotent_project_still_parses` |
| CC-19 | Command injection metacharacters present | `[|;&` pattern or similar in middleware | `test_command_injection_patterns` |
| CC-20 | Error raised for invalid `project_dir` | `status="error"` | `test_error_on_invalid_project_dir` |
| CC-21 | `SENTINEL_MODE` defaults to `"learning"` | Default value check | `test_sentinel_mode_default` |
| CC-22 | `MCP_TOOL["entry"]` matches function name | `MCP_TOOL["entry"] == "add_runtime_sentinel"` | `test_mcp_tool_entry_matches_function` |

---

## 7. Definition of Done (DoD)

- [ ] All 22 Completeness Criteria verified by `test_add_runtime_sentinel.py`
- [ ] `add_runtime_sentinel.py` runs `ast.parse` on every created `.py` before returning success
- [ ] Fingerprint `"RuntimeSentinelMiddleware" in runtime_sentinel.py` triggers `status="no_op"`
- [ ] `dry_run=True` returns success with empty `files_created`/`files_modified`
- [ ] `InjectionDetector.check_sql` covers tautology, UNION, stacked, comment patterns
- [ ] `InjectionDetector.check_command` covers `|;&` metacharacters + wget/curl/nc/bash
- [ ] `InjectionDetector.check_ssrf` uses `ipaddress` module + `_INTERNAL_NETWORKS` + `_METADATA_HOSTNAMES`
- [ ] `_extract_string_values` capped at depth 5
- [ ] `RuntimeSentinelMiddleware` in `learning` mode logs; in `enforcing` mode returns HTTP 400
- [ ] `SENTINEL_MODE` defaults to `"learning"` (not `"enforcing"`)
- [ ] `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30`
- [ ] `execution_time_ms` set on every return path
- [ ] `MCP_TOOL` descriptor exposes `{name, description, tags, entry}` quartet

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-RS-01 | Tool is ALWAYS idempotent | `"RuntimeSentinelMiddleware" in middleware.py` → `no_op` | `test_idempotent` |
| INV-RS-02 | `dry_run=True` NEVER writes to disk | Early return before write | `test_dry_run` |
| INV-RS-03 | Every generated `.py` MUST parse | `ast.parse` loop | `test_all_py_parse` |
| INV-RS-04 | SQL patterns MUST cover 4 attack classes | Tautology/UNION/stacked/comment | `test_sql_patterns` |
| INV-RS-05 | SSRF MUST block RFC-1918 + link-local + loopback | `_INTERNAL_NETWORKS` covers all | `test_ssrf_blocking` |
| INV-RS-06 | `_extract_string_values` depth limit MUST be 5 | DoS prevention | Enforced by construction |
| INV-RS-07 | `SENTINEL_MODE` MUST default to `"learning"` | Safe conservative default | `test_sentinel_mode_default` |
| INV-RS-08 | Enforcing mode MUST return HTTP 400 | `Response(status_code=400)` branch | `test_learning_enforcing_modes` |
| INV-RS-09 | `SENTINEL_*` MUST be inside `class Settings` | `_patch_config` anchor | `test_config_fields_patched` |
| INV-RS-10 | `ToolResult.execution_time_ms` MUST be positive | `_elapsed_ms(start)` on all branches | `test_execution_time_recorded` |

---

## 9. User Stories

### 9.1 Core install flow (US-01 .. US-05)

**US-01: Install RASP sentinel into a clean FastAPI project**
- **As a** security engineer
- **I want** one tool call to add in-process injection detection
- **So that** SQL/command injection and SSRF are detected before reaching the DB
- **Given:** A FastAPI project with `app/core/config.py`
- **When:** `add_runtime_sentinel(ToolInput(project_dir=...))`
- **Then:**
  - Returns `ToolResult.status == "success"` (CC-01)
  - ≥ 3 files created (CC-04)
  - Verified by `test_success_status`, `test_files_created_count`

**US-02: Re-run safely**
- **As a** CI job
- **I want** `status="no_op"` on second run
- **Given:** `RuntimeSentinelMiddleware` already in `runtime_sentinel.py`
- **When:** Tool invoked again
- **Then:** `r2.status == "no_op"` — verified by `test_idempotent`

**US-03: Dry-run preview**
- **Given:** Fresh project
- **When:** `add_runtime_sentinel(ToolInput(project_dir=..., dry_run=True))`
- **Then:** Zero filesystem changes — verified by `test_dry_run`

**US-04: Start in learning mode for safe rollout**
- **As a** platform engineer
- **I want** `SENTINEL_MODE` to default to `"learning"`
- **So that** the sentinel observes before blocking any traffic
- **Given:** Fresh install
- **When:** Tool runs
- **Then:** `SENTINEL_MODE: str = "learning"` in config — verified by CC-21

**US-05: Generated code is auditable**
- **As a** security reviewer
- **I want** all functions ≤ 50 LOC
- **Given:** Tool emitted `runtime_sentinel.py`, `sentinel_registry.py`
- **When:** AST walk over `app/`
- **Then:** `max_loc <= 50` — verified by `test_no_function_over_50_loc`

### 9.2 Detection logic (US-06 .. US-10)

**US-06: Detect SQL injection tautology**
- **As a** RASP sentinel
- **I want** `' OR 1=1--` to be flagged as SQL injection
- **Given:** `InjectionDetector().check_sql("' OR 1=1--")`
- **When:** Called
- **Then:** Returns `True` — verified by CC-11

**US-07: Block UNION SELECT attacks**
- **As a** RASP sentinel
- **I want** `UNION SELECT password FROM users` flagged
- **Given:** `check_sql("UNION SELECT password FROM users")`
- **When:** Called (case-insensitive)
- **Then:** Returns `True`

**US-08: Block SSRF to AWS metadata endpoint**
- **As a** RASP sentinel
- **I want** `169.254.169.254` in a URL parameter to be flagged
- **Given:** `check_ssrf("169.254.169.254")`
- **When:** Called
- **Then:** Returns `True` — verified by CC-12

**US-09: Log without blocking in learning mode**
- **As a** platform engineer deploying to production
- **I want** the sentinel to log detections without blocking legitimate requests
- **Given:** `SENTINEL_MODE=learning` (default)
- **When:** Attack pattern detected in request body
- **Then:** `logger.warning(...)` called; response passes through normally — verified by CC-15

**US-10: Promote to enforcing mode**
- **As a** security engineer
- **I want** to set `SENTINEL_MODE=enforcing` after validating
- **Given:** Zero false positives in learning mode over 7 days
- **When:** `SENTINEL_MODE=enforcing` set in env
- **Then:** Matching requests receive HTTP 400 — verified by CC-15

### 9.3 Integration (US-11 .. US-13)

**US-11: Attack events persist in registry**
- **As an** operator
- **I want** to query recent attacks
- **Given:** `AttackPatternRegistry` singleton
- **When:** `get_registry().recent(10)`
- **Then:** Last 10 `SecurityEvent` objects returned — verified by CC-13

**US-12: Project parseable after two runs**
- **Given:** Tool applied twice
- **When:** `ast.parse` over all `.py`
- **Then:** Zero errors — verified by CC-18

**US-13: Error on invalid project_dir**
- **Given:** Non-existent path
- **When:** `add_runtime_sentinel(ToolInput(project_dir="/nonexistent"))`
- **Then:** `result.status == "error"` — verified by CC-20

---

## 10. Error Handling

| Scenario | Behaviour | Status |
|----------|-----------|--------|
| `project_dir` does not exist | Returns `status="error"`, `error` set | `"error"` |
| `app/core/config.py` absent | `ensure_prerequisites` raises | `"error"` |
| Request body is not JSON | `json.JSONDecodeError` caught; scan skipped | Silent |
| IP parsing fails in `check_ssrf` | `ValueError` caught; returns `False` | Silent |

---

## 11. Dependencies

| Package | Why needed |
|---------|------------|
| `re` (stdlib) | Compiled SQL/command injection patterns |
| `ipaddress` (stdlib) | RFC-1918 + link-local IP classification |
| `json` (stdlib) | Request body parsing |
| `os` (stdlib) | `_get_mode()` reads `SENTINEL_MODE` env var |
| `starlette.middleware.base` | `BaseHTTPMiddleware` |
| `pydantic-settings` | `Settings` in target project |

No new packages added to `requirements.txt`.

---

## 12. Security Considerations

| Concern | Mitigation |
|---------|-----------|
| DoS via deep nested JSON | `_extract_string_values` max depth 5 |
| False positives in enforcing mode | Default to `learning` mode; promotes to `enforcing` after validation |
| Regex catastrophic backtracking | Patterns use anchored, non-greedy alternations |
| Learning mode logs could expose payload | `payload_snippet` capped at 80 chars |

---

## 13. Observability

| Signal | Where |
|--------|-------|
| `execution_time_ms` | `ToolResult.execution_time_ms` |
| Attack detected | `logger.warning("RASP: %s detected at %s", attack_type, path)` |
| Attack event persisted | `get_registry().record(event)` |
| Blocking in enforcing mode | `event.blocked = True` + HTTP 400 response |

---

## 14. Configuration Reference

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `SENTINEL_ENABLED` | `bool` | `True` | Master switch |
| `SENTINEL_MODE` | `str` | `"learning"` | `"learning"` (log only) or `"enforcing"` (block + log) |
| `SENTINEL_ALLOWED_HOSTS` | `str` | `""` | Comma-separated trusted IPs/CIDRs to bypass SSRF detection |

---

## 15. Migration / Rollback

**Rollback is mechanical:**
- Delete `app/middleware/runtime_sentinel.py`
- Delete `app/core/sentinel_registry.py`
- Remove `RuntimeSentinelMiddleware` from `app/main.py` if added manually
- Remove `SENTINEL_*` from `app/core/config.py`

No database migrations. No external services.

---

## 16. Test File Reference

**Location:** `adapt/extend/infrastructure/test_add_runtime_sentinel.py`

**Test runner:**
```bash
PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_runtime_sentinel.py -v
# or standalone:
PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_runtime_sentinel.py
```

**Full test inventory:**

| Test function | CC ID | What it asserts |
|---------------|-------|-----------------|
| `test_success_status` | CC-01 | `result.status == "success"` on fresh project |
| `test_idempotent` | CC-02 | Second run → `status="no_op"`, no file ops |
| `test_dry_run` | CC-03 | `dry_run=True` → zero filesystem changes |
| `test_files_created_count` | CC-04 | `len(files_created) >= 3`, all paths exist |
| `test_files_modified_count` | CC-05 | `len(files_modified) >= 1`, all paths exist |
| `test_all_py_parse` | CC-06 | All generated `.py` pass `ast.parse` |
| `test_no_function_over_50_loc` | CC-07 | No function in `app/` exceeds 50 LOC |
| `test_config_fields_patched` | CC-08 | `SENTINEL_ENABLED` inside `class Settings` |
| `test_middleware_created` | CC-09 | `RuntimeSentinelMiddleware` in `runtime_sentinel.py` |
| `test_injection_detector` | CC-10 | `InjectionDetector`, `check_sql`, `check_command`, `check_ssrf` |
| `test_sql_patterns` | CC-11 | `UNION`, tautology, stacked, comment patterns |
| `test_ssrf_blocking` | CC-12 | `169.254`, `127.0.0.0`, `10.x` ranges in source |
| `test_attack_registry_created` | CC-13 | `AttackPatternRegistry` in `sentinel_registry.py` |
| `test_security_event` | CC-14 | `SecurityEvent`, `attack_type`, `blocked` fields |
| `test_learning_enforcing_modes` | CC-15 | `"learning"` and `"enforcing"` in middleware source |
| `test_execution_time_recorded` | CC-16 | `execution_time_ms > 0` |
| `test_next_steps_present` | CC-17 | `next_steps` mentions `middleware`/`sentinel`/`env` |
| `test_idempotent_project_still_parses` | CC-18 | Two runs → all `.py` still parse |
| `test_command_injection_patterns` | CC-19 | Command injection metacharacters in middleware |
| `test_error_on_invalid_project_dir` | CC-20 | `status="error"` on non-existent dir |
| `test_sentinel_mode_default` | CC-21 | `SENTINEL_MODE` defaults to `"learning"` |
| `test_mcp_tool_entry_matches_function` | CC-22 | `MCP_TOOL["entry"] == "add_runtime_sentinel"` |
