# TOOL-075: add_passkey_auth

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_passkey_auth` |
| Category | EXTEND > Auth/Access |
| Complexity | High |
| Dependencies | FastAPI, SQLAlchemy 2.0, Alembic, pydantic-settings, py_webauthn (lazy), Redis (challenge storage) |
| Signature | `add_passkey_auth(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_passkey_auth", "description": "Add WebAuthn/FIDO2 passwordless passkey authentication to a FastAPI project.", "tags": ["extend", "auth_access"], "entry": "add_passkey_auth"}` |
| Files created (typical) | 7 — `app/models/passkey.py`, `app/auth/webauthn.py`, `app/auth/__init__.py`, `app/schemas/passkey.py`, `app/api/routes/passkeys.py`, `alembic/versions/0075_add_passkey_auth.py` |
| Files modified (typical) | 3 — `app/core/config.py`, `app/models/__init__.py`, `app/routes/__init__.py` |

---

## 2. Purpose

The `fastapi_add_passkey_auth` tool installs production-grade WebAuthn/FIDO2 passwordless passkey authentication into a FastAPI project. Password-based login has three failure modes that passkeys eliminate entirely: credential stuffing (passkeys are phishing-resistant), password reuse across sites (each passkey is site-scoped), and credential database leaks (public keys stored, never private keys). Apple, Google, and Microsoft's cross-device passkey sync means users are not locked to a single device.

This tool generates: (a) `app/models/passkey.py` — a `Passkey` SQLAlchemy model storing `credential_id` (LargeBinary), `public_key` (COSE-encoded CBOR, LargeBinary), `sign_count` (BigInteger, monotonically increasing for cloned-device detection), `aaguid` (authenticator model ID), `user_id` FK, `created_at`, and `last_used_at`; (b) `app/auth/webauthn.py` — a `WebAuthnManager` class with four methods (`generate_registration_options`, `verify_registration_response`, `generate_authentication_options`, `verify_authentication_response`) each importing `py_webauthn` lazily inside the method body so the app boots cleanly without it installed; (c) Pydantic schemas for all four endpoints; (d) four route handlers — `POST /passkeys/register/begin`, `POST /passkeys/register/complete`, `POST /passkeys/login/begin`, `POST /passkeys/login/complete`; (e) an in-process challenge store (`_CHALLENGE_STORE` dict with `_store_challenge` / `_pop_challenge`) that is production-replaceable with Redis; (f) an Alembic migration creating the `passkeys` table with a `uq_passkey_credential_id` unique constraint and `ix_passkeys_user_id` index.

Key design decisions: `py_webauthn` is imported lazily inside every `WebAuthnManager` method body — the class instantiates at module level but makes no `py_webauthn` calls until a ceremony begins, so missing the library is a runtime error only on the first actual passkey call; `credential_id` and `public_key` are stored as raw `LargeBinary` bytes (CBOR-encoded), not base64 strings, to avoid double-encoding bugs; `sign_count` is validated on every login — if the server's stored count is higher than the authenticator's reported count, the credential may be cloned and the login is rejected; `WEBAUTHN_RP_ID` defaults to `"localhost"` and must be set to the real domain (e.g., `"example.com"`) in production — the tool emits this explicitly in `next_steps`.

The challenge store (`_CHALLENGE_STORE` dict) maps `session_id → bytes(challenge)`. Challenges are written by `_store_challenge(session_id, challenge)` on the `begin` endpoints and consumed by `_pop_challenge(session_id)` on the `complete` endpoints — `dict.pop` is used to guarantee one-time use (INV-PK-06). For multi-replica deployments, `_CHALLENGE_STORE` must be replaced with a Redis key with TTL equal to `WEBAUTHN_CHALLENGE_TTL_SECONDS` (default 300 seconds). The tool emits this architectural note in `next_steps`.

The `aaguid` field (Authenticator Attestation Globally Unique Identifier) identifies the make and model of the authenticator (e.g., "Apple Touch ID", "YubiKey 5"). It is stored as a nullable `String(64)` and can be used by relying parties to build device-specific UX or to restrict which authenticator models are allowed. The tool stores it but does not enforce any policy on it — that is left to the application layer.

The registration complete handler calls `verify_registration_response`, extracts `(credential_id, credential_public_key, sign_count, aaguid)`, and inserts a `Passkey` row. The login complete handler calls `verify_authentication_response` with the stored `credential_public_key` and `sign_count`, receives a `new_sign_count`, updates the DB, and then mints a JWT. The JWT minting logic is expected to use an existing `create_access_token` function that the tool assumes is present in the project (it is a prerequisite of the base FastAPI template).

---

### Design Decisions Table

| Decision | Chosen Approach | Rejected Alternative | Reason |
|----------|----------------|---------------------|--------|
| `py_webauthn` import | Lazy inside all 4 method bodies | Top-level import | App boots without `py_webauthn` installed; `ImportError` only on first ceremony call |
| `credential_id` storage | Raw `LargeBinary` bytes | Base64 string `String(256)` | Avoids double-encoding bugs; `py_webauthn` works with raw bytes |
| Challenge store | In-process `_CHALLENGE_STORE` dict | Redis key with TTL | Simpler single-process starter; operator replaces with Redis for multi-replica |
| `sign_count` validation | Strict: reject if server count > authenticator count | Lenient: allow with warning | Strict mode catches cloned credential attacks proactively |
| `aaguid` storage | Nullable `String(64)` | Ignored entirely | Enables device-type-specific UX and authenticator allowlist policy |
| JWT minting | Calls existing `create_access_token` function | Generates JWT inline | Reuses project's established token format; no duplicate JWT logic |

---

### Generated file tree

```
project/ (after tool run)
├── app/
│   ├── auth/
│   │   ├── __init__.py                  # package marker (created if missing)
│   │   └── webauthn.py                  # WebAuthnManager (4 methods, all lazy-importing py_webauthn)
│   ├── models/
│   │   ├── __init__.py                  # MODIFIED: + Passkey import
│   │   └── passkey.py                   # Passkey model (credential_id, public_key, sign_count, aaguid)
│   ├── schemas/
│   │   └── passkey.py                   # 6 schema classes (begin/complete for register and login)
│   └── api/routes/
│       └── passkeys.py                  # 4 route handlers + _CHALLENGE_STORE helpers
├── app/core/
│   └── config.py                        # MODIFIED: + WEBAUTHN_RP_ID, WEBAUTHN_RP_NAME, WEBAUTHN_ORIGIN, WEBAUTHN_CHALLENGE_TTL_SECONDS
├── app/routes/
│   └── __init__.py                      # MODIFIED: + passkeys_router
└── alembic/versions/
    └── 0075_add_passkey_auth.py         # passkeys table + uq_passkey_credential_id + ix_passkeys_user_id
```

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | CI step budget |
| Files created | ≥ 6 | Model, auth module, `__init__`, schemas, routes, migration |
| Files modified | ≥ 2 | Config, models init, routes init |
| Max function LOC in generated code | ≤ 50 | Auditability |
| `POST /passkeys/register/begin` latency | < 10 ms | Pure option generation, no I/O |
| `POST /passkeys/login/begin` latency | < 10 ms | Pure option generation, no I/O |
| `POST /passkeys/register/complete` latency | < 50 ms | `py_webauthn` CBOR verification + DB INSERT |
| `POST /passkeys/login/complete` latency | < 50 ms | `py_webauthn` verification + sign_count UPDATE + JWT mint |
| `passkeys` lookup by `credential_id` | < 5 ms | `uq_passkey_credential_id` unique index scan |
| `passkeys` lookup by `user_id` | < 5 ms | `ix_passkeys_user_id` B-tree index scan |
| Challenge store `_pop_challenge` | < 1 ms | In-process dict pop |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── core/config.py       # No WEBAUTHN_* fields
│   ├── models/__init__.py   # No Passkey
│   └── routes/__init__.py   # No passkeys router
└── alembic/versions/
```

### 4.2 Passkey model: AFTER

```python
# app/models/passkey.py (excerpt)
class Passkey(Base):
    __tablename__ = "passkeys"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    credential_id: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    public_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sign_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    aaguid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint("credential_id", name="uq_passkey_credential_id"),)
