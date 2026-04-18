# TOOL-074: add_social_login

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_social_login` |
| Category | EXTEND > Auth/Access |
| Complexity | High |
| Dependencies | FastAPI, SQLAlchemy 2.0, Alembic, pydantic-settings, httpx (lazy) |
| Signature | `add_social_login(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_social_login", "description": "Add Google/GitHub/Apple OAuth2 social login with account linking to a FastAPI project.", "tags": ["extend", "auth_access"], "entry": "add_social_login"}` |
| Files created (typical) | 6 — `app/auth/social.py`, `app/models/social_account.py`, `app/schemas/social.py`, `app/api/routes/social_auth.py`, `app/auth/__init__.py`, `alembic/versions/0074_add_social_login.py` |
| Files modified (typical) | 3 — `app/core/config.py`, `app/models/__init__.py`, `app/routes/__init__.py` |

---

## 2. Purpose

The `fastapi_add_social_login` tool installs production-grade OAuth2 social login via Google, GitHub, and Apple into a FastAPI project in a single call. Teams hand-roll social auth and get it wrong in predictable ways: they store the OAuth2 `access_token` (which expires) instead of the `provider_user_id` (which does not), they fail to handle account linking when the same email is registered via two providers, they skip state-parameter CSRF protection on the redirect leg, and they discover too late that Apple's callback returns the user's name only once, meaning the `User` record is incomplete for every subsequent login.

This tool generates: (a) `app/auth/social.py` with a `SocialAuthProvider` enum (GOOGLE, GITHUB, APPLE) and three lazy-httpx provider functions (`exchange_google_code`, `exchange_github_code`, `exchange_apple_code`) — `httpx` is imported inside each body so the app boots without it installed; (b) `app/models/social_account.py` with a `SocialAccount` SQLAlchemy model (`provider`, `provider_user_id`, `user_id` FK, `email`, `created_at`) — `provider_user_id` is the durable external identity; (c) Pydantic schemas (`SocialCallbackRequest`, `SocialLoginResponse`); (d) route handlers `GET /auth/{provider}/login` (redirect to provider) and `GET /auth/{provider}/callback` (exchange code, link account, return JWT); (e) account linking logic: if the email returned by the provider matches an existing `User`, the `SocialAccount` row is linked to that user — no duplicate accounts; and (f) an Alembic migration creating `social_accounts` with a composite unique constraint on `(provider, provider_user_id)`.

Key design decisions: `httpx` calls are always `async`; provider credentials (`GOOGLE_CLIENT_ID`, etc.) are read from `settings` at call time — never hard-coded; the `state` parameter is a `secrets.token_urlsafe(32)` value stored in an in-process dict for the callback verification (TTL-bound, replaceable with Redis for multi-replica); `provider_user_id` is stored as a `String(128)` to cover Apple's opaque identifiers; the tool is idempotent via `"SocialAccount" in app/models/social_account.py` fingerprint check.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | CI step budget; measured via `execution_time_ms` in `ToolResult` |
| Files created | ≥ 5 | Model, auth module, schemas, routes, migration (plus optional `__init__`) |
| Files modified | ≥ 2 | Config, models init, routes init — at least two must exist |
| Max function LOC in generated code | ≤ 50 | Auditability requirement; enforced by AST walk |
| OAuth2 redirect response time | < 2 ms | Pure redirect, no I/O |
| Callback (code exchange) latency | < 500 ms | One `httpx` call to provider token endpoint; network-bound |
| `provider_user_id` lookup latency | < 5 ms | Indexed lookup on `(provider, provider_user_id)` |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── main.py
│   ├── core/config.py          # No GOOGLE_* / GITHUB_* / APPLE_* fields
│   ├── models/__init__.py      # No SocialAccount
│   └── routes/__init__.py      # No social_auth router
└── alembic/versions/
```

No social login capability. Users must authenticate via password or API key only.

### 4.2 SocialAccount model: AFTER

```python
# app/models/social_account.py
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base

class SocialAccount(Base):
    """Linked OAuth2 social identity for a user.

    One user may link multiple social accounts (one per provider).
    The provider_user_id is the durable identity — never the OAuth access_token.
    """
    __tablename__ = "social_accounts"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name="uq_social_provider_uid"),
    )
