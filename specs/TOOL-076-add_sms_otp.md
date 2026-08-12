---
spec_id: "TOOL-076"
tool_name: "add_sms_otp"
version: "1.0.0"
status: "ratified"
invariants:
  - "INV-OTP-01"
  - "INV-OTP-02"
  - "INV-OTP-03"
  - "INV-OTP-04"
  - "INV-OTP-05"
  - "INV-OTP-06"
  - "INV-OTP-07"
  - "INV-OTP-08"
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
quality_standards:
  - "QS-1"
  - "QS-10"
  - "QS-11"
  - "QS-12"
  - "QS-13"
  - "QS-14"
  - "QS-2"
  - "QS-3"
  - "QS-4"
  - "QS-5"
  - "QS-6"
  - "QS-7"
  - "QS-8"
  - "QS-9"
test_plan:
  - "T-01"
  - "T-02"
  - "T-03"
  - "T-04"
  - "T-05"
  - "T-06"
  - "T-07"
  - "T-08"
  - "T-09"
  - "T-10"
  - "T-11"
  - "T-12"
  - "T-13"
  - "T-14"
  - "T-15"
  - "T-16"
tags:
  - "performance"
  - "security"
  - "data"
  - "resiliency"
  - "realtime"
---
# TOOL-076: add_sms_otp

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_sms_otp` |
| Category | EXTEND > Auth/Access |
| Complexity | Medium |
| Dependencies | FastAPI, SQLAlchemy 2.0, Alembic, pydantic-settings, twilio (lazy) or vonage (lazy) |
| Signature | `add_sms_otp(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path) and `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_sms_otp", "description": "Add SMS OTP authentication via Twilio/Vonage with rate limiting to a FastAPI project.", "tags": ["extend", "auth_access"], "entry": "add_sms_otp"}` |
| Files created (typical) | 6 — `app/models/otp_code.py`, `app/auth/sms_otp.py`, `app/auth/__init__.py`, `app/schemas/otp.py`, `app/api/routes/sms_auth.py`, `alembic/versions/0076_add_sms_otp.py` |
| Files modified (typical) | 3 — `app/core/config.py`, `app/models/__init__.py`, `app/routes/__init__.py` |

---

## 2. Purpose

The `fastapi_add_sms_otp` tool installs production-grade SMS one-time password authentication via Twilio (default) or Vonage into a FastAPI project. SMS OTP is the most widely deployed second factor in consumer applications — it is universally understood, requires no app install, and works on feature phones. The failure modes teams encounter when hand-rolling it are: OTP generation via `random.randint` (cryptographically insecure), storing codes in Redis without a DB audit trail (no replay evidence), no rate limiting (unlimited SMS blast to any number), and `str(code) == submitted_code` comparison (timing attack vector).

This tool generates: (a) `app/models/otp_code.py` — an `OtpCode` SQLAlchemy model (`phone` String(20) indexed, `code` String(10), `expires_at`, `verified` Boolean, `created_at`); OTP rows are never deleted — verified and expired codes remain for audit; (b) `app/auth/sms_otp.py` — `generate_otp` using `secrets.randbelow` (cryptographically secure), `verify_otp` using `secrets.compare_digest` (constant-time), `send_sms` with lazy Twilio/Vonage dispatch (`SMS_PROVIDER` env var controls which SDK is loaded), and `_mask_phone` (last 4 digits for safe logging); (c) Pydantic schemas (`OtpSendRequest`, `OtpSendResponse`, `OtpVerifyRequest`, `OtpVerifyResponse`); (d) two route handlers — `POST /auth/sms/send` (generate + dispatch OTP, DB-enforced rate limit) and `POST /auth/sms/verify` (constant-time check + mark verified); (e) `_enforce_rate_limit` that counts `otp_codes` rows per phone in the last `OTP_RATE_LIMIT_WINDOW_SECONDS` (default 3600) and raises HTTP 429 when count `>= OTP_RATE_LIMIT_MAX` (default 5) — no Redis required; (f) an Alembic migration creating `otp_codes`.