```

### 4.3 WebAuthnManager: AFTER

```python
# app/auth/webauthn.py (excerpt)
class WebAuthnManager:
    def __init__(self, rp_id: str, rp_name: str, origin: str) -> None:
        self._rp_id = rp_id
        self._rp_name = rp_name
        self._origin = origin

    def generate_registration_options(self, user_id: str, username: str) -> dict:
        from py_webauthn import generate_registration_options  # lazy import
        from py_webauthn.helpers.structs import (
            AuthenticatorSelectionCriteria,
            ResidentKeyRequirement,
            UserVerificationRequirement,
        )
        options = generate_registration_options(
            rp_id=self._rp_id, rp_name=self._rp_name,
            user_id=user_id.encode(), user_name=username,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.REQUIRED,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
        )
        return _options_to_dict(options)

    def verify_registration_response(
        self, credential: dict, expected_challenge: bytes
    ) -> tuple[bytes, bytes, int, str | None]:
        from py_webauthn import verify_registration_response  # lazy import
        from py_webauthn.helpers.structs import AuthenticatorTransport
        verification = verify_registration_response(
            credential=credential,
            expected_challenge=expected_challenge,
            expected_rp_id=self._rp_id,
            expected_origin=self._origin,
        )
        return (
            verification.credential_id,
            verification.credential_public_key,
            verification.sign_count,
            str(verification.aaguid) if verification.aaguid else None,
        )

    def verify_authentication_response(
        self, credential: dict, expected_challenge: bytes,
        credential_public_key: bytes, current_sign_count: int,
    ) -> int:
        from py_webauthn import verify_authentication_response  # lazy import
        verification = verify_authentication_response(
            credential=credential,
            expected_challenge=expected_challenge,
            expected_rp_id=self._rp_id,
            expected_origin=self._origin,
            credential_public_key=credential_public_key,
            credential_current_sign_count=current_sign_count,
        )
        return verification.new_sign_count  # caller persists this