```

### 4.3 Social auth provider module: AFTER

```python
# app/auth/social.py  (excerpt)
import enum, logging, os, secrets
logger = logging.getLogger(__name__)

class SocialAuthProvider(str, enum.Enum):
    GOOGLE = "google"
    GITHUB = "github"
    APPLE  = "apple"

async def exchange_google_code(code: str) -> dict:
    """Exchange a Google authorization code for user profile.
    httpx imported lazily inside function body.
    """
    import httpx
    client_id     = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    redirect_uri  = os.environ.get("GOOGLE_REDIRECT_URI", "")
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={"code": code, "client_id": client_id,
                  "client_secret": client_secret,
                  "redirect_uri": redirect_uri,
                  "grant_type": "authorization_code"},
        )
        token_resp.raise_for_status()
        token = token_resp.json()
        profile_resp = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {token['access_token']}"},
        )
        profile_resp.raise_for_status()
        profile = profile_resp.json()
    return {"provider_user_id": profile["id"], "email": profile.get("email"),
            "name": profile.get("name")}
```

### 4.4 Route handlers: AFTER

```
GET  /auth/{provider}/login     → redirect to provider OAuth2 URL (state cookie set)
GET  /auth/{provider}/callback  → exchange code, link/create user, return JWT
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | Tool is idempotent on second run | `"SocialAccount" in app/models/social_account.py` → `status="no_op"` |
| QS-2 | `dry_run=True` writes zero files | Early return before any write when `inp.dry_run` is truthy |
| QS-3 | Every generated `.py` file AST-parses | `ast.parse` over each created `.py`; tool returns `status="error"` on `SyntaxError` |
| QS-4 | No generated function exceeds 50 LOC | Construction discipline; asserted by AST walk in test harness |
| QS-5 | Provider credentials never hard-coded | All `*_CLIENT_ID`, `*_SECRET` read from `os.environ` / `settings` at call time |
| QS-6 | `httpx` imported lazily in every provider function | Import statement inside function body only |
| QS-7 | Account linking by verified email | `_find_user_by_email` SQL query before creating new `User` |
| QS-8 | `provider_user_id` stored — not the access token | Model stores `provider_user_id`; access token discarded after user info fetch |
| QS-9 | `(provider, provider_user_id)` unique constraint | `UniqueConstraint("provider", "provider_user_id")` in model + migration |
| QS-10 | State parameter CSRF protection on redirect | `secrets.token_urlsafe(32)` stored in `_STATE_STORE` dict; validated in callback |
| QS-11 | `execution_time_ms` positive on every return path | `_elapsed_ms(start)` called on all branches |
| QS-12 | Alembic migration chained to current head | `find_migration_head` used in `_write_migration` |

---

