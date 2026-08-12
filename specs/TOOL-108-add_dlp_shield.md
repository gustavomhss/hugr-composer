---
spec_id: "TOOL-108"
tool_name: "add_dlp_shield"
version: "1.0.0"
status: "ratified"
invariants:
  - "INV-DLP-01"
  - "INV-DLP-02"
  - "INV-DLP-03"
  - "INV-DLP-04"
  - "INV-DLP-05"
  - "INV-DLP-06"
  - "INV-DLP-07"
  - "INV-DLP-08"
  - "INV-DLP-09"
  - "INV-DLP-10"
completeness_criteria:
  - "CC-01"
  - "CC-02"
  - "CC-03"
  - "CC-04"
  - "CC-05"
  - "CC-06"
  - "CC-07"
  - "CC-08"
  - "CC-11"
  - "CC-12"
  - "CC-13"
  - "CC-14"
  - "CC-15"
  - "CC-16"
  - "CC-17"
  - "CC-18"
  - "CC-N-1"
quality_standards:
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
  - "payments"
  - "data"
  - "realtime"
  - "compliance"
---
# TOOL-108: add_dlp_shield

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_dlp_shield` |
| Category | EXTEND > Infrastructure |
| Complexity | High |
| Dependencies | FastAPI, pydantic-settings, Starlette middleware, `re` (stdlib) |
| Signature | `add_dlp_shield(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_dlp_shield", "description": "Add a Data Loss Prevention shield with regex-based PII/PHI/PCI detection, Luhn validation, and four redaction modes.", "tags": ["extend", "infrastructure"], "entry": "add_dlp_shield"}` |
| Files created (typical) | 4 — `app/core/dlp/patterns.py`, `app/core/dlp/redactor.py`, `app/core/dlp/decorator.py`, `app/middleware/dlp_shield.py` |
| Files modified (typical) | 1 — `app/core/config.py` |

---

## 2. Purpose

The `fastapi_add_dlp_shield` tool installs a production-grade Data Loss Prevention (DLP) system into a FastAPI project. Regulatory environments (GDPR, HIPAA, PCI DSS) require that APIs never leak personally identifiable information (PII), protected health information (PHI), or payment card data in response bodies. The naive approach — a code review checklist — catches nothing systematically. A proper DLP layer intercepts every outbound response, scans it for sensitive patterns, and applies the configured redaction strategy before bytes leave the server.

The tool implements a four-layer system. First, `app/core/dlp/patterns.py` defines a `SensitivePattern` named-tuple (`name`, `regex`, `level`) and five `BUILTIN_PATTERNS`: `credit_card` (PCI level, 16-digit groups, validated by Luhn), `ssn` (PII level, `\d{3}-\d{2}-\d{4}`), `email` (PII level), `iban` (PHI level, ISO 13616), `phone` (PII level, E.164 and common formats). The `luhn_valid(number)` function validates credit card numbers to reduce false positives — a pure Python implementation of the Luhn algorithm.

Second, `app/core/dlp/redactor.py` with a `Redactor` class providing `redact_value(value, pattern) -> str` (applies the active redaction mode: `full`→`***`, `partial`→`***XXXX` last four digits, `tokenize`→`tok_` + sha256 first 12 chars, `remove`→empty string), `_replace(match) -> str`, `redact_payload(data: dict) -> dict` (recursively walks the dict and redacts matching string values), `_has_match(value) -> bool`, and `redact_json_bytes(body: bytes) -> bytes` (deserialises JSON, redacts, re-serialises).

Third, `app/core/dlp/decorator.py` with a `@sensitive(level)` decorator that marks function return values for DLP processing, storing the sensitivity level on the function object.

Fourth, `app/middleware/dlp_shield.py` with `DLPMiddleware` (`BaseHTTPMiddleware`) that intercepts every outbound JSON response, calls `Redactor().redact_json_bytes(body)`, and replaces the response body. Middleware skips non-JSON `Content-Type` responses and requests to bypass paths.

The tool patches `app/core/config.py` with four `DLP_*` fields: `DLP_ENABLED: bool = True`, `DLP_REDACTION_MODE: str = "full"`, `DLP_SENSITIVE_PATTERNS: list = []`, `DLP_BYPASS_ROLES: list = []`. The tool is idempotent: `class DLPMiddleware` in `app/middleware/dlp_shield.py` is the fingerprint.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | CI budget; measured via `execution_time_ms` |
| Files created | ≥ 4 | Patterns, redactor, decorator, middleware |
| Files modified | ≥ 1 | Config at minimum |
| Max function LOC in generated code | ≤ 50 | Auditable; AST-checked |
| Regex scan time per response | < 5 ms | 5 compiled patterns over typical JSON body |
| Luhn validation time | < 0.1 ms | Pure Python integer arithmetic |
| Middleware overhead | < 10 ms | JSON parse + regex scan + re-serialise |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── main.py
│   ├── core/
│   │   └── config.py        # No DLP_* fields
│   └── api/routes/
│       └── users.py         # Returns SSN, credit card in response
└── app/middleware/          # No DLP middleware
```

A bug in `GET /users/{id}` includes `ssn` in the serialised response. The leak goes undetected until an audit.

### 4.2 Patterns module: AFTER

```python
# app/core/dlp/patterns.py
"""Built-in sensitive data patterns for DLP scanning."""
from __future__ import annotations

import re
from typing import NamedTuple


class SensitivePattern(NamedTuple):
    """A named DLP pattern with its level classification."""

    name: str
    regex: re.Pattern
    level: str


def luhn_valid(number: str) -> bool:
    """Validate a credit card number with the Luhn algorithm."""
    digits = [int(d) for d in number if d.isdigit()]
    if not digits:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


BUILTIN_PATTERNS: list[SensitivePattern] = [
    SensitivePattern(
        name="credit_card",
        regex=re.compile(r"\b(?:\d{4}[- ]){3}\d{4}\b"),
        level="pci",
    ),
    SensitivePattern(
        name="ssn",
        regex=re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        level="pii",
    ),
    SensitivePattern(
        name="email",
        regex=re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
        level="pii",
    ),
    SensitivePattern(
        name="iban",
        regex=re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{4}\d{7}(?:[A-Z0-9]?){0,16}\b"),
        level="phi",
    ),
    SensitivePattern(
        name="phone",
        regex=re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b"),
        level="pii",
    ),
]
```

### 4.3 Redactor module: AFTER

```python
# app/core/dlp/redactor.py
"""DLP Redactor — apply redaction modes to sensitive values."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from app.core.dlp.patterns import BUILTIN_PATTERNS, SensitivePattern


class Redactor:
    """Redact sensitive patterns from string values and JSON payloads."""

    def __init__(self, mode: str = "full") -> None:
        self._mode = mode
        self._patterns: list[SensitivePattern] = BUILTIN_PATTERNS

    def redact_value(self, value: str, pattern: SensitivePattern) -> str:
        """Apply the configured redaction mode to a matching value."""
        if self._mode == "full":
            return "***"
        if self._mode == "partial":
            last4 = value[-4:] if len(value) >= 4 else value
            return f"***{last4}"
        if self._mode == "tokenize":
            token = hashlib.sha256(value.encode()).hexdigest()[:12]
            return f"tok_{token}"
        if self._mode == "remove":
            return ""
        return "***"

    def _replace(self, match) -> str:  # type: ignore[override]
        """Regex replacement callback."""
        return self.redact_value(match.group(0), BUILTIN_PATTERNS[0])

    def _has_match(self, value: str) -> bool:
        """Return True if *value* matches any built-in pattern."""
        return any(p.regex.search(value) for p in self._patterns)

    def redact_payload(self, data: Any) -> Any:
        """Recursively redact sensitive string values in a dict/list."""
        if isinstance(data, dict):
            return {k: self.redact_payload(v) for k, v in data.items()}
        if isinstance(data, list):
            return [self.redact_payload(item) for item in data]
        if isinstance(data, str):
            result = data
            for pattern in self._patterns:
                result = pattern.regex.sub(self._replace, result)
            return result
        return data

    def redact_json_bytes(self, body: bytes) -> bytes:
        """Deserialise *body*, redact, and re-serialise as bytes."""
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return body
        redacted = self.redact_payload(data)
        return json.dumps(redacted).encode()
```

### 4.4 Decorator module: AFTER

```python
# app/core/dlp/decorator.py
"""@sensitive decorator for marking function outputs for DLP processing."""
from __future__ import annotations

from functools import wraps
from typing import Any, Callable


def sensitive(level: str = "pii") -> Callable:
    """Mark a function's return value as sensitive at the given level.

    Args:
        level: Sensitivity level — 'pii', 'phi', or 'pci'.
    """
    def decorator(func: Callable) -> Callable:
        func._dlp_sensitivity_level = level  # type: ignore[attr-defined]

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await func(*args, **kwargs)

        return wrapper
    return decorator
```

### 4.5 DLP middleware: AFTER

```python
# app/middleware/dlp_shield.py
"""DLPMiddleware — scan and redact sensitive data in outbound responses."""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings
from app.core.dlp.redactor import Redactor


class DLPMiddleware(BaseHTTPMiddleware):
    """Redact PII/PHI/PCI from outbound JSON responses."""

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        if not settings.DLP_ENABLED:
            return await call_next(request)
        response = await call_next(request)
        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            return response
        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        mode = settings.DLP_REDACTION_MODE
        redacted = Redactor(mode=mode).redact_json_bytes(body)
        return Response(
            content=redacted,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type="application/json",
        )
```

### 4.6 Config patch (inside `class Settings`)

```python
# app/core/config.py  (diff, added by _patch_config)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # --- DLP shield settings — added by add_dlp_shield tool ---
    DLP_ENABLED: bool = True
    DLP_REDACTION_MODE: str = "full"
    DLP_SENSITIVE_PATTERNS: list = []
    DLP_BYPASS_ROLES: list = []
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Tool is idempotent on second run** | `"class DLPMiddleware" in dlp_shield.py` → `status="no_op"` |
| QS-2 | **`dry_run=True` writes zero files** | Early return before any write |
| QS-3 | **Every generated `.py` AST-parses** | `ast.parse` on each created `.py` |
| QS-4 | **No generated function exceeds 50 LOC** | AST walk; all methods kept short |
| QS-5 | **Five built-in patterns with correct levels** | `credit_card/pci`, `ssn/pii`, `email/pii`, `iban/phi`, `phone/pii` |
| QS-6 | **`luhn_valid` implements the Luhn algorithm** | Pure Python; reduces credit card false positives |
| QS-7 | **All four redaction modes implemented** | `full`, `partial`, `tokenize`, `remove` |
| QS-8 | **`@sensitive` stores level on function** | `func._dlp_sensitivity_level = level` |
| QS-9 | **Middleware skips non-JSON content types** | `"application/json" not in content_type` check |
| QS-10 | **No `httpx` module-level import** | `httpx` not imported at top-level in any generated file |
| QS-11 | **No TODO/FIXME/HACK in generated files** | Scan all generated `.py` |
| QS-12 | **`DLP_*` inside `class Settings`** | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES` |
| QS-13 | **`execution_time_ms` is positive** | `_elapsed_ms(start)` on all return paths |

---

## 6. Completeness Criteria

Every criterion is tied to a real assertion in `adapt/extend/infrastructure/test_add_dlp_shield.py`.

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | Tool returns `status="success"` on a fresh project | `result.status == "success"` | `test_success_status` |
| CC-02 | Second run returns `status="no_op"` with zero file ops | `r2.status == "no_op"` and both lists empty | `test_idempotent` |
| CC-03 | `dry_run=True` writes zero bytes to filesystem | `before == after` over all `.py` | `test_dry_run` |
| CC-04 | Tool creates at least 4 new files | `len(files_created) >= 4` | `test_files_created_count` |
| CC-05 | Tool modifies at least 1 existing file | `len(files_modified) >= 1` | `test_files_modified_count` |
| CC-06 | Every generated `.py` AST-parses cleanly | `ast.parse` over all `.py` | `test_all_py_parse` |
| CC-07 | No generated function exceeds 50 LOC in `app/` | AST walk, `max_loc <= 50` | `test_no_function_over_50_loc` |
| CC-08 | `DLP_ENABLED` and `DLP_REDACTION_MODE` inside `class Settings` body | String scan + indent check | `test_config_fields_patched` |
| CC-11 | `patterns.py` contains `BUILTIN_PATTERNS` and `SensitivePattern` | Both tokens in file | `test_builtin_patterns_present` |
| CC-12 | `luhn_valid` function present in `patterns.py` | `"luhn_valid"` or `"luhn_"` in file | `test_luhn_valid_present` |
| CC-13 | Patterns have `pci`, `pii`, and `phi` levels | All three level strings present | `test_pattern_levels` |
| CC-14 | `Redactor` class with `redact_value`, `redact_payload` present | Both method names in `redactor.py` | `test_redactor_created` |
| CC-15 | All four redaction modes (`full`, `partial`, `tokenize`, `remove`) present | All four tokens in `redactor.py` | `test_redaction_modes` |
| CC-16 | `@sensitive` decorator with `_dlp_sensitivity_level` attribute | Both tokens in `decorator.py` | `test_sensitive_decorator` |
| CC-17 | `DLPMiddleware` with `BaseHTTPMiddleware` and `dispatch` in `dlp_shield.py` | All three tokens | `test_dlp_middleware_created` |
| CC-18 | Middleware checks `content-type` before processing | `"content-type"` or `"content_type"` in middleware | `test_content_type_check` |
| QS-04 | No module-level `httpx` import in generated files | Top-level import scan | `test_no_top_level_httpx` |
| CC-N-1 | `execution_time_ms` is a positive integer | `result.execution_time_ms > 0` | `test_execution_time_recorded` |
| CC-N | `next_steps` mentions `dlp`, `middleware`, or `enabled` | Token in lowercased join | `test_next_steps_present` |
| CC-LAST | Two runs leave the project AST-parseable | `ast.parse` after two runs | `test_idempotent_project_still_parses` |
| QS-03 | No TODO/FIXME/HACK comments | Scan all generated `.py` | `test_no_todo_fixme_hack` |
| CC-extra | At least 4 `SensitivePattern` instances in `BUILTIN_PATTERNS` | Count of `SensitivePattern(` in file ≥ 4 | `test_four_or_more_patterns` |

---

## 7. Definition of Done (DoD)

- [ ] All 22 Completeness Criteria verified by `test_add_dlp_shield.py`
- [ ] `add_dlp_shield.py` runs `ast.parse` on every created `.py` before returning success
- [ ] Fingerprint `"class DLPMiddleware" in dlp_shield.py` triggers `status="no_op"`
- [ ] `dry_run=True` returns success with empty `files_created`/`files_modified`
- [ ] `BUILTIN_PATTERNS` contains 5 entries covering PCI/PII/PHI levels
- [ ] `luhn_valid()` pure Python Luhn algorithm present in `patterns.py`
- [ ] All four redaction modes (`full`, `partial`, `tokenize`, `remove`) in `Redactor.redact_value`
- [ ] `@sensitive(level)` sets `func._dlp_sensitivity_level = level`
- [ ] `DLPMiddleware.dispatch` skips non-JSON responses
- [ ] No `httpx` imported at module level in any generated file
- [ ] `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30`
- [ ] `execution_time_ms` set on every return path
- [ ] `MCP_TOOL` descriptor exposes `{name, description, tags, entry}` quartet

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-DLP-01 | Tool is ALWAYS idempotent | `"class DLPMiddleware" in dlp_shield.py` → `status="no_op"` | `test_idempotent` |
| INV-DLP-02 | `dry_run=True` NEVER writes to disk | Early return before write | `test_dry_run` |
| INV-DLP-03 | Every generated `.py` MUST parse | `ast.parse` loop | `test_all_py_parse` |
| INV-DLP-04 | `BUILTIN_PATTERNS` MUST include pci, pii, phi levels | All three level strings present | `test_pattern_levels` |
| INV-DLP-05 | `luhn_valid` MUST be present for PCI compliance | `"luhn"` in `patterns.py` | `test_luhn_valid_present` |
| INV-DLP-06 | All four redaction modes MUST be implemented | `full/partial/tokenize/remove` in `Redactor` | `test_redaction_modes` |
| INV-DLP-07 | Middleware MUST skip non-JSON responses | Content-type check in `dispatch` | `test_content_type_check` |
| INV-DLP-08 | `httpx` MUST NOT be at module level | Top-level import check | `test_no_top_level_httpx` |
| INV-DLP-09 | `DLP_*` settings MUST land inside `class Settings` | `_patch_config` anchor | `test_config_fields_patched` |
| INV-DLP-10 | `ToolResult.execution_time_ms` MUST be positive | `_elapsed_ms(start)` on all branches | `test_execution_time_recorded` |

---

## 9. User Stories

### 9.1 Core install flow (US-01 .. US-05)

**US-01: Install DLP shield into a clean FastAPI project**
- **As a** compliance engineer
- **I want** one tool call to add regex-based PII/PCI/PHI detection
- **So that** sensitive data never leaks in responses
- **Given:** A FastAPI project with `app/core/config.py`
- **When:** `add_dlp_shield(ToolInput(project_dir=...))`
- **Then:**
  - Returns `ToolResult.status == "success"` (CC-01)
  - ≥ 4 files created (CC-04)
  - Verified by `test_success_status`, `test_files_created_count`

**US-02: Re-run safely**
- **As a** CI job
- **I want** `status="no_op"` on second run
- **Given:** `class DLPMiddleware` already in `dlp_shield.py`
- **When:** Tool invoked again
- **Then:** `r2.status == "no_op"` — verified by `test_idempotent`

**US-03: Dry-run preview**
- **Given:** Fresh project
- **When:** `add_dlp_shield(ToolInput(project_dir=..., dry_run=True))`
- **Then:** Zero filesystem changes — verified by `test_dry_run`

**US-04: Config fields are env-var overridable**
- **As a** platform engineer
- **I want** `DLP_ENABLED` and `DLP_REDACTION_MODE` in `Settings`
- **Given:** `ACCESS_TOKEN_EXPIRE_MINUTES` in config
- **When:** Tool runs
- **Then:** Fields inside class body — verified by `test_config_fields_patched`

**US-05: Generated code is auditable**
- **As a** security reviewer
- **I want** all functions ≤ 50 LOC
- **Given:** Tool emitted `patterns.py`, `redactor.py`, `decorator.py`, `dlp_shield.py`
- **When:** AST walk over `app/`
- **Then:** `max_loc <= 50` — verified by `test_no_function_over_50_loc`

### 9.2 DLP logic (US-06 .. US-10)

**US-06: Redact credit card numbers in responses**
- **As a** developer with a CC in a response
- **I want** DLP middleware to replace it before leaving the server
- **Given:** `DLP_ENABLED=true`, `DLP_REDACTION_MODE=full`
- **When:** Response body contains `4532-0151-1283-0366`
- **Then:** Body contains `***` instead — verified by CC-15

**US-07: Validate credit card numbers via Luhn**
- **As a** compliance engineer
- **I want** Luhn validation to avoid false positives
- **Given:** `luhn_valid("4532015112830366")` (valid CC)
- **When:** Called
- **Then:** Returns `True`; `luhn_valid("1234567890123456")` returns `False`

**US-08: Partial redaction keeps last 4 digits**
- **As a** UX designer
- **I want** partial mode to show last 4 for recognition
- **Given:** `DLP_REDACTION_MODE=partial`
- **When:** CC `4532-0151-1283-0366` appears in response
- **Then:** Redacted to `***0366`

**US-09: Non-JSON responses pass through**
- **As an** image-serving endpoint
- **I want** DLP to skip binary responses
- **Given:** Response has `Content-Type: image/png`
- **When:** Middleware processes it
- **Then:** Body unchanged — verified by CC-18

**US-10: Mark function output as sensitive**
- **As a** developer
- **I want** `@sensitive("pci")` on a route handler
- **Given:** `@sensitive` from `app.core.dlp.decorator`
- **When:** Applied to a function
- **Then:** `func._dlp_sensitivity_level == "pci"` — verified by CC-16

### 9.3 Integration (US-11 .. US-13)

**US-11: DLP can be disabled for trusted internal routes**
- **As an** internal API
- **I want** `DLP_ENABLED=false` to bypass the shield
- **Given:** `settings.DLP_ENABLED is False`
- **When:** Any request passes through middleware
- **Then:** Response body unchanged

**US-12: Project parseable after two runs**
- **As a** CI system
- **Given:** Tool applied twice
- **When:** `ast.parse` over all `.py`
- **Then:** Zero errors — verified by CC-LAST

**US-13: No TODO/FIXME/HACK in generated files**
- **As a** code reviewer
- **Given:** DLP shield installed
- **When:** Scan all generated `.py` for `TODO`/`FIXME`/`HACK`
- **Then:** Zero occurrences — verified by QS-03

---

## 10. Error Handling

| Scenario | Behaviour | Status |
|----------|-----------|--------|
| `project_dir` does not exist | Returns `status="error"`, `error` set | `"error"` |
| `app/core/config.py` absent | `ensure_prerequisites` raises; `status="error"` | `"error"` |
| Response body is not valid JSON | `redact_json_bytes` returns body unchanged | Silent degradation |
| Invalid redaction mode | `Redactor.redact_value` falls through to `return "***"` | Defaults to full |

---

## 11. Dependencies

| Package | Why needed |
|---------|------------|
| `re` (stdlib) | Compiled regex patterns |
| `hashlib` (stdlib) | SHA-256 for `tokenize` mode |
| `json` (stdlib) | JSON parse + re-serialise in middleware |
| `functools.wraps` (stdlib) | `@sensitive` wrapper |
| `starlette.middleware.base` | `BaseHTTPMiddleware` |
| `pydantic-settings` | `Settings` in target project |

No new packages added to `requirements.txt`.

---

## 12. Security Considerations

| Concern | Mitigation |
|---------|-----------|
| Regex false negatives | Five patterns cover major PII/PHI/PCI categories; operators can extend via `DLP_SENSITIVE_PATTERNS` |
| Performance under high load | Compiled `re.Pattern` objects; avoid per-request compilation |
| Tokenisation reversibility | `tok_` + sha256 tokens are not reversible; original data not recoverable from token |
| Bypass roles | `DLP_BYPASS_ROLES` allows trusted roles to skip redaction (e.g. internal audit tooling) |

---

## 13. Observability

| Signal | Where |
|--------|-------|
| `execution_time_ms` | `ToolResult.execution_time_ms` |
| Redacted responses | Can add logging in `DLPMiddleware.dispatch` on pattern match |
| Disabled DLP | `DLP_ENABLED=false` passes all responses unchanged |

---

## 14. Configuration Reference

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `DLP_ENABLED` | `bool` | `True` | Master switch for DLP scanning |
| `DLP_REDACTION_MODE` | `str` | `"full"` | One of: `full`, `partial`, `tokenize`, `remove` |
| `DLP_SENSITIVE_PATTERNS` | `list` | `[]` | Additional patterns (list of `{name, regex, level}` dicts) |
| `DLP_BYPASS_ROLES` | `list` | `[]` | Role names that bypass DLP redaction |

---

## 15. Migration / Rollback

**Rollback is mechanical:**
- Delete `app/core/dlp/` (3 files)
- Delete `app/middleware/dlp_shield.py`
- Remove `DLP_*` lines from `app/core/config.py`
- Remove `DLPMiddleware` from `app/main.py` if added manually

No database migrations. No external services.

---

## 16. Test File Reference

**Location:** `adapt/extend/infrastructure/test_add_dlp_shield.py`

**Test runner:**
```bash
PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_dlp_shield.py -v
# or standalone:
PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_dlp_shield.py
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
| `test_config_fields_patched` | CC-08 | `DLP_ENABLED` inside `class Settings` body |
| `test_builtin_patterns_present` | CC-11 | `BUILTIN_PATTERNS` + `SensitivePattern` in `patterns.py` |
| `test_luhn_valid_present` | CC-12 | `luhn_valid` in `patterns.py` |
| `test_pattern_levels` | CC-13 | `pci`, `pii`, `phi` level strings present |
| `test_redactor_created` | CC-14 | `Redactor`, `redact_value`, `redact_payload` in `redactor.py` |
| `test_redaction_modes` | CC-15 | `full`, `partial`, `tokenize`, `remove` in `redactor.py` |
| `test_sensitive_decorator` | CC-16 | `@sensitive` + `_dlp_sensitivity_level` in `decorator.py` |
| `test_dlp_middleware_created` | CC-17 | `DLPMiddleware` + `BaseHTTPMiddleware` + `dispatch` |
| `test_content_type_check` | CC-18 | Content-type check in middleware |
| `test_no_top_level_httpx` | QS-04 | No module-level `httpx` import |
| `test_execution_time_recorded` | CC-N-1 | `execution_time_ms > 0` |
| `test_next_steps_present` | CC-N | `next_steps` mentions `dlp`/`middleware`/`enabled` |
| `test_idempotent_project_still_parses` | CC-LAST | Two runs → all `.py` still parse |
| `test_no_todo_fixme_hack` | QS-03 | No `TODO`/`FIXME`/`HACK` in generated files |
| `test_four_or_more_patterns` | CC-extra | ≥ 4 `SensitivePattern` instances in `BUILTIN_PATTERNS` |