```

### 4.4 Challenge Store: AFTER

```python
# app/api/routes/passkeys.py (challenge helpers)
_CHALLENGE_STORE: dict[str, bytes] = {}

def _store_challenge(session_id: str, challenge: bytes) -> None:
    _CHALLENGE_STORE[session_id] = challenge

def _pop_challenge(session_id: str) -> bytes | None:
    return _CHALLENGE_STORE.pop(session_id, None)  # one-time use (INV-PK-06)
```

### 4.5 Routes: AFTER

```
POST /passkeys/register/begin    → generate_registration_options → store challenge → {options, session_id}
POST /passkeys/register/complete → pop challenge → verify_registration_response → insert Passkey row
POST /passkeys/login/begin       → generate_authentication_options → store challenge → {options, session_id}
POST /passkeys/login/complete    → pop challenge → verify_authentication_response → update sign_count → mint JWT
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | Tool is idempotent | `"Passkey" in app/models/passkey.py` → `status="no_op"` |
| QS-2 | `dry_run=True` writes zero files | Early return before any write |
| QS-3 | Every generated `.py` AST-parses | `ast.parse` loop after all writes |
| QS-4 | No generated function exceeds 50 LOC | Construction discipline + AST walk |
| QS-5 | `py_webauthn` imported lazily inside each method | `from py_webauthn import ...` inside method bodies only |
| QS-6 | `sign_count` validated on every login | `verify_authentication_response` returns new count; `_update_sign_count` persists it |
| QS-7 | Challenges stored per-session, popped on use | `_CHALLENGE_STORE.pop(session_id, None)` — one-time use |
| QS-8 | Credential public key stored as raw bytes | `LargeBinary` column; no base64 encoding in model |
| QS-9 | `WEBAUTHN_RP_ID` read from settings | `os.environ.get("WEBAUTHN_RP_ID", "localhost")` — never hardcoded |
| QS-10 | `execution_time_ms` positive on every return | `_elapsed_ms(start)` on all branches |
| QS-11 | Alembic migration chained to current head | `find_migration_head` used |
| QS-12 | `Passkey` registered in `app/models/__init__.py` | `_patch_models_init` idempotent append |

---