## 6. Completeness Criteria

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | Tool returns `status="success"` on fresh project | `result.status == "success"` | T-01 (`test_success_status`) |
| CC-02 | Second run returns `status="no_op"` with zero file ops | `r2.status == "no_op"` and both lists empty | T-02 (`test_idempotent`) |
| CC-03 | `dry_run=True` writes zero bytes to the filesystem | Snapshot dict before/after; byte-identical | T-03 (`test_dry_run`) |
| CC-04 | Tool creates at least 5 new files | `len(result.files_created) >= 5` and each path exists | T-04 (`test_files_created_count`) |
| CC-05 | Tool modifies at least 2 existing files | `len(result.files_modified) >= 2` and each path exists | T-05 (`test_files_modified_count`) |
| CC-06 | Every generated `.py` AST-parses cleanly | `ast.parse` over all `.py` in project tree | T-06 (`test_all_py_parse`) |
| CC-07 | No generated function exceeds 50 LOC | AST walk `FunctionDef`/`AsyncFunctionDef`, `max_loc <= 50` | T-07 (`test_no_function_over_50_loc`) |
| CC-08 | `GOOGLE_CLIENT_ID` and `GITHUB_CLIENT_ID` exist in `app/core/config.py` inside Settings | Substring + indent check | T-08 (`test_config_fields_patched`) |
| CC-09 | `SocialAccount` registered in `app/models/__init__.py` | `"SocialAccount" in content` | T-09 (`test_models_init_patched`) |
| CC-10 | Social auth router registered in `app/routes/__init__.py` | `"social" in content.lower()` | T-10 (`test_routes_registered`) |
| CC-11 | `app/models/social_account.py` contains `class SocialAccount` | File exists + substring | T-11 (`test_model_created`) |
| CC-12 | `app/auth/social.py` contains `SocialAuthProvider` enum and `exchange_google_code` | File exists + substrings | T-12 (`test_social_auth_module`) |
| CC-13 | `app/api/routes/social_auth.py` contains both route handlers | File exists + `"/login"` + `"/callback"` | T-13 (`test_routes_created`) |
| CC-14 | Alembic migration creates `social_accounts` table with unique constraint | Migration file exists + `"social_accounts"` + `"uq_social_provider_uid"` | T-14 (`test_migration_created`) |
| CC-15 | `execution_time_ms` is a positive integer on success path | `result.execution_time_ms > 0` | T-15 (`test_execution_time_recorded`) |
| CC-16 | `next_steps` includes `alembic` and provider credential guidance | Lowercased join contains `"alembic"` and `"client_id"` | T-16 (`test_next_steps_mention_alembic`) |

---

## 7. Definition of Done (DoD)

- [ ] All 16 Completeness Criteria verified by `test_add_social_login.py`
- [ ] `add_social_login.py` runs `ast.parse` on every created `.py` before returning success
- [ ] `add_social_login.py` detects `"SocialAccount"` fingerprint and returns `status="no_op"` on second run
- [ ] `dry_run=True` returns success with empty `files_created`/`files_modified`
- [ ] `httpx` imported lazily inside each provider exchange function body
- [ ] Provider credentials (`GOOGLE_CLIENT_ID`, `GITHUB_CLIENT_ID`, etc.) read from settings/env only
- [ ] Account linking: if email matches existing `User`, link `SocialAccount` to that user
- [ ] `SocialAccount` has composite unique constraint on `(provider, provider_user_id)`
- [ ] State parameter stored in `_STATE_STORE` dict and validated in callback
- [ ] Migration chained to current head via `find_migration_head`
- [ ] `execution_time_ms` set on every return path

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-SOC-01 | Tool is ALWAYS idempotent on second invocation | `"SocialAccount" in model_file.read_text()` → `status="no_op"` | T-02 |
| INV-SOC-02 | `dry_run=True` NEVER writes to disk | Early return before any `dest.write_text(...)` | T-03 |
| INV-SOC-03 | Every generated `.py` MUST parse as valid Python | `ast.parse` loop after all writes | T-06 |
| INV-SOC-04 | Provider credentials MUST come from environment/settings — never hard-coded | `os.environ.get(...)` pattern in every provider function | T-12 |
| INV-SOC-05 | `httpx` MUST be imported lazily inside function bodies | `import httpx` inside `exchange_*` functions only | T-12 |
| INV-SOC-06 | `provider_user_id` MUST be stored, not the access token | Model column is `provider_user_id`; access token not persisted | T-11 |
| INV-SOC-07 | `(provider, provider_user_id)` MUST be unique | `UniqueConstraint` in model + migration | T-11, T-14 |
| INV-SOC-08 | `ToolResult.execution_time_ms` MUST be positive on every return path | `_elapsed_ms(start)` on all branches | T-15 |