Key design decisions: rate limiting is DB-enforced via a `COUNT(*)` query (no Redis dependency) so the feature works in any deployment topology; phone numbers are stored in E.164 format (`String(20)` — `+15555550100` is 12 chars; max E.164 is 15 + country code prefix); OTP codes use `secrets.randbelow(10**n)` then `str(...).zfill(n)` to produce a zero-padded n-digit string that is both cryptographically secure and uniform (no modulo bias unlike `random.randint`); Twilio and Vonage SDKs are always imported inside the respective `_send_via_*` body so the app boots without either installed — the `ImportError` only fires when the provider's `_send_via_*` function is actually called; the tool defaults to `SMS_PROVIDER=twilio` and the `next_steps` list instructs the operator to install the correct SDK; OTP rows are never deleted — verified and expired codes are retained for audit trails.

The `_mask_phone` helper (`return f"***{phone[-4:]}"`) ensures full phone numbers are never written to application logs, guarding against log scraping attacks. The `expires_at` column stores a UTC timestamp computed as `datetime.utcnow() + timedelta(seconds=OTP_EXPIRY_SECONDS)` — the verify handler filters with `OtpCode.expires_at > datetime.utcnow()` to reject stale codes without requiring a background cleanup job.

---

### Design Decisions Table

| Decision | Chosen Approach | Rejected Alternative | Reason |
|----------|----------------|---------------------|--------|
| OTP generation | `secrets.randbelow(10**n)` + `zfill(n)` | `random.randint` | `secrets` module uses OS CSPRNG; `random` is not cryptographically secure |
| OTP comparison | `secrets.compare_digest` | `stored == submitted` | Constant-time comparison prevents timing attacks |
| Rate limiting | DB `COUNT(*)` query | Redis counter with TTL | No Redis dependency; works in any deployment topology |
| SMS dispatch | Lazy import of `twilio.rest` / `vonage` inside `_send_via_*` | Top-level import | App boots without either SDK installed; `ImportError` only on first SMS call |
| OTP storage | `otp_codes` table (never deleted) | Redis key with TTL | Permanent audit trail; expired codes remain for forensics |
| Phone logging | `_mask_phone` (last 4 digits) | Full phone in logs | Guards against phone number exfiltration via log scraping |
| Provider selection | `SMS_PROVIDER` env var at runtime | Compile-time configuration | Allows switching providers without code changes |

---

### Generated file tree

```
project/ (after tool run)
├── app/
│   ├── auth/
│   │   ├── __init__.py                  # package (created if missing)
│   │   └── sms_otp.py                   # generate_otp, verify_otp, send_sms, _mask_phone
│   ├── models/
│   │   ├── __init__.py                  # MODIFIED: + OtpCode import
│   │   └── otp_code.py                  # OtpCode SQLAlchemy model
│   ├── schemas/
│   │   └── otp.py                       # OtpSendRequest/Response, OtpVerifyRequest/Response
│   └── api/routes/
│       └── sms_auth.py                  # POST /auth/sms/send, POST /auth/sms/verify
├── app/core/
│   └── config.py                        # MODIFIED: + 8 SMS/OTP config fields
├── app/routes/
│   └── __init__.py                      # MODIFIED: + sms_auth_router
└── alembic/versions/
    └── 0076_add_sms_otp.py              # otp_codes table + ix_otp_codes_phone
```

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | CI step budget |
| Files created | ≥ 5 | Model, service, schemas, routes, migration |
| Files modified | ≥ 2 | Config, models init, routes init |
| Max function LOC in generated code | ≤ 50 | Auditability |
| `POST /auth/sms/send` (excluding SMS dispatch) | < 20 ms | DB rate-limit check + `OtpCode` insert + flush |
| SMS dispatch via Twilio REST API | < 2 s | Network-bound; one HTTPS call to Twilio endpoint |
| `POST /auth/sms/verify` latency | < 10 ms | Single indexed row lookup + `secrets.compare_digest` |
| Rate limit `COUNT(*)` SQL | < 5 ms | `ix_otp_codes_phone` index makes this fast |
| `generate_otp(6)` | < 1 ms | Pure `secrets.randbelow` + `zfill` in memory |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── core/config.py       # No TWILIO_* or OTP_* fields
│   ├── models/__init__.py   # No OtpCode
│   └── routes/__init__.py   # No sms_auth router
└── alembic/versions/
```

### 4.2 OtpCode model: AFTER

```python
class OtpCode(Base):
    __tablename__ = "otp_codes"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    phone: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(10), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

### 4.3 SMS OTP service: AFTER