## 6. Completeness Criteria

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | Tool returns `status="success"` on fresh project | `result.status == "success"` | T-01 (`test_success_status`) |
| CC-02 | Second run returns `status="no_op"` | `r2.status == "no_op"`, empty lists | T-02 (`test_idempotent`) |
| CC-03 | `dry_run=True` writes zero bytes | Filesystem byte-identical before/after | T-03 (`test_dry_run`) |
| CC-04 | Tool creates at least 6 files | `len(files_created) >= 6`, each exists | T-04 (`test_files_created_count`) |
| CC-05 | Tool modifies at least 2 existing files | `len(files_modified) >= 2`, each exists | T-05 (`test_files_modified_count`) |
| CC-06 | Every generated `.py` AST-parses | `ast.parse` over all project `.py` | T-06 (`test_all_py_parse`) |
| CC-07 | No generated function exceeds 50 LOC | AST walk `app/`, `max_loc <= 50` | T-07 (`test_no_function_over_50_loc`) |
| CC-08 | `WEBAUTHN_RP_ID` inside `class Settings` | Substring + indent check | T-08 (`test_config_fields_patched`) |
| CC-09 | `Passkey` in `app/models/__init__.py` | `"Passkey" in content` | T-09 (`test_models_init_patched`) |
| CC-10 | Passkeys router registered in `app/routes/__init__.py` | `"passkey" in content.lower()` | T-10 (`test_routes_registered`) |
| CC-11 | `app/models/passkey.py` contains `class Passkey` with `sign_count` | File + substrings | T-11 (`test_passkey_model_created`) |
| CC-12 | `app/auth/webauthn.py` contains `WebAuthnManager` with lazy `py_webauthn` | File + `"from py_webauthn"` inside method | T-12 (`test_webauthn_manager_created`) |
| CC-13 | `app/api/routes/passkeys.py` contains all four route handlers | File + `"/register/begin"` + `"/login/complete"` | T-13 (`test_routes_created`) |
| CC-14 | Migration creates `passkeys` table with `uq_passkey_credential_id` | Migration file + substrings | T-14 (`test_migration_created`) |
| CC-15 | `execution_time_ms` positive | `result.execution_time_ms > 0` | T-15 (`test_execution_time_recorded`) |
| CC-16 | `next_steps` mentions `py_webauthn` install and `WEBAUTHN_RP_ID` | Lowercased join contains both | T-16 (`test_next_steps_mention_py_webauthn`) |

---

## 7. Definition of Done (DoD)

- [ ] All 16 Completeness Criteria verified by `test_add_passkey_auth.py`
- [ ] `add_passkey_auth.py` runs `ast.parse` on every created `.py` before returning success
- [ ] Fingerprint check `"Passkey" in model_file.read_text()` returns `status="no_op"` on second run
- [ ] `dry_run=True` returns `status="success"` with empty `files_created` and `files_modified`
- [ ] `py_webauthn` imported lazily inside all four `WebAuthnManager` method bodies — no module-level import
- [ ] `sign_count` validated and updated on every successful authentication (INV-PK-05)
- [ ] Challenges stored via `_store_challenge` and consumed via `_pop_challenge` exactly once (INV-PK-06)
- [ ] `WEBAUTHN_RP_ID` defaults to `"localhost"` in config; `next_steps` instructs operator to set real domain
- [ ] `Passkey` model has `uq_passkey_credential_id` unique constraint and `ix_passkeys_user_id` index
- [ ] Migration chained via `find_migration_head`; migration file creates `passkeys` table
- [ ] `execution_time_ms` set on every return path including `no_op` and `error`

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-PK-01 | Tool ALWAYS idempotent on second invocation | Fingerprint check → `no_op` | T-02 |
| INV-PK-02 | `dry_run=True` NEVER writes to disk | Early return before any write | T-03 |
| INV-PK-03 | Every generated `.py` MUST parse as valid Python | `ast.parse` loop | T-06 |
| INV-PK-04 | `py_webauthn` MUST be lazy-imported inside method bodies | `from py_webauthn import` inside functions only | T-12 |
| INV-PK-05 | `sign_count` MUST be validated on every login | `verify_authentication_response` returns `new_sign_count` | T-11 |
| INV-PK-06 | Challenge MUST be consumed exactly once | `_CHALLENGE_STORE.pop(session_id, None)` | T-13 |
| INV-PK-07 | `credential_id` MUST have unique constraint | `UniqueConstraint("credential_id", ...)` in model + migration | T-11, T-14 |
| INV-PK-08 | `execution_time_ms` MUST be positive on every return path | `_elapsed_ms(start)` on all branches | T-15 |

---

## 9. User Stories

**US-01: Install passkey auth into a clean project**
- **Given:** FastAPI project with base prereqs
- **When:** `add_passkey_auth(ToolInput(project_dir=...))`
- **Then:** `status="success"`, `files_created >= 6`, `files_modified >= 2` (CC-01, CC-04, CC-05)