---

## 9. User Stories

### 9.1 Core install flow (US-01 .. US-04)

**US-01: Install social login into a clean FastAPI project**
- **As a** backend engineer who needs OAuth2 social login
- **I want** to run one tool call and get a working Google/GitHub/Apple flow
- **So that** I stop hand-rolling OAuth2 redirect + callback + account-link logic
- **Given:** FastAPI project with `app/core/config.py`, `app/models/base.py`, `alembic/versions/`, `requirements.txt`
- **When:** `add_social_login(ToolInput(project_dir=...))`
- **Then:** `status == "success"`, `files_created >= 5`, `files_modified >= 2` (CC-01, CC-04, CC-05)

**US-02: Re-run the tool on an already-configured project**
- **As a** CI job that re-applies tooling
- **I want** the tool to detect existing `SocialAccount` and skip
- **So that** repeated runs are safe
- **Given:** `app/models/social_account.py` exists with `"SocialAccount"`
- **When:** Tool invoked a second time
- **Then:** `status="no_op"`, empty lists, all `.py` still parse (CC-02)

**US-03: Dry-run preview without touching files**
- **As a** developer reviewing what the tool will do
- **I want** to see notes but have no files written
- **So that** I can audit before committing
- **Given:** Fresh fixture project
- **When:** `add_social_login(ToolInput(dry_run=True))`
- **Then:** `status="success"`, filesystem byte-identical before/after (CC-03)

**US-04: Link social login to existing email account**
- **As a** user who already has a password account
- **I want** to sign in with Google and have it linked to my existing account
- **So that** I do not end up with two accounts
- **Given:** `User` with `email="user@example.com"` exists
- **When:** Google callback returns `email="user@example.com"`
- **Then:** New `SocialAccount` row links to existing `User`; no duplicate `User` created (QS-7)

### 9.2 Provider exchange functions (US-05 .. US-08)

**US-05: Exchange Google authorization code**
- **As a** callback handler
- **I want** `exchange_google_code(code)` to return `{provider_user_id, email, name}`
- **So that** I can persist or link the social account
- **Given:** Valid `code` from Google OAuth2 redirect
- **When:** `await exchange_google_code(code)` is called
- **Then:** Returns dict with `provider_user_id`, `email`, `name`; access token discarded (INV-SOC-06)

**US-06: Exchange GitHub authorization code**
- **As a** callback handler
- **I want** `exchange_github_code(code)` to hit GitHub's token + user endpoints
- **So that** I get the GitHub user's `id` as `provider_user_id`
- **Given:** Valid GitHub code
- **When:** `await exchange_github_code(code)`
- **Then:** Returns dict with `provider_user_id` = GitHub numeric id as string

**US-07: Exchange Apple authorization code**
- **As a** callback handler
- **I want** `exchange_apple_code(code)` to handle Apple's ID token JWT
- **So that** I extract `sub` as `provider_user_id`
- **Given:** Apple `code` + Apple's note that name is only returned on first login
- **When:** `await exchange_apple_code(code)`
- **Then:** Returns `provider_user_id = sub` from Apple ID token; `email` may be absent on repeat logins

**US-08: Provider import does not crash app at boot**
- **As a** DevOps engineer who has not installed httpx
- **I want** the app to start cleanly without the social login credentials set
- **So that** optional features do not block deployment
- **Given:** `httpx` not installed
- **When:** App starts, no social login route is called
- **Then:** No `ImportError` at startup (INV-SOC-05)

### 9.3 Security and configuration (US-09 .. US-12)

**US-09: CSRF protection via state parameter**
- **As a** security reviewer
- **I want** the login redirect to include a `state` parameter
- **So that** an attacker cannot forge a callback
- **Given:** `GET /auth/google/login` is called
- **When:** Handler generates redirect URL
- **Then:** URL includes `state=<random>` stored in `_STATE_STORE`; callback validates state