```python
# app/auth/sms_otp.py (excerpt)
def generate_otp(length: int | None = None) -> str:
    """Generate a zero-padded n-digit OTP using cryptographically secure randomness."""
    n = length or int(os.environ.get("OTP_LENGTH", "6"))
    return str(secrets.randbelow(10 ** n)).zfill(n)  # INV-OTP-04

def verify_otp(stored_code: str, submitted_code: str) -> bool:
    """Constant-time OTP comparison to prevent timing attacks."""
    return secrets.compare_digest(stored_code.strip(), submitted_code.strip())  # INV-OTP-05

async def send_sms(phone: str, message: str) -> None:
    provider = os.environ.get("SMS_PROVIDER", "twilio").lower()
    if provider == "twilio":
        await _send_via_twilio(phone, message)  # lazy import inside
    elif provider == "vonage":
        await _send_via_vonage(phone, message)  # lazy import inside
    else:
        raise RuntimeError(f"Unknown SMS_PROVIDER: {provider!r}")

async def _send_via_twilio(phone: str, message: str) -> None:
    import twilio.rest  # lazy — INV-OTP-06
    sid = os.environ["TWILIO_ACCOUNT_SID"]
    token = os.environ["TWILIO_AUTH_TOKEN"]
    from_number = os.environ["TWILIO_FROM_NUMBER"]
    client = twilio.rest.Client(sid, token)
    client.messages.create(body=message, from_=from_number, to=phone)

def _mask_phone(phone: str) -> str:
    """Return last 4 digits only for safe logging."""
    return f"***{phone[-4:]}" if len(phone) >= 4 else "****"
```

### 4.4 Rate Limit Enforcement: AFTER

```python
# app/api/routes/sms_auth.py (excerpt)
async def _enforce_rate_limit(phone: str, session: AsyncSession) -> None:
    """DB-enforced rate limit — no Redis required (INV-OTP-07)."""
    window_seconds = int(os.environ.get("OTP_RATE_LIMIT_WINDOW_SECONDS", "3600"))
    max_attempts = int(os.environ.get("OTP_RATE_LIMIT_MAX", "5"))
    window_start = datetime.utcnow() - timedelta(seconds=window_seconds)
    result = await session.execute(
        select(func.count()).select_from(OtpCode)
        .where(OtpCode.phone == phone, OtpCode.created_at >= window_start)
    )
    count = result.scalar() or 0
    if count >= max_attempts:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
```

### 4.5 Routes: AFTER