**US-02: Re-run on already-configured project**
- **Given:** `app/models/passkey.py` contains `"Passkey"`
- **When:** Tool invoked again
- **Then:** `status="no_op"`, empty lists (CC-02, INV-PK-01)

**US-03: Begin passkey registration ceremony**
- **Given:** User ID + username provided
- **When:** `POST /passkeys/register/begin` called
- **Then:** Returns `{options, session_id}`; challenge stored in `_CHALLENGE_STORE`

**US-04: Complete passkey registration**
- **Given:** Client calls `navigator.credentials.create()` and POSTs the response
- **When:** `POST /passkeys/register/complete` with `session_id` + `credential`
- **Then:** Challenge popped (one-time use); `verify_registration_response` called; `Passkey` row inserted

**US-05: Detect cloned credential via sign_count**
- **Given:** Attacker cloned a passkey and has lower sign_count
- **When:** Authentication response has sign_count lower than stored
- **Then:** `py_webauthn.verify_authentication_response` raises `ValueError`; login rejected (INV-PK-05)

**US-06: App boots without py_webauthn installed**
- **Given:** `py_webauthn` not in virtualenv
- **When:** FastAPI app starts; no passkey endpoint is called
- **Then:** No `ImportError` at startup; error occurs only when ceremony begins (INV-PK-04)

**US-07: dry_run preview**
- **Given:** Fresh fixture project
- **When:** `add_passkey_auth(ToolInput(dry_run=True))`
- **Then:** `status="success"`, filesystem unchanged (CC-03, INV-PK-02)

**US-08: Config fields bound from environment**
- **Given:** `.env` has `WEBAUTHN_RP_ID=example.com`
- **When:** `Settings()` instantiated
- **Then:** `settings.WEBAUTHN_RP_ID == "example.com"` (CC-08)

**US-09: Install passkey auth alongside social login**
- **Given:** `add_social_login` already installed
- **When:** `add_passkey_auth(ToolInput(project_dir=...))`
- **Then:** Both auth systems coexist; no conflict; shared `User` table; `Passkey` model adds separate FK to users (Interaction Matrix)

**US-10: Migration creates passkeys table with index**
- **Given:** Fresh fixture project with `alembic/versions/`
- **When:** Tool runs
- **Then:** Migration file created; `op.create_table("passkeys")` with `uq_passkey_credential_id` + `ix_passkeys_user_id` (CC-14)

**US-11: login/complete mints JWT after sign_count update**
- **Given:** Successful `verify_authentication_response` returns `new_sign_count=5`
- **When:** Route handler completes
- **Then:** DB updated with `sign_count=5`; JWT access token returned in response

**US-12: App with py_webauthn installed at registration time**
- **Given:** `py_webauthn` installed in virtualenv; user initiates registration
- **When:** `POST /passkeys/register/begin` called
- **Then:** `from py_webauthn import generate_registration_options` executes; options returned; no `ImportError`

---

## 10. Test Plan

All 16 tests live in `adapt/extend/auth_access/test_add_passkey_auth.py`.

### 10.1 Category A — Tool execution (T-01 .. T-05)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | `test_success_status` | Fixture `pk_t01` | `add_passkey_auth(ToolInput(project_dir))` | `result.status == "success"` |
| T-02 | `test_idempotent` | Fixture `pk_t02`; run once | Run again | `r2.status == "no_op"`, empty lists |
| T-03 | `test_dry_run` | Fixture `pk_t03` | `add_passkey_auth(ToolInput(dry_run=True))` | `status == "success"`; no files written |
| T-04 | `test_files_created_count` | Fixture `pk_t04` | Run tool | `len(files_created) >= 6`, each path exists |
| T-05 | `test_files_modified_count` | Fixture `pk_t05` | Run tool | `len(files_modified) >= 2`, each path exists |