**US-10: Config fields injected into Settings class**
- **As an** ops engineer using `.env`
- **I want** `GOOGLE_CLIENT_ID` etc. in `app/core/config.py` inside `class Settings`
- **So that** pydantic-settings binds them from env vars
- **Given:** Tool ran successfully
- **When:** `app/core/config.py` is read
- **Then:** `GOOGLE_CLIENT_ID`, `GITHUB_CLIENT_ID`, `APPLE_CLIENT_ID` all present with 4-space indent (CC-08)

**US-11: Unique constraint prevents duplicate social accounts**
- **As a** database integrity guard
- **I want** a composite unique constraint on `(provider, provider_user_id)`
- **So that** double-register attempts raise a DB error rather than creating duplicate rows
- **Given:** `SocialAccount` already exists for Google user id `"12345"`
- **When:** Second registration attempt with same provider + id
- **Then:** `UniqueViolation` raised; handler returns 409 (INV-SOC-07)

**US-12: Execution time is always recorded**
- **As a** monitoring system
- **I want** `execution_time_ms` on every `ToolResult`
- **So that** I can track tool performance
- **Given:** Any invocation path (success, no_op, dry_run, error)
- **When:** Result is returned
- **Then:** `result.execution_time_ms > 0` (INV-SOC-08)

---

## 10. Test Plan

All 16 tests live in `adapt/extend/auth_access/test_add_social_login.py`.

### 10.1 Category A — Tool execution (T-01 .. T-05)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | `test_success_status` | Fixture `sl_t01` | `add_social_login(ToolInput(project_dir))` | `result.status == "success"` (CC-01) |
| T-02 | `test_idempotent` | Fixture `sl_t02`; run once | Run again | `r2.status == "no_op"`, empty lists (CC-02) |
| T-03 | `test_dry_run` | Fixture `sl_t03` | `add_social_login(ToolInput(dry_run=True))` | `status == "success"`; filesystem unchanged (CC-03) |
| T-04 | `test_files_created_count` | Fixture `sl_t04` | Run tool | `len(files_created) >= 5`, each path exists (CC-04) |
| T-05 | `test_files_modified_count` | Fixture `sl_t05` | Run tool | `len(files_modified) >= 2`, each path exists (CC-05) |

### 10.2 Category B — Generated code quality (T-06 .. T-10)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-06 | `test_all_py_parse` | Fixture `sl_t06`; run tool | `ast.parse` every `.py` | No `SyntaxError` (CC-06) |
| T-07 | `test_no_function_over_50_loc` | Fixture `sl_t07`; run tool | AST walk `app/` | `max_loc <= 50` (CC-07) |
| T-08 | `test_config_fields_patched` | Fixture `sl_t08`; run tool | Read `app/core/config.py` | Contains `GOOGLE_CLIENT_ID` with 4-space indent (CC-08) |
| T-09 | `test_models_init_patched` | Fixture `sl_t09`; run tool | Read `app/models/__init__.py` | Contains `"SocialAccount"` (CC-09) |
| T-10 | `test_routes_registered` | Fixture `sl_t10`; run tool | Read `app/routes/__init__.py` | Contains `"social"` (case-insensitive) (CC-10) |

### 10.3 Category C — Domain-specific modules (T-11 .. T-14)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-11 | `test_model_created` | Fixture `sl_t11`; run tool | Read `app/models/social_account.py` | File exists; `"class SocialAccount"` present (CC-11) |
| T-12 | `test_social_auth_module` | Fixture `sl_t12`; run tool | Read `app/auth/social.py` | Contains `SocialAuthProvider`, `exchange_google_code`, `import httpx` inside function | T-12 (`test_social_auth_module`) (CC-12) |
| T-13 | `test_routes_created` | Fixture `sl_t13`; run tool | Read `app/api/routes/social_auth.py` | Contains `"/login"` and `"/callback"` (CC-13) |
| T-14 | `test_migration_created` | Fixture `sl_t14`; run tool | Scan `alembic/versions/` | File with `"social_accounts"` and `"uq_social_provider_uid"` exists (CC-14) |