```
POST /auth/sms/send    → _enforce_rate_limit → generate_otp → OtpCode insert → send_sms
POST /auth/sms/verify  → query latest unverified unexpired OtpCode → verify_otp (constant-time) → mark verified=True
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | Tool is idempotent | `"OtpCode" in app/models/otp_code.py` → `status="no_op"` |
| QS-2 | `dry_run=True` writes zero files | Early return before any `dest.write_text(...)` |
| QS-3 | Every generated `.py` AST-parses | `ast.parse` loop after all writes |
| QS-4 | No generated function exceeds 50 LOC | Construction discipline + AST walk in tests |
| QS-5 | OTP generated with `secrets.randbelow` | Cryptographically secure; never `random.randint` (INV-OTP-04) |
| QS-6 | OTP comparison via `secrets.compare_digest` | Constant-time; never `==` string compare (INV-OTP-05) |
| QS-7 | Twilio and Vonage SDKs imported lazily | `import twilio.rest` inside `_send_via_twilio` body only; same for vonage (INV-OTP-06) |
| QS-8 | Rate limit is DB-enforced without Redis | `COUNT(*) WHERE phone=? AND created_at>=?` with index (INV-OTP-07) |
| QS-9 | Phone stored in E.164 format | `String(20)` column; schema documents E.164 requirement |
| QS-10 | Phone masked in all log lines | `_mask_phone(phone)` → `"***NNNN"` |
| QS-11 | `execution_time_ms` positive on all return paths | `_elapsed_ms(start)` on all branches (INV-OTP-08) |
| QS-12 | Alembic migration chained to current head | `find_migration_head` used |
| QS-13 | OTP rows never deleted | `OtpCode` rows marked `verified=True` or left as expired; retained for audit |
| QS-14 | `expires_at` computed as UTC | `datetime.utcnow() + timedelta(seconds=OTP_EXPIRY_SECONDS)` |

---

## 6. Completeness Criteria

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | Tool returns `status="success"` on fresh project | `result.status == "success"` | T-01 (`test_success_status`) |
| CC-02 | Second run returns `status="no_op"` | `r2.status == "no_op"`, both lists empty | T-02 (`test_idempotent`) |
| CC-03 | `dry_run=True` writes zero bytes | Snapshot dict before/after; byte-identical | T-03 (`test_dry_run`) |
| CC-04 | Tool creates at least 5 files | `len(files_created) >= 5`, each path exists on disk | T-04 (`test_files_created_count`) |
| CC-05 | Tool modifies at least 2 existing files | `len(files_modified) >= 2`, each path exists | T-05 (`test_files_modified_count`) |
| CC-06 | Every generated `.py` AST-parses cleanly | `ast.parse` over all `.py` under `app/` | T-06 (`test_all_py_parse`) |
| CC-07 | No generated function exceeds 50 LOC | AST `FunctionDef` walk, `max_loc <= 50` | T-07 (`test_no_function_over_50_loc`) |
| CC-08 | `TWILIO_ACCOUNT_SID` inside `class Settings` with 4-space indent | Substring + indent check on `app/core/config.py` | T-08 (`test_config_fields_patched`) |
| CC-09 | `OtpCode` registered in `app/models/__init__.py` | `"OtpCode" in content` | T-09 (`test_models_init_patched`) |
| CC-10 | SMS auth router registered in `app/routes/__init__.py` | `"sms" in content.lower()` | T-10 (`test_routes_registered`) |
| CC-11 | `app/models/otp_code.py` contains `class OtpCode` with `verified` column | File exists + `"class OtpCode"` + `"verified"` | T-11 (`test_otp_model_created`) |
| CC-12 | `app/auth/sms_otp.py` contains `generate_otp`, `verify_otp`, `send_sms`; `import twilio.rest` inside function body | File + substrings; AST confirms no module-level twilio import | T-12 (`test_sms_otp_service`) |
| CC-13 | `app/api/routes/sms_auth.py` has `/send`, `/verify`, `_enforce_rate_limit` | File + substrings | T-13 (`test_routes_created`) |
| CC-14 | Alembic migration creates `otp_codes` with `ix_otp_codes_phone` index | Migration file + `"otp_codes"` + `"ix_otp_codes_phone"` | T-14 (`test_migration_created`) |
| CC-15 | `execution_time_ms` positive | `result.execution_time_ms > 0` | T-15 (`test_execution_time_recorded`) |
| CC-16 | `next_steps` mentions `pip install twilio` and `alembic` | Lowercased join contains `"twilio"` and `"alembic"` | T-16 (`test_next_steps_mention_twilio_and_alembic`) |

---

## 7. Definition of Done (DoD)

- [ ] All 16 Completeness Criteria verified by `test_add_sms_otp.py`
- [ ] `ast.parse` runs on every created `.py` before success return
- [ ] `"OtpCode" in model_file.read_text()` → `status="no_op"` on second run
- [ ] `dry_run=True` returns `status="success"` with empty `files_created` and `files_modified`
- [ ] `secrets.randbelow(10**n)` for OTP generation — never `random.randint` (INV-OTP-04)
- [ ] `secrets.compare_digest` for OTP verification — never `==` string comparison (INV-OTP-05)
- [ ] `import twilio.rest` / `import vonage` inside `_send_via_*` function bodies only (INV-OTP-06)
- [ ] Rate limit enforced via `COUNT(*) WHERE phone=? AND created_at>=?` — no Redis (INV-OTP-07)
- [ ] Phone logged only via `_mask_phone` (shows last 4 digits)
- [ ] Migration chained via `find_migration_head`; creates `otp_codes` with `ix_otp_codes_phone` index
- [ ] `execution_time_ms` set on all return paths (INV-OTP-08)

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-OTP-01 | Tool ALWAYS idempotent | Fingerprint → `no_op` | T-02 |
| INV-OTP-02 | `dry_run=True` NEVER writes | Early return | T-03 |
| INV-OTP-03 | Every generated `.py` MUST parse | `ast.parse` loop | T-06 |
| INV-OTP-04 | OTP MUST use `secrets.randbelow` | `secrets.randbelow(10 ** n)` in `generate_otp` | T-12 |
| INV-OTP-05 | Comparison MUST be constant-time | `secrets.compare_digest` in `verify_otp` | T-12 |
| INV-OTP-06 | SMS SDKs MUST be lazy-imported | `import twilio.rest` inside `_send_via_twilio` | T-12 |
| INV-OTP-07 | Rate limit MUST be DB-enforced | `COUNT(*) WHERE phone=? AND created_at>=?` | T-13 |
| INV-OTP-08 | `execution_time_ms` MUST be positive | `_elapsed_ms(start)` on all branches | T-15 |

---

## 9. User Stories

**US-01: Install SMS OTP into a clean project**
- **Given:** FastAPI project with base prereqs
- **When:** `add_sms_otp(ToolInput(project_dir=...))`
- **Then:** `status="success"`, `files_created >= 5`, `files_modified >= 2` (CC-01, CC-04, CC-05)

**US-02: Send OTP to a phone number**
- **Given:** `POST /auth/sms/send` with `{phone: "+15555550100"}`
- **When:** Under rate limit
- **Then:** `OtpCode` row created with `expires_at = now() + OTP_EXPIRY_SECONDS`; SMS dispatched

**US-03: Rate limit protects against SMS blast**
- **Given:** Phone has already received 5 OTPs in the last hour
- **When:** Sixth `POST /auth/sms/send` request arrives
- **Then:** `HTTP 429` returned; no SMS sent; no new `OtpCode` row inserted (INV-OTP-07)

**US-04: Verify correct OTP**
- **Given:** Valid unverified unexpired `OtpCode` row exists
- **When:** `POST /auth/sms/verify` with correct code
- **Then:** `verified=True` set on row; `OtpVerifyResponse(verified=True, phone=...)` returned

**US-05: Reject expired OTP**
- **Given:** `OtpCode` row with `expires_at < now()`
- **When:** Verify request arrives
- **Then:** `HTTP 400 "Invalid or expired OTP code"`

**US-06: Reject wrong OTP (constant-time)**
- **Given:** Valid unexpired `OtpCode` row; submitted wrong code
- **When:** `verify_otp(stored, submitted)` called
- **Then:** `secrets.compare_digest` returns `False`; `HTTP 400` returned (INV-OTP-05)

**US-07: Switch provider to Vonage**
- **Given:** `SMS_PROVIDER=vonage` in env
- **When:** `send_sms(phone, message)` called
- **Then:** `_send_via_vonage` invoked; `import vonage` inside that function; `twilio` not imported

**US-08: dry_run preview**
- **Given:** Fresh fixture project
- **When:** `add_sms_otp(ToolInput(dry_run=True))`
- **Then:** `status="success"`, filesystem unchanged (CC-03)

**US-09: Re-run tool on already-configured project**
- **Given:** `app/models/otp_code.py` already contains `"OtpCode"`
- **When:** Tool invoked again
- **Then:** `status="no_op"`, empty lists (CC-02, INV-OTP-01)

**US-10: OTP masked in logs**
- **Given:** Phone number `+15555550123`
- **When:** Any log line emitted by `send_sms` or route handler
- **Then:** Phone appears as `***0123` via `_mask_phone`; full number never logged

**US-11: Migration creates otp_codes table with phone index**
- **Given:** Fresh fixture project with `alembic/versions/`
- **When:** Tool runs
- **Then:** Migration file created; table `otp_codes` with `ix_otp_codes_phone` index (CC-14)

**US-12: OTP length configurable**
- **Given:** `OTP_LENGTH=8` in env
- **When:** `generate_otp()` called
- **Then:** Returns 8-digit zero-padded string (e.g., `"04293847"`) using `secrets.randbelow(10**8)`

---

## 10. Test Plan

All 16 tests live in `adapt/extend/auth_access/test_add_sms_otp.py`.

### 10.1 Category A — Tool execution (T-01 .. T-05)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | `test_success_status` | Fixture `otp_t01` | `add_sms_otp(ToolInput(project_dir))` | `result.status == "success"` |
| T-02 | `test_idempotent` | Fixture `otp_t02`; run once | Run again | `r2.status == "no_op"`, empty lists |
| T-03 | `test_dry_run` | Fixture `otp_t03` | `add_sms_otp(ToolInput(dry_run=True))` | `status == "success"`; no files written |
| T-04 | `test_files_created_count` | Fixture `otp_t04` | Run tool | `len(files_created) >= 5`, each exists |
| T-05 | `test_files_modified_count` | Fixture `otp_t05` | Run tool | `len(files_modified) >= 2`, each exists |

### 10.2 Category B — Code quality (T-06 .. T-10)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-06 | `test_all_py_parse` | Fixture `otp_t06`; run tool | `ast.parse` every `.py` | No `SyntaxError` |
| T-07 | `test_no_function_over_50_loc` | Fixture `otp_t07`; run tool | AST walk `app/` | `max_loc <= 50` |
| T-08 | `test_config_fields_patched` | Fixture `otp_t08`; run tool | Read `app/core/config.py` | `TWILIO_ACCOUNT_SID` with 4-space indent |
| T-09 | `test_models_init_patched` | Fixture `otp_t09`; run tool | Read `app/models/__init__.py` | Contains `"OtpCode"` |
| T-10 | `test_routes_registered` | Fixture `otp_t10`; run tool | Read `app/routes/__init__.py` | Contains `"sms"` |

### 10.3 Category C — Domain-specific modules (T-11 .. T-14)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-11 | `test_otp_model_created` | Fixture `otp_t11`; run tool | Read `app/models/otp_code.py` | `"class OtpCode"`, `"verified"` present |
| T-12 | `test_sms_otp_service` | Fixture `otp_t12`; run tool | Read `app/auth/sms_otp.py` | `"secrets.randbelow"`, `"secrets.compare_digest"`, `"import twilio"` inside function |
| T-13 | `test_routes_created` | Fixture `otp_t13`; run tool | Read `app/api/routes/sms_auth.py` | `"/send"` + `"/verify"` + `"_enforce_rate_limit"` |
| T-14 | `test_migration_created` | Fixture `otp_t14`; run tool | Scan `alembic/versions/` | File with `"otp_codes"` + `"ix_otp_codes_phone"` |

### 10.4 Category D — Meta (T-15 .. T-16)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-15 | `test_execution_time_recorded` | Fixture `otp_t15`; run tool | `result.execution_time_ms` | `> 0` |
| T-16 | `test_next_steps_mention_twilio_and_alembic` | Fixture `otp_t16`; run tool | Lowercase-join `next_steps` | Contains `"twilio"` and `"alembic"` |

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| `add_social_login` (TOOL-074) | No | ✅ Compatible | SMS OTP as MFA layer on top of social login |
| `add_passkey_auth` (TOOL-075) | No | ✅ Compatible | SMS OTP as fallback factor for passkey-incapable devices |
| `add_transactional_email` (TOOL-081) | No | ✅ Compatible | Email OTP as alternative channel using the same `OtpCode` model |
| `add_multi_tenancy` (TOOL-008) | No | ⚠️ Caveat | `OtpCode` has no `tenant_id`; multi-tenant apps must scope rate-limit checks by `user_id` |
| `add_arq_worker` (TOOL-053) | No | ⚠️ Caveat | `send_sms` can be offloaded to arq for durable retry on Twilio/Vonage failures |
| `add_cache_layer` (TOOL-021) | No | ⚠️ Caveat | DB-based rate limiting is the default; Redis-based rate limiting is a performance upgrade if high SMS volume expected |

---

## 11.1 Anti-patterns This Tool Prevents

| Anti-pattern | How this tool avoids it |
|-------------|------------------------|
| `random.randint` for OTP generation | `secrets.randbelow` from `secrets` module (OS CSPRNG) — INV-OTP-04 |
| `str(otp) == submitted` timing attack | `secrets.compare_digest` constant-time comparison — INV-OTP-05 |
| Importing Twilio at module level (app boot crash if not installed) | `import twilio.rest` inside `_send_via_twilio` body only — INV-OTP-06 |
| Unlimited SMS to any phone number (SMS bombing) | DB rate limit via `COUNT(*)` query — INV-OTP-07 |
| Logging full phone numbers | `_mask_phone` — only last 4 digits in logs |
| Deleting OTP rows after verification | `verified=True` flag; rows retained for audit trail |
| Redis-only rate limiting (Redis becomes critical dependency) | Pure DB implementation — no Redis required |

---

## 12. Rollback Procedure

```bash
git checkout HEAD -- app/core/config.py app/models/__init__.py app/routes/__init__.py
rm -f app/models/otp_code.py app/auth/sms_otp.py app/schemas/otp.py \
      app/api/routes/sms_auth.py