### 10.2 Category B — Generated code quality (T-06 .. T-10)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-06 | `test_all_py_parse` | Fixture `pk_t06`; run tool | `ast.parse` every `.py` | No `SyntaxError` |
| T-07 | `test_no_function_over_50_loc` | Fixture `pk_t07`; run tool | AST walk `app/` | `max_loc <= 50` |
| T-08 | `test_config_fields_patched` | Fixture `pk_t08`; run tool | Read `app/core/config.py` | Contains `WEBAUTHN_RP_ID` with 4-space indent |
| T-09 | `test_models_init_patched` | Fixture `pk_t09`; run tool | Read `app/models/__init__.py` | Contains `"Passkey"` |
| T-10 | `test_routes_registered` | Fixture `pk_t10`; run tool | Read `app/routes/__init__.py` | Contains `"passkey"` (case-insensitive) |

### 10.3 Category C — Domain-specific modules (T-11 .. T-14)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-11 | `test_passkey_model_created` | Fixture `pk_t11`; run tool | Read `app/models/passkey.py` | `"class Passkey"`, `"sign_count"`, `"uq_passkey_credential_id"` present |
| T-12 | `test_webauthn_manager_created` | Fixture `pk_t12`; run tool | Read `app/auth/webauthn.py` | `"WebAuthnManager"` + `"from py_webauthn"` inside method body |
| T-13 | `test_routes_created` | Fixture `pk_t13`; run tool | Read `app/api/routes/passkeys.py` | `"/register/begin"` + `"/login/complete"` present |
| T-14 | `test_migration_created` | Fixture `pk_t14`; run tool | Scan `alembic/versions/` | File with `"passkeys"` + `"uq_passkey_credential_id"` |

### 10.4 Category D — Meta (T-15 .. T-16)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-15 | `test_execution_time_recorded` | Fixture `pk_t15`; run tool | `result.execution_time_ms` | `> 0` |
| T-16 | `test_next_steps_mention_py_webauthn` | Fixture `pk_t16`; run tool | Lowercase-join `next_steps` | Contains `"py_webauthn"` and `"webauthn_rp_id"` |

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| `add_social_login` (TOOL-074) | No | ✅ Compatible | Multiple auth methods; shared `User` table; `SocialAccount` and `Passkey` are separate models |
| `add_sms_otp` (TOOL-076) | No | ✅ Compatible | Passkeys and SMS OTP are independent auth factors; either can be offered as fallback |
| `add_multi_tenancy` (TOOL-008) | No | ⚠️ Caveat | `Passkey.user_id` cascades from `User`; no `tenant_id` on passkeys — scoping handled at `User` level |
| `add_rbac` (TOOL-012) | Yes — RBAC AFTER | ✅ Compatible | Passkey login mints JWT; RBAC enforces per-endpoint permissions after JWT validation |
| `add_cache_layer` (TOOL-021) | No | ⚠️ Caveat | In-process `_CHALLENGE_STORE` dict breaks on multi-replica; move to Redis when `add_cache_layer` is installed |
| `add_arq_worker` (TOOL-053) | No | ⚠️ Caveat | Challenge TTL cleanup can be offloaded to arq periodic task |

---

## 11.1 Anti-patterns This Tool Prevents

| Anti-pattern | How this tool avoids it |
|-------------|------------------------|
| Storing OAuth2 access tokens instead of passkey public keys | Stores `credential_id` (bytes) and `public_key` (bytes) only — no access token exists in passkey flow |
| Not validating `sign_count` on login | `verify_authentication_response` enforces `sign_count` check; cloned credentials rejected |
| Module-level `py_webauthn` import crashing app at boot | All imports inside method bodies (INV-PK-04) |
| Using same challenge twice | `_pop_challenge` uses `dict.pop` — key destroyed on first use (INV-PK-06) |
| Hardcoded `WEBAUTHN_RP_ID` to `localhost` in production | `next_steps` explicitly instructs operator to set `WEBAUTHN_RP_ID=yourdomain.com` |
| Storing `credential_id` as base64 string (double-encoding) | `LargeBinary` column stores raw bytes directly |

---

## 12. Rollback Procedure

### 12.1 Code rollback

```bash
git checkout HEAD -- app/core/config.py app/models/__init__.py app/routes/__init__.py
rm -f app/models/passkey.py app/auth/webauthn.py app/schemas/passkey.py \
      app/api/routes/passkeys.py
find alembic/versions/ -name '*passkey*' -delete
# If app/auth/ is now empty, remove the directory too:
rmdir app/auth 2>/dev/null || true
```

### 12.2 Database rollback

```bash
alembic downgrade -1   # drops passkeys table
```