### 10.4 Category D — Meta (T-15 .. T-16)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-15 | `test_execution_time_recorded` | Fixture `sl_t15`; run tool | Read `result.execution_time_ms` | `> 0` (CC-15) |
| T-16 | `test_next_steps_mention_alembic` | Fixture `sl_t16`; run tool | Lowercase-join `result.next_steps` | Contains `"alembic"` and `"client_id"` (CC-16) |

### 10.5 Test execution

```bash
PYTHONPATH=. pytest adapt/extend/auth_access/test_add_social_login.py -v
```

Target: 16/16 passed, 0 failed.

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| `add_mfa` (TOOL-013) | No | ✅ Compatible | Social login + MFA can coexist; social callback issues JWT, MFA verifies second factor separately |
| `add_passkey_auth` (TOOL-075) | No | ✅ Compatible | Multiple auth methods; `User` table shared |
| `add_sms_otp` (TOOL-076) | No | ✅ Compatible | SMS OTP is an alternative 2FA method alongside social login |
| `add_multi_tenancy` (TOOL-008) | Yes — tenancy BEFORE | ✅ Compatible | If `app/models/tenant.py` exists, `SocialAccount` may need `tenant_id`; currently not auto-linked |
| `add_rbac` (TOOL-012) | Yes — RBAC AFTER | ✅ Compatible | After social callback, RBAC assigns default roles |
| `add_audit_log` (TOOL-005) | No | ✅ Compatible | Social login events (`social.login`, `social.register`) should emit audit entries |
| `add_soft_delete` (TOOL-001) | No | ⚠️ Caveat | Soft-deleting `User` should cascade to `SocialAccount` rows; exclude `SocialAccount` from soft-delete mixin |

---

## 12. Rollback Procedure

### 12.1 Code rollback (before deploy)

```bash
git checkout HEAD -- \
  app/core/config.py \
  app/models/__init__.py \
  app/routes/__init__.py

rm -f app/models/social_account.py \
      app/auth/social.py \
      app/schemas/social.py \
      app/api/routes/social_auth.py
find alembic/versions/ -name '*social*' -delete
```

### 12.2 Database rollback (after deploy)

```bash
alembic downgrade -1   # drops social_accounts table + index
```

### 12.3 Uninstall validator

```bash
test ! -f app/models/social_account.py || (echo "SocialAccount model still present" && exit 1)
grep -q "GOOGLE_CLIENT_ID" app/core/config.py && echo "config still patched" && exit 1
echo "rollback verified"
```

---

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-01 | Invalid `project_dir` | `validate_project_dir` fails → `status="error"` |
| EC-02 | Missing prerequisites | `ensure_prerequisites` → `status="error"` with list |
| EC-03 | `app/models/social_account.py` exists with `"SocialAccount"` | `status="no_op"`, zero writes |
| EC-04 | `dry_run=True` | Notes only, zero writes (INV-SOC-02) |
| EC-05 | `app/core/config.py` already has `GOOGLE_CLIENT_ID` | `_patch_config` early-returns; no duplicate |
| EC-06 | `alembic/versions/` missing | Migration step skipped; other files written |
| EC-07 | `app/routes/__init__.py` missing | Router registration skipped; note emitted |
| EC-08 | Apple ID token lacks `email` field | `exchange_apple_code` returns `email=None`; account created without email; linking skipped |
| EC-09 | Provider returns duplicate `provider_user_id` on re-login | `_find_social_account` returns existing row; no new `SocialAccount` created |
| EC-10 | `find_migration_head` returns `None` | Falls back to `"0001_initial"` |
| EC-11 | Generated file has `SyntaxError` | `ast.parse` raises; tool returns `status="error"` |
| EC-12 | `app/auth/__init__.py` missing | Created with minimal docstring |

---