find alembic/versions/ -name '*sms_otp*' -delete
alembic downgrade -1
```

---

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-01 | Invalid `project_dir` | `status="error"` |
| EC-02 | `app/models/otp_code.py` exists with `"OtpCode"` | `status="no_op"` |
| EC-03 | `dry_run=True` | Notes only, zero writes |
| EC-04 | Twilio credentials not set | `RuntimeError("TWILIO_ACCOUNT_SID, ...")` raised by `_send_via_twilio` |
| EC-05 | `SMS_PROVIDER=vonage` in env | `import vonage` called; `twilio` never imported |
| EC-06 | Rate limit window at boundary | `COUNT(*) WHERE created_at >= window_start` exactly `== OTP_RATE_LIMIT_MAX` → 429 |
| EC-07 | OTP expired during verify | `expires_at <= now()` → record not returned → 400 |
| EC-08 | Phone number with spaces | Stored as-is; E.164 normalization is caller responsibility |
| EC-09 | `find_migration_head` returns `None` | Falls back to `"0001_initial"` |
| EC-10 | `alembic/versions/` missing | Migration step skipped |

---

## 14. Acceptance Criteria (Final Sign-off)

1. ✅ All 16 Completeness Criteria verified by `test_add_sms_otp.py`
2. ✅ Tool execution < 5 s
3. ✅ `status="no_op"` on second run (INV-OTP-01)
4. ✅ `dry_run=True` zero writes (INV-OTP-02)
5. ✅ All `.py` AST-parse (INV-OTP-03)
6. ✅ `secrets.randbelow(10**n)` for OTP generation — never `random.randint` (INV-OTP-04)
7. ✅ `secrets.compare_digest` for constant-time OTP verification (INV-OTP-05)
8. ✅ Twilio and Vonage SDKs lazy-imported inside respective `_send_via_*` bodies (INV-OTP-06)
9. ✅ Rate limit enforced via `COUNT(*)` SQL without Redis dependency (INV-OTP-07)
10. ✅ `execution_time_ms` positive on all return paths (INV-OTP-08)
11. ✅ Phone masked in logs via `_mask_phone` (last 4 digits only)
12. ✅ Migration creates `otp_codes` with `ix_otp_codes_phone` index

---

## 15. Implementation Checklist (Ultra-granular)

- [ ] `validate_project_dir` confirms path exists and is a directory
- [ ] `ensure_prerequisites(BASE_MODEL, MODELS_INIT, CONFIG_SETTINGS, ROUTES_INIT, ALEMBIC_VERSIONS)` passes
- [ ] Fingerprint check: `"OtpCode" in (project_dir / "app/models/otp_code.py").read_text()` (if file exists) → `no_op`
- [ ] `dry_run` guard: early return with `status="success"` before any file write
- [ ] Write `app/models/otp_code.py` with `OtpCode` model (`phone` String(20) indexed, `code` String(10), `expires_at`, `verified` Boolean default False, `created_at`)
- [ ] `_patch_models_init` appends `from app.models.otp_code import OtpCode` idempotently
- [ ] Write `app/auth/sms_otp.py` with `generate_otp` (`secrets.randbelow`), `verify_otp` (`secrets.compare_digest`), `send_sms` (dispatches to `_send_via_twilio` or `_send_via_vonage`), `_mask_phone`
- [ ] Verify `import twilio.rest` appears only inside `_send_via_twilio` body; same for `import vonage`
- [ ] Create `app/auth/__init__.py` if missing
- [ ] Write `app/schemas/otp.py` (`OtpSendRequest`, `OtpSendResponse`, `OtpVerifyRequest`, `OtpVerifyResponse`)
- [ ] Write `app/api/routes/sms_auth.py` with `send_otp` endpoint, `verify_otp_code` endpoint, `_enforce_rate_limit` helper (`COUNT(*)` pattern)
- [ ] `_patch_routes_init` registers `sms_auth_router` idempotently
- [ ] `_patch_config` injects all 8 config fields: `SMS_PROVIDER`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`, `OTP_LENGTH`, `OTP_EXPIRY_SECONDS`, `OTP_RATE_LIMIT_MAX`, `OTP_RATE_LIMIT_WINDOW_SECONDS`
- [ ] `find_migration_head` resolves current Alembic head; write `alembic/versions/0076_add_sms_otp.py` creating `otp_codes` with `ix_otp_codes_phone` index
- [ ] `ast.parse` loop over all created `.py` files; return `status="error"` if any fail
- [ ] Return `ToolResult` with `next_steps` including `pip install twilio` (or `vonage`) and `alembic upgrade head`

