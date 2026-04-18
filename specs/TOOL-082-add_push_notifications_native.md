# TOOL-082: add_push_notifications_native

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_push_notifications_native` |
| Category | EXTEND > Infrastructure |
| Complexity | Medium-High |
| Dependencies | FastAPI, SQLAlchemy 2.0, Alembic, pydantic-settings; `firebase-admin` (FCM) and `apns2` (APNs) are optional |
| Signature | `add_push_notifications_native(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_push_notifications_native", "description": "Add production APNs + FCM push notifications with PushService, DeviceToken model, CRUD helpers, and REST routes. All SDKs lazy-imported.", "tags": ["extend", "infrastructure"], "entry": "add_push_notifications_native"}` |
| Files created (typical) | 10 — `app/push/__init__.py`, `app/push/service.py`, `app/push/providers/__init__.py`, `app/push/providers/fcm.py`, `app/push/providers/apns.py`, `app/models/device_token.py`, `app/schemas/push.py`, `app/crud/device_token.py`, `app/api/routes/push.py`, `alembic/versions/add_device_tokens.py` |
| Files modified (typical) | 3 — `app/core/config.py`, `app/models/__init__.py`, `app/routes/__init__.py` |

---

## 2. Purpose

The `fastapi_add_push_notifications_native` tool installs a complete, production-grade push notification system into a FastAPI project using the two official native SDKs — **FCM** (`firebase_admin`) for Android and web, and **APNs** (`apns2`) for iOS — without requiring a SaaS abstraction layer (OneSignal, Pusher Beams, etc.) that charges per-notification and creates a dependency on a third party's uptime. Teams that reach for SaaS wrappers trade simplicity for cost and lock-in; teams that try to call the raw FCM REST API directly discover that credential management and APNs HTTP/2 key-based authentication are non-trivial. This tool handles both.

It generates: (a) an `app/push/` package with a `PushService` facade that routes delivery to `APNsProvider` (iOS) or `FCMProvider` (Android/web) based on the `platform` field, plus a `PushService.send_to_topic` method for FCM broadcast; (b) `app/push/providers/fcm.py` with `FCMProvider` — a `_init_firebase()` singleton that initialises the Firebase app exactly once and `send_to_device` / `send_to_topic` methods; (c) `app/push/providers/apns.py` with `APNsProvider` — token-based HTTP/2 auth via `APNS_KEY_PATH` / `APNS_KEY_ID` / `APNS_TEAM_ID`; (d) a `DeviceToken` SQLAlchemy model linking `user_id` to `platform + token` with a cascade-delete FK on `users.id`; (e) async CRUD helpers (`create_device_token`, `get_device_token`, `list_tokens_for_user`, `delete_device_token`); (f) three REST routes — `POST /push/register-device` (register a token), `POST /push/send` (send a notification to a device or FCM topic), `DELETE /push/devices/{id}` (unregister); (g) an Alembic migration; and (h) five settings fields (`FCM_CREDENTIALS_PATH`, `APNS_KEY_PATH`, `APNS_KEY_ID`, `APNS_TEAM_ID`, `APNS_BUNDLE_ID`) injected inside `class Settings`.

Key design decisions: both SDKs are **lazy-imported** inside provider method bodies — the app boots cleanly without either package; `_init_firebase()` uses a module-level boolean guard so Firebase is initialised exactly once per process regardless of how many requests call `FCMProvider`; APNs uses `settings.ENVIRONMENT != "production"` to select sandbox vs production endpoint automatically; the `platform` field is typed as `Literal["ios", "android"]` in the Pydantic schema so invalid platform values are rejected with HTTP 422 before reaching the service layer; `DELETE /push/devices/{id}` returns 404 when the token is not found rather than silently succeeding; the tool is **idempotent** — a second run detects `PushService` in `app/push/__init__.py` and returns `status="no_op"`.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | CI budget; measured via `execution_time_ms` (T-18) |
| Files created | ≥ 9 | Push package (5), model, schemas, CRUD, routes, migration (T-04) |
| Files modified | ≥ 2 | Config, models `__init__`, routes `__init__` (T-05) |
| Max function LOC in generated code | ≤ 50 | Each generated function auditable (T-07) |
| `POST /push/register-device` latency | < 20 ms | Single `INSERT` into `device_tokens` |
| `POST /push/send` latency (device) | < 500 ms | One DB read + provider SDK call; bounded by FCM/APNs RTT |
| `POST /push/send` latency (topic) | < 500 ms | No DB read; single FCM topic send |
| `DELETE /push/devices/{id}` latency | < 20 ms | Single `DELETE` by PK |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── main.py
│   ├── core/config.py       # No FCM_* or APNS_* settings
│   ├── models/__init__.py   # No DeviceToken
│   └── routes/__init__.py   # No push router
└── requirements.txt         # no firebase-admin, no apns2
```

Push notifications are absent or implemented with a one-off SaaS SDK with per-notification pricing. No device token persistence. No native APNs support.

### 4.2 PushService: AFTER

```python
# app/push/__init__.py
from app.push.service import PushService
__all__ = ["PushService"]

# app/push/service.py
class PushService:
    async def send_to_device(
        self, *, token: str, platform: str, title: str, body: str,
        data: dict | None = None,
    ) -> bool:
        """Route to FCMProvider (android) or APNsProvider (ios)."""
        if platform == "ios":
            from app.push.providers.apns import APNsProvider
            return await APNsProvider().send(token=token, title=title, body=body, data=data)
        if platform == "android":
            from app.push.providers.fcm import FCMProvider
            return await FCMProvider().send_to_device(token=token, title=title, body=body, data=data)
        return False

    async def send_to_topic(self, *, topic: str, title: str, body: str,
                            data: dict | None = None) -> bool:
        """FCM topic broadcast."""
```

### 4.3 FCMProvider: AFTER

```python
# app/push/providers/fcm.py
_firebase_initialised = False

def _init_firebase() -> bool:
    """Initialise Firebase Admin SDK once; reads FCM_CREDENTIALS_PATH from settings."""
    global _firebase_initialised
    if _firebase_initialised: return True
    try:
        import firebase_admin                     # lazy — optional dep
        from firebase_admin import credentials as fb_creds
    except ImportError:
        logger.warning("firebase_admin not installed"); return False
    ...

class FCMProvider:
    async def send_to_device(self, *, token, title, body, data=None) -> bool: ...
    async def send_to_topic(self, *, topic, title, body, data=None) -> bool: ...
```

### 4.4 DeviceToken model: AFTER

```python
# app/models/device_token.py
class DeviceToken(Base):
    __tablename__ = "device_tokens"

    id:         Mapped[uuid.UUID]   # PK
    user_id:    Mapped[uuid.UUID]   # FK → users.id CASCADE DELETE, index=True
    platform:   Mapped[str]         # String(16)
    token:      Mapped[str]         # String(512)
    created_at: Mapped[datetime]    # TZ-aware, server_default=now()
```

### 4.5 REST routes: AFTER

```python
router = APIRouter(prefix="/push", tags=["push"])

POST   /push/register-device   → DeviceTokenRead (201)
POST   /push/send              → PushSendResult
DELETE /push/devices/{id}      → {"deleted": True} or 404
```

### 4.6 Config patch: AFTER

```python
# app/core/config.py  (added by _patch_config)
    # --- Push notifications — added by add_push_notifications_native tool ---
    FCM_CREDENTIALS_PATH: str = ""
    APNS_KEY_PATH: str = ""
    APNS_KEY_ID: str = ""
    APNS_TEAM_ID: str = ""
    APNS_BUNDLE_ID: str = ""
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Tool is idempotent on second run** | Pre-flight checks `"PushService" in app/push/__init__.py` and returns `status="no_op"` |
| QS-2 | **`dry_run=True` writes zero files** | Early return before any filesystem write |
| QS-3 | **Every generated `.py` file AST-parses** | `ast.parse` run on each created `.py` |
| QS-4 | **No generated function exceeds 50 LOC** | All helpers and provider methods kept short |
| QS-5 | **FCM and APNs SDKs are lazy-imported** | `import firebase_admin` and `from apns2...` inside method bodies only |
| QS-6 | **Firebase initialised exactly once per process** | `_init_firebase()` guards with `_firebase_initialised` module-level boolean |
| QS-7 | **Credential paths read from `settings` at call time** | `settings.FCM_CREDENTIALS_PATH` / `settings.APNS_KEY_PATH` never hard-coded |
| QS-8 | **`platform` field enforced as `Literal["ios", "android"]`** | Pydantic schema rejects unknown values with HTTP 422 |
| QS-9 | **`DELETE /push/devices/{id}` returns 404 when not found** | `if not deleted: raise HTTPException(404)` in route |
| QS-10 | **`DeviceToken` registered in `app/models/__init__.py`** | `_patch_models_init` appends import idempotently |
| QS-11 | **Migration chained to current head** | `find_migration_head(versions_dir)` called |
| QS-12 | **Unknown platform logs warning and returns `False`** | `logger.warning("PushService: unknown platform %r", platform); return False` |
| QS-13 | **`execution_time_ms` set on every return path** | `_elapsed_ms(start)` called on all branches |
| QS-14 | **`next_steps` reference `alembic` and provider SDK installs** | Hard-coded strings in success branch |

---

## 6. Completeness Criteria

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | Tool returns `status="success"` on a fresh project | `result.status == "success"` | T-01 (`test_success_status`) |
| CC-02 | Second run returns `status="no_op"` with zero file ops | `r2.status == "no_op"` and both lists empty | T-02 (`test_idempotent`) |
| CC-03 | `dry_run=True` writes zero bytes to the filesystem | Before/after filesystem snapshot identical | T-03 (`test_dry_run`) |
| CC-04 | Tool creates at least 9 new files | `len(result.files_created) >= 9` and each path exists | T-04 (`test_files_created_count`) |
| CC-05 | Tool modifies at least 2 existing files | `len(result.files_modified) >= 2` and each path exists | T-05 (`test_files_modified_count`) |
| CC-06 | Every generated `.py` AST-parses cleanly | `ast.parse` over all `.py` files in project tree | T-06 (`test_all_py_parse`) |
| CC-07 | No generated function exceeds 50 LOC | AST walk; `max_loc <= 50` | T-07 (`test_no_function_over_50_loc`) |
| CC-08 | `FCM_CREDENTIALS_PATH` exists inside `class Settings` body | String scan + 4-space indent check | T-08 (`test_config_fields_patched`) |
| CC-09 | `DeviceToken` registered in `app/models/__init__.py` | `"DeviceToken" in content` | T-09 (`test_models_init_patched`) |
| CC-10 | Push router registered in `app/routes/__init__.py` | `"push" in content.lower()` | T-10 (`test_routes_registered`) |
| CC-11 | `app/push/__init__.py` contains `PushService` | File exists + `"PushService" in content` | T-11 (`test_push_init_created`) |
| CC-12 | `app/push/providers/fcm.py` contains `FCMProvider` and `_init_firebase` | File exists + substring checks | T-12 (`test_fcm_provider_created`) |
| CC-13 | `app/push/providers/apns.py` contains `APNsProvider` | File exists + `"APNsProvider" in content` | T-13 (`test_apns_provider_created`) |
| CC-14 | `app/models/device_token.py` declares `class DeviceToken` | File exists + `"class DeviceToken" in content` | T-14 (`test_device_token_model_created`) |
| CC-15 | `app/crud/device_token.py` contains CRUD helpers | Contains `create_device_token`, `get_device_token`, `delete_device_token` | T-15 (`test_device_token_crud_created`) |
| CC-16 | Alembic migration exists and references `device_tokens` table | File exists + `"device_tokens" in content` | T-16 (`test_migration_created`) |
| CC-17 | `app/api/routes/push.py` has all three route handlers | Contains `register_device`, `send_push`, `delete_device` | T-17 (`test_push_routes_created`) |
| CC-18 | `execution_time_ms` is a positive integer | `result.execution_time_ms > 0` | T-18 (`test_execution_time_recorded`) |
| CC-19 | `next_steps` include `alembic` and `firebase-admin`/`apns2` install guidance | Lowercased join contains `"alembic"` and `"pip install"` | T-19 (`test_next_steps_mention_alembic_and_pip`) |
| CC-20 | Running the tool twice leaves project AST-parseable | `ast.parse` over all `.py` after two runs | T-20 (`test_idempotent_project_still_parses`) |

---

## 7. Definition of Done (DoD)

- [ ] All 20 Completeness Criteria verified by `test_add_push_notifications_native.py`
- [ ] `add_push_notifications_native.py` runs `ast.parse` on every created `.py` before returning success
- [ ] Fingerprint check `"PushService" in app/push/__init__.py` returns `status="no_op"` on second run
- [ ] `dry_run=True` returns success with empty create/modify lists
- [ ] `firebase_admin` and `apns2` are lazy-imported inside method bodies only
- [ ] `_init_firebase()` uses `_firebase_initialised` module-level guard — Firebase initialised exactly once
- [ ] `platform` field typed as `Literal["ios", "android"]` in `DeviceTokenCreate` schema
- [ ] `DELETE /push/devices/{id}` raises HTTP 404 when token not found
- [ ] Config fields anchored inside `class Settings` on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30`
- [ ] `_patch_models_init` idempotently appends `DeviceToken` import
- [ ] `find_migration_head` used to chain migration
- [ ] `execution_time_ms` set on every return path
- [ ] Tool exits within 5 s on a fresh fixture project
- [ ] `MCP_TOOL` descriptor exposes `{name, description, tags, entry}`

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-PUSH-01 | Tool is ALWAYS idempotent on second invocation | `"PushService" in push_init.read_text()` short-circuits to `status="no_op"` | T-02, T-20 |
| INV-PUSH-02 | `dry_run=True` NEVER writes to disk | Early return before any write | T-03 |
| INV-PUSH-03 | Every generated `.py` MUST parse as valid Python | Final `ast.parse` loop | T-06, T-20 |
| INV-PUSH-04 | FCM and APNs SDKs MUST be lazy-imported | `import firebase_admin` / `from apns2...` inside method bodies | T-12, T-13 |
| INV-PUSH-05 | Firebase MUST be initialised exactly once per process | `_firebase_initialised` boolean guard in `_init_firebase()` | T-12 |
| INV-PUSH-06 | Credential paths MUST be read from `settings` at call time | `settings.FCM_CREDENTIALS_PATH` / `settings.APNS_KEY_PATH` in provider bodies | T-08 |
| INV-PUSH-07 | `DeviceToken` MUST be registered in `app/models/__init__.py` | `_patch_models_init` appends import idempotently | T-09 |
| INV-PUSH-08 | Config fields MUST live inside `class Settings` body | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` | T-08 |
| INV-PUSH-09 | Alembic migration MUST be chained to current head | `find_migration_head(versions_dir) or "0001_initial"` | T-16 |
| INV-PUSH-10 | `DELETE /push/devices/{id}` MUST return 404 when not found | `if not deleted: raise HTTPException(404)` | T-17 |
| INV-PUSH-11 | `ToolResult.execution_time_ms` MUST be positive on every path | `_elapsed_ms(start)` called on all branches | T-18 |
| INV-PUSH-12 | `next_steps` MUST reference `alembic` and provider SDK install | Hard-coded in success branch | T-19 |

---

## 9. User Stories

### 9.1 Core install flow (US-01 .. US-05)

**US-01: Install push notifications into a clean project**
- **As a** mobile backend engineer
- **I want** FCM and APNs both wired up with one tool call
- **So that** I stop maintaining two separate SDK integrations
- **Given:** FastAPI project with config, models, alembic
- **When:** `add_push_notifications_native(ToolInput(project_dir=...))`
- **Then:** `status="success"`, ≥ 9 files created, ≥ 2 modified (T-01, T-04, T-05)

**US-02: Re-run on an already-installed project**
- **As a** CI job
- **I want** tool to skip silently when already applied
- **Given:** `app/push/__init__.py` contains `PushService`
- **When:** Tool invoked again
- **Then:** `status="no_op"`, empty lists, project still parses (T-02, T-20)

**US-03: Dry-run to preview changes**
- **As a** cautious developer
- **Given:** Fresh project
- **When:** `add_push_notifications_native(ToolInput(dry_run=True))`
- **Then:** Success + notes; filesystem unchanged (T-03)

**US-04: Generated code is auditable**
- **As a** code reviewer
- **Given:** Tool just generated push package
- **When:** AST-walk `app/` for function sizes
- **Then:** No function > 50 LOC (T-07)

**US-05: Both SDKs absent at boot time**
- **As a** Docker image without optional SDKs
- **Given:** `firebase-admin` and `apns2` not installed
- **When:** App starts
- **Then:** No `ImportError` at boot; error only at first `send()` call (INV-PUSH-04)

### 9.2 FCM provider (US-06 .. US-10)

**US-06: Send Android notification via FCM**
- **As a** developer sending a push to Android
- **Given:** `FCM_CREDENTIALS_PATH` set; `firebase-admin` installed
- **When:** `await PushService().send_to_device(token=..., platform="android", title=..., body=...)`
- **Then:** FCM sends message; returns `True` (T-12)

**US-07: Firebase initialised exactly once**
- **As a** high-traffic service handling 1000 req/s
- **Given:** `FCMProvider` called from multiple concurrent handlers
- **When:** `_init_firebase()` called repeatedly
- **Then:** `firebase_admin.initialize_app()` called at most once (`_firebase_initialised` guard) (INV-PUSH-05)

**US-08: Send to FCM topic for broadcast**
- **As a** developer broadcasting to all Android users
- **Given:** FCM initialised
- **When:** `await PushService().send_to_topic(topic="all_users", title=..., body=...)`
- **Then:** `FCMProvider.send_to_topic()` called; FCM broadcast message sent (T-12)

**US-09: FCM unavailable — returns False, no crash**
- **As a** staging environment without Firebase credentials
- **Given:** `FCM_CREDENTIALS_PATH=""` or `firebase-admin` not installed
- **When:** `FCMProvider.send_to_device()` called
- **Then:** Returns `False`; `WARNING` logged; no unhandled exception (T-12)

**US-10: `data` dict values coerced to strings**
- **As a** caller passing integer data values to FCM
- **Given:** `data={"badge": 5}`
- **When:** `FCMProvider.send_to_device(..., data={"badge": 5})`
- **Then:** `{k: str(v) for k, v in data.items()}` applied before `messaging.Message` (T-12)

### 9.3 APNs provider (US-11 .. US-15)

**US-11: Send iOS notification via APNs**
- **As a** developer sending a push to iOS
- **Given:** `APNS_KEY_PATH`, `APNS_KEY_ID`, `APNS_TEAM_ID`, `APNS_BUNDLE_ID` set; `apns2` installed
- **When:** `await PushService().send_to_device(token=..., platform="ios", title=..., body=...)`
- **Then:** APNs sends notification; returns `True` (T-13)

**US-12: APNs sandbox mode in non-production**
- **As a** developer testing on a real device
- **Given:** `ENVIRONMENT != "production"`
- **When:** `APNsProvider.send()` creates `APNsClient`
- **Then:** `use_sandbox=True` passed to `APNsClient` (T-13)

**US-13: APNs unavailable — returns False**
- **As a** CI environment without APNs credentials
- **Given:** `APNS_KEY_PATH=""` or `apns2` not installed
- **When:** `APNsProvider.send()` called
- **Then:** Returns `False`; `WARNING` logged; no crash (T-13)

**US-14: Unknown platform logs warning**
- **As a** developer accidentally passing `platform="web"`
- **When:** `PushService.send_to_device(platform="web", ...)`
- **Then:** `logger.warning("PushService: unknown platform %r", "web")`; returns `False` (QS-12)

**US-15: `Literal` platform validation rejects unknown values at HTTP boundary**
- **As a** client sending malformed request
- **Given:** `DeviceTokenCreate(platform="windows")`
- **When:** `POST /push/register-device` with `{"platform": "windows", ...}`
- **Then:** FastAPI returns HTTP 422 before reaching `PushService` (QS-8)

### 9.4 Device token CRUD and REST routes (US-16 .. US-20)

**US-16: Register a device token**
- **As a** mobile app after FCM/APNs token refresh
- **When:** `POST /push/register-device` `{"user_id": "...", "platform": "android", "token": "..."}`
- **Then:** Returns `DeviceTokenRead` with `id`, `created_at`; row inserted (T-17)

**US-17: Send push to a registered device**
- **As a** notification service
- **When:** `POST /push/send` `{"device_token_id": "...", "title": "Hey", "body": "..."}`
- **Then:** Route fetches `DeviceToken` row, calls `PushService.send_to_device`; returns `{"sent": true}` (T-17)

**US-18: Send to unknown device_token_id returns 404**
- **As a** caller with a stale token ID
- **When:** `POST /push/send` with non-existent `device_token_id`
- **Then:** HTTP 404 `{"detail": "Device token not found."}` (T-17, INV-PUSH-10)

**US-19: Neither device_token_id nor topic returns 422**
- **As a** caller with empty body
- **When:** `POST /push/send` `{"title": "Hey", "body": "..."}`
- **Then:** HTTP 422 `{"detail": "Provide either device_token_id or topic."}` (T-17)

**US-20: Unregister a device token**
- **As a** user who logged out
- **When:** `DELETE /push/devices/{token_id}`
- **Then:** Row deleted; returns `{"deleted": True}`; 404 if not found (T-17, INV-PUSH-10)

### 9.5 Config, migration, and operator experience (US-21 .. US-25)

**US-21: Config binds from environment variables**
- **Given:** `FCM_CREDENTIALS_PATH=/secrets/creds.json` in `.env`
- **When:** `Settings()` instantiated
- **Then:** `settings.FCM_CREDENTIALS_PATH == "/secrets/creds.json"` (INV-PUSH-06, T-08)

**US-22: Migration creates device_tokens table**
- **Given:** Migration applied with `alembic upgrade head`
- **When:** Schema inspected
- **Then:** `device_tokens` table with `id`, `user_id` (FK→users.id CASCADE), `platform`, `token`, `created_at` (T-16)

**US-23: Migration chained to current head**
- **Given:** Existing migration chain
- **When:** Tool generates migration
- **Then:** `down_revision` matches `find_migration_head()` result (INV-PUSH-09, T-16)

**US-24: `next_steps` guide operator**
- **Given:** Tool completed successfully
- **When:** `result.next_steps` inspected
- **Then:** Contains `"alembic upgrade head"` and `"pip install firebase-admin"` / `"pip install apns2"` (INV-PUSH-12, T-19)

**US-25: Execution time recorded**
- **Given:** Tool runs on fresh fixture
- **Then:** `result.execution_time_ms > 0` (INV-PUSH-11, T-18)

---

## 10. Test Plan

All 20 tests live in `adapt/extend/infrastructure/test_add_push_notifications_native.py`.

### 10.1 Category A — Tool execution (T-01 .. T-05)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | `test_success_status` | Fixture `push_t01` | `add_push_notifications_native(ToolInput(project_dir))` | `result.status == "success"` (INV-PUSH-01, CC-01) |
| T-02 | `test_idempotent` | Fixture `push_t02`; run once | Run again | `r2.status == "no_op"`; both lists empty (CC-02) |
| T-03 | `test_dry_run` | Fixture `push_t03` | `dry_run=True` | Success + notes; filesystem unchanged (CC-03) |
| T-04 | `test_files_created_count` | Fixture `push_t04` | Run tool | `len(files_created) >= 9`; all paths exist (CC-04) |
| T-05 | `test_files_modified_count` | Fixture `push_t05` | Run tool | `len(files_modified) >= 2`; all paths exist (CC-05) |

### 10.2 Category B — Generated code quality (T-06 .. T-10)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-06 | `test_all_py_parse` | Fixture `push_t06`; run tool | AST-parse every `.py` | No `SyntaxError` (CC-06) |
| T-07 | `test_no_function_over_50_loc` | Fixture `push_t07`; run tool | AST walk `app/` | `max_loc <= 50` (CC-07) |
| T-08 | `test_config_fields_patched` | Fixture `push_t08`; run tool | Read `config.py` | `FCM_CREDENTIALS_PATH` with 4-space indent (CC-08) |
| T-09 | `test_models_init_patched` | Fixture `push_t09`; run tool | Read `models/__init__.py` | Contains `"DeviceToken"` (CC-09) |
| T-10 | `test_routes_registered` | Fixture `push_t10`; run tool | Read `routes/__init__.py` | Contains `"push"` (CC-10) |

### 10.3 Category C — Domain-specific modules (T-11 .. T-17)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-11 | `test_push_init_created` | Fixture `push_t11`; run tool | Read `app/push/__init__.py` | Contains `"PushService"` (CC-11) |
| T-12 | `test_fcm_provider_created` | Fixture `push_t12`; run tool | Read `app/push/providers/fcm.py` | Contains `FCMProvider`, `_init_firebase`, `_firebase_initialised` (INV-PUSH-04, INV-PUSH-05, CC-12) |
| T-13 | `test_apns_provider_created` | Fixture `push_t13`; run tool | Read `app/push/providers/apns.py` | Contains `APNsProvider`; `from apns2` inside method body (INV-PUSH-04, CC-13) |
| T-14 | `test_device_token_model_created` | Fixture `push_t14`; run tool | Read `app/models/device_token.py` | Contains `"class DeviceToken"` with `user_id`, `platform`, `token` (CC-14) |
| T-15 | `test_device_token_crud_created` | Fixture `push_t15`; run tool | Read `app/crud/device_token.py` | Contains `create_device_token`, `get_device_token`, `delete_device_token` (CC-15) |
| T-16 | `test_migration_created` | Fixture `push_t16`; run tool | Read migration file | Contains `"device_tokens"`; `down_revision` not placeholder (INV-PUSH-09, CC-16) |
| T-17 | `test_push_routes_created` | Fixture `push_t17`; run tool | Read `app/api/routes/push.py` | Contains `register_device`, `send_push`, `delete_device` (CC-17) |

### 10.4 Category D — Meta (T-18 .. T-20)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-18 | `test_execution_time_recorded` | Fixture `push_t18` | Read `result.execution_time_ms` | `> 0` (CC-18) |
| T-19 | `test_next_steps_mention_alembic_and_pip` | Fixture `push_t19` | Lowercase-join `result.next_steps` | Contains `"alembic"` and `"pip install"` (CC-19) |
| T-20 | `test_idempotent_project_still_parses` | Fixture `push_t20`; run twice | AST-parse every `.py` | No `SyntaxError` (CC-20) |

### 10.5 Test execution

```bash
PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_push_notifications_native.py -v
```

Target: 20/20 passed, 0 failed.

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| `add_arq_worker` (TOOL-053) | No | ✅ Compatible | Push sends can be queued as arq tasks for retry on failure |
| `add_multi_tenancy` (TOOL-008) | No | ⚠️ Caveat | `device_tokens` has no tenant FK by default; add `tenant_id` column manually for per-tenant isolation |
| `add_rbac` (TOOL-012) | Yes — RBAC runs AFTER | ⚠️ Caveat | `POST /push/send` should require an admin or system role |
| `add_webhook_sender` (TOOL-015) | No | ✅ Compatible | Push and webhook delivery are complementary notification channels |
| `add_audit_log` (TOOL-005) | No | ✅ Compatible | Optionally emit audit entries in `send_push` handler for compliance |
| `add_transactional_email` (TOOL-081) | No | ✅ Compatible | Push + email are parallel notification channels; can be sent from same handler |
| `add_soft_delete` (TOOL-001) | No | ⚠️ Caveat | `DeviceToken` rows should be hard-deleted (cascade from user) not soft-deleted |
| `add_feature_flags` (TOOL-009) | No | ✅ Compatible | Feature-flag push delivery per user segment |

**Conflicts:** None identified. `firebase_admin` and `apns2` have no known conflicts with other SKILL-001 dependencies.

---

## 12. Rollback Procedure

### 12.1 Code rollback

```bash
git checkout HEAD -- \
  app/core/config.py \
  app/models/__init__.py \
  app/routes/__init__.py

rm -rf \
  app/push/ \
  app/models/device_token.py \
  app/schemas/push.py \
  app/crud/device_token.py \
  app/api/routes/push.py \
  alembic/versions/add_device_tokens.py
```

### 12.2 Database rollback

```bash
alembic downgrade -1   # drops device_tokens table
```

---

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-01 | Missing `app/` directory | `validate_project_dir` fails → `status="error"` |
| EC-02 | Missing prerequisites | `ensure_prerequisites` error; hint to run `fastapi_generate_project` |
| EC-03 | `app/push/__init__.py` already contains `PushService` | Early return `status="no_op"` |
| EC-04 | `dry_run=True` | Success + notes; no filesystem changes |
| EC-05 | `FCM_CREDENTIALS_PATH` empty at call time | `_init_firebase()` logs WARNING and returns `False`; provider returns `False` |
| EC-06 | `firebase_admin` not installed | `ImportError` caught in `_init_firebase()`; WARNING logged; returns `False` |
| EC-07 | `apns2` not installed | `ImportError` caught in `APNsProvider.send()`; WARNING logged; returns `False` |
| EC-08 | `ENVIRONMENT` not set | `settings.ENVIRONMENT` defaults to `"development"`; APNs uses sandbox |
| EC-09 | `alembic/versions/` missing | Migration step skipped; other writes proceed |
| EC-10 | `app/models/__init__.py` already imports `DeviceToken` | `_patch_models_init` early-returns |
| EC-11 | `app/routes/__init__.py` already contains push router | `_patch_routes_init` early-returns |
| EC-12 | `send_push` called with both `device_token_id` and `topic` | `topic` branch takes precedence (checked first) |
| EC-13 | `send_push` called with neither `device_token_id` nor `topic` | HTTP 422 raised |
| EC-14 | `find_migration_head` returns `None` | `down_revision = "0001_initial"` fallback |
| EC-15 | Tool runs twice back-to-back | Second run returns `no_op`; project AST remains parseable |

---

## 14. Security Considerations

| # | Concern | Mitigation |
|---|---------|------------|
| SEC-01 | FCM service account key exposure | `FCM_CREDENTIALS_PATH` is a file path read at call time; file should be volume-mounted as a secret |
| SEC-02 | APNs key exposure | `APNS_KEY_PATH` is a file path; key file should be mounted as a secret |
| SEC-03 | Device token enumeration via `GET /push/devices/` | No list-all-tokens route generated; tokens listed only via `list_tokens_for_user` CRUD |
| SEC-04 | Unauthenticated push sending | `POST /push/send` should require authentication; add `CurrentUser` gate manually or via `add_rbac` |
| SEC-05 | Platform injection | `Literal["ios", "android"]` enforced by Pydantic; unknown values rejected at HTTP boundary |

---

## 15. Observability

| Signal | Location | Notes |
|--------|----------|-------|
| `PushService: unknown platform` warning | `PushService.send_to_device()` | Logged at WARNING when platform not ios/android |
| `firebase_admin not installed` warning | `_init_firebase()` | Logged at WARNING |
| `apns2 not installed` warning | `APNsProvider.send()` | Logged at WARNING |
| `FCM init failed` warning | `_init_firebase()` | Logged at WARNING with exception |
| `FCM send_to_device failed` warning | `FCMProvider.send_to_device()` | Logged at WARNING with exception |
| `APNs send failed` warning | `APNsProvider.send()` | Logged at WARNING with exception |

---

## 16. Changelog

| Version | Date | Change |
|---------|------|--------|
| v1 | 2026-04-15 | Initial spec — FCM + APNs native providers; DeviceToken model; CRUD; 3 REST routes; 20 CCs |