## 14. Acceptance Criteria (Final Sign-off)

1. ✅ All 16 Completeness Criteria verified via `test_add_social_login.py` passing
2. ✅ `test_add_social_login.py` reports `16 passed, 0 failed`
3. ✅ Tool execution time < 5 s on reference hardware
4. ✅ Second invocation returns `status="no_op"` with empty lists (INV-SOC-01)
5. ✅ `dry_run=True` produces zero filesystem writes (INV-SOC-02)
6. ✅ Every generated `.py` AST-parses cleanly (INV-SOC-03)
7. ✅ No generated function exceeds 50 LOC (QS-4)
8. ✅ Provider credentials read from environment — never hard-coded (INV-SOC-04)
9. ✅ `httpx` imported lazily inside exchange functions (INV-SOC-05)
10. ✅ `provider_user_id` stored — access token discarded (INV-SOC-06)
11. ✅ `(provider, provider_user_id)` unique constraint in model + migration (INV-SOC-07)
12. ✅ `execution_time_ms` positive on all return paths (INV-SOC-08)

---

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks

- [ ] `validate_project_dir(inp.project_dir)` returns no error
- [ ] `ensure_prerequisites(BASE_MODEL, MODELS_INIT, CONFIG_SETTINGS, ROUTES_INIT, ALEMBIC_VERSIONS)` passes
- [ ] `app/models/social_account.py` does NOT contain `"SocialAccount"` (otherwise → `no_op`)
- [ ] If `inp.dry_run`, emit dry-run notes and return before any write

### 15.2 Auth package

- [ ] Create `app/auth/__init__.py` if missing
- [ ] Write `app/auth/social.py` with `SocialAuthProvider` enum, `exchange_google_code`, `exchange_github_code`, `exchange_apple_code` (all lazy `httpx`)
- [ ] `_STATE_STORE: dict[str, str] = {}` with `_store_state` / `_pop_state` helpers

### 15.3 Model + migration

- [ ] Write `app/models/social_account.py` with `class SocialAccount` (`provider`, `provider_user_id`, `user_id` FK, `email`, `created_at`)
- [ ] Add `UniqueConstraint("provider", "provider_user_id", name="uq_social_provider_uid")`
- [ ] `_patch_models_init` appends `from app.models.social_account import SocialAccount  # noqa: F401`
- [ ] Write `alembic/versions/0074_add_social_login.py` via `find_migration_head`

### 15.4 Schemas + routes + config

- [ ] Write `app/schemas/social.py` (`SocialCallbackRequest`, `SocialLoginResponse`)
- [ ] Write `app/api/routes/social_auth.py` with `GET /{provider}/login` + `GET /{provider}/callback`
- [ ] `_patch_routes_init` registers `social_auth_router`
- [ ] `_patch_config` injects `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `GITHUB_REDIRECT_URI`, `APPLE_CLIENT_ID`, `APPLE_CLIENT_SECRET`, `APPLE_REDIRECT_URI` into `class Settings` body

### 15.5 Validation + result

- [ ] `ast.parse` loop over every `.py` in `files_created`
- [ ] Return `ToolResult(status="success", files_created=..., files_modified=..., notes=..., next_steps=..., execution_time_ms=...)`
- [ ] `next_steps` includes `"alembic upgrade head"` and mentions setting `*_CLIENT_ID` env vars

---

## 16. References

| Document | Purpose |
|----------|---------|
| `adapt/extend/auth_access/add_social_login.py` | Source implementation |
| `adapt/contracts/__init__.py` | `ToolInput`, `ToolResult`, `validate_project_dir` |
| `adapt/contracts/prerequisites.py` | `ensure_prerequisites`, `Prereq` |
| `adapt/contracts/migration_helper.py` | `find_migration_head` |
| `specs/TOOL-075-add_passkey_auth.md` | Sibling auth tool |
| `specs/TOOL-076-add_sms_otp.md` | Sibling auth tool |