---

## 16. References

| Document | Purpose |
|----------|---------|
| `adapt/extend/auth_access/add_sms_otp.py` | Source implementation (~780 lines) |
| `adapt/contracts/__init__.py` | `ToolInput`, `ToolResult` |
| `adapt/contracts/migration_helper.py` | `find_migration_head` |
| `specs/TOOL-074-add_social_login.md` | Sibling auth tool (Google/GitHub/Apple OAuth2) |
| `specs/TOOL-075-add_passkey_auth.md` | Sibling auth tool (passkeys; SMS OTP as fallback) |
| [Twilio Python Helper Library](https://github.com/twilio/twilio-python) | SMS provider SDK (lazy-imported) |
| [Vonage Python SDK](https://github.com/Vonage/vonage-python-sdk) | Alternative SMS provider SDK (lazy-imported) |

---

## 16.1 Troubleshooting Guide

### Symptom → Root Cause → Fix

| Symptom | Likely Cause | Diagnostic Command | Fix |
|---------|-------------|-------------------|-----|
| `ImportError: No module named 'twilio'` at startup | `twilio` imported at module level instead of inside `_send_via_twilio` | `grep -n "^import twilio" app/auth/sms_otp.py` | Move import inside function body; re-run `ast.parse` check |
| OTP always rejected even within expiry | Clock skew: server UTC vs DB-stored `created_at` | `SELECT NOW(), created_at, EXTRACT(EPOCH FROM (NOW()-created_at)) FROM otp_codes ORDER BY id DESC LIMIT 5;` | Ensure all datetimes use `datetime.utcnow()` consistently; never mix tz-aware and naive |
| 429 returned after first SMS | `OTP_RATE_LIMIT_MAX` env var set to `1` by accident | `echo $OTP_RATE_LIMIT_MAX` | Set to `5` (default); confirm `_enforce_rate_limit` reads env at call-time, not module-import |
| SMS delivered but `verify_otp_code` returns 422 | Trim/whitespace in request body `code` field | Log `repr(inp.code)` before `secrets.compare_digest` | Add `.strip()` to input before comparison; update `OtpVerifyRequest` validator |
| `alembic upgrade head` fails with duplicate table | Migration chaining broken — `0076_add_sms_otp.py` has wrong `down_revision` | `alembic history` | Regenerate migration with `find_migration_head()` returning correct head |
| Vonage SDK raises `401 Unauthorized` | `VONAGE_API_SECRET` not set; falls back to empty string | `os.environ.get("VONAGE_API_SECRET", "")` debug print | Set `VONAGE_API_KEY` and `VONAGE_API_SECRET` in `.env` |
| Rate limit window resets unexpectedly | `window_start` computed with `timedelta(seconds=...)` but env var is `None` (not set) | `print(os.environ.get("OTP_RATE_LIMIT_WINDOW_SECONDS"))` | Ensure env var is set; default is `"3600"` string — `int()` conversion must happen after `getenv` |
| `maskPhone` shows full number in logs | `_mask_phone` only called in response, not in log statements | Search for `phone` in log lines | Replace all `logger.info(f"Sending OTP to {phone}")` with `logger.info(f"Sending OTP to {_mask_phone(phone)}")` |

### OTP Security Checklist (pre-deploy)

```
[ ] OTP_LENGTH >= 6 (OWASP minimum)
[ ] OTP_EXPIRY_SECONDS <= 300 (5 minutes maximum)
[ ] OTP_RATE_LIMIT_MAX <= 5 per window
[ ] OTP_RATE_LIMIT_WINDOW_SECONDS >= 3600 (1 hour)
[ ] secrets.compare_digest used (not ==)
[ ] OTP marked used=True immediately after successful verify
[ ] Phone numbers stored as E.164 format in DB
[ ] _mask_phone applied before any logging
[ ] Twilio/Vonage credentials NOT logged anywhere
[ ] Migration creates ix_otp_codes_phone index for rate-limit query performance
[ ] OTP_EXPIRY_SECONDS default <= 300 (5 minutes) — never default to hours
[ ] SMS provider selected via SMS_PROVIDER env var at call-time (not import-time)
[ ] Tool AST-validates every generated .py file before returning status="success"
[ ] dry_run guard returns ToolResult before any file write or DB migration
```