> **Note:** Downgrading will drop all registered passkeys. Users will need to re-register passkeys after re-running the migration forward.

---

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-01 | Invalid `project_dir` | `status="error"` |
| EC-02 | Missing prerequisites | `status="error"` with list |
| EC-03 | `app/models/passkey.py` exists with `"Passkey"` | `status="no_op"` |
| EC-04 | `dry_run=True` | Notes only, zero writes |
| EC-05 | `app/core/config.py` already has `WEBAUTHN_RP_ID` | `_patch_config` early-returns |
| EC-06 | `alembic/versions/` missing | Migration skipped |
| EC-07 | Challenge popped but verification fails | `HTTPException 400` returned; challenge not re-inserted |
| EC-08 | `sign_count` mismatch on login | `py_webauthn` raises `ValueError`; handler returns 400 |
| EC-09 | `find_migration_head` returns `None` | Falls back to `"0001_initial"` |
| EC-10 | Generated file has `SyntaxError` | `ast.parse` raises; tool returns `status="error"` |

---

## 14. Acceptance Criteria (Final Sign-off)

1. ✅ All 16 Completeness Criteria verified via `test_add_passkey_auth.py` passing
2. ✅ Tool execution time < 5 s
3. ✅ Second invocation returns `status="no_op"` (INV-PK-01)
4. ✅ `dry_run=True` produces zero writes (INV-PK-02)
5. ✅ Every generated `.py` AST-parses (INV-PK-03)
6. ✅ `py_webauthn` lazy-imported inside all four method bodies (INV-PK-04)
7. ✅ `sign_count` validated on login (INV-PK-05)
8. ✅ Challenge consumed exactly once (INV-PK-06)
9. ✅ `credential_id` unique constraint present (INV-PK-07)
10. ✅ `execution_time_ms` positive on all paths (INV-PK-08)

---

## 15. Implementation Checklist (Ultra-granular)

- [ ] `validate_project_dir` passes
- [ ] `ensure_prerequisites(BASE_MODEL, MODELS_INIT, CONFIG_SETTINGS, ROUTES_INIT, ALEMBIC_VERSIONS)` passes
- [ ] Fingerprint check on `app/models/passkey.py`
- [ ] `dry_run` early return
- [ ] Write `app/models/passkey.py` with `Passkey` model (`credential_id`, `public_key`, `sign_count`, `aaguid`, `user_id`, `created_at`, `last_used_at`, unique constraint)
- [ ] `_patch_models_init` appends `Passkey` import
- [ ] Write `app/auth/webauthn.py` with `WebAuthnManager` (lazy `py_webauthn` in all four methods, `_options_to_dict`, `_to_json`)
- [ ] Create `app/auth/__init__.py` if missing
- [ ] Write `app/schemas/passkey.py` with all six schema classes
- [ ] Write `app/api/routes/passkeys.py` with four route handlers + `_CHALLENGE_STORE` helpers
- [ ] `_patch_routes_init` registers passkeys router
- [ ] Write `alembic/versions/0075_add_passkey_auth.py` via `find_migration_head`
- [ ] `_patch_config` injects `WEBAUTHN_RP_ID`, `WEBAUTHN_RP_NAME`, `WEBAUTHN_ORIGIN`, `WEBAUTHN_CHALLENGE_TTL_SECONDS`
- [ ] `ast.parse` loop over all created `.py` files
- [ ] Return `ToolResult` with `next_steps` mentioning `pip install py_webauthn` and `WEBAUTHN_RP_ID`

---

## 16. References

| Document | Purpose |
|----------|---------|
| `adapt/extend/auth_access/add_passkey_auth.py` | Source implementation (~1027 lines) |
| `adapt/contracts/__init__.py` | `ToolInput`, `ToolResult` |
| `adapt/contracts/migration_helper.py` | `find_migration_head` |
| `specs/TOOL-074-add_social_login.md` | Sibling auth tool (Google/GitHub/Apple OAuth2) |
| `specs/TOOL-076-add_sms_otp.md` | Sibling auth tool (SMS OTP as passkey fallback) |
| [WebAuthn Level 3 spec](https://www.w3.org/TR/webauthn-3/) | FIDO2/WebAuthn protocol reference |
| [py_webauthn library](https://github.com/duo-labs/py_webauthn) | Python WebAuthn implementation (lazy-imported) |
