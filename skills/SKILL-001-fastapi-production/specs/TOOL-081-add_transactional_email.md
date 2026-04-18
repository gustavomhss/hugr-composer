# TOOL-081: add_transactional_email

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_transactional_email` |
| Category | EXTEND > Infrastructure |
| Complexity | Medium |
| Dependencies | FastAPI, SQLAlchemy 2.0, Alembic, pydantic-settings; provider SDKs are optional (resend, postmarker, sendgrid) |
| Signature | `add_transactional_email(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_transactional_email", "description": "Add Resend/Postmark/SendGrid email adapters with delivery tracking (sent/delivered/bounced/complained events), PII-safe audit model, and provider webhook routes.", "tags": ["extend", "infrastructure"], "entry": "add_transactional_email"}` |
| Files created (typical) | 9 — `app/email/providers/__init__.py`, `app/email/providers/resend_provider.py`, `app/email/providers/postmark_provider.py`, `app/email/providers/sendgrid_provider.py`, `app/email/delivery_tracker.py`, `app/models/email_event.py`, `app/schemas/email_event.py`, `app/api/routes/email_events.py`, `alembic/versions/add_email_events.py` |
| Files modified (typical) | 3 — `app/core/config.py`, `app/models/__init__.py`, `app/routes/__init__.py` |

---

## 2. Purpose

The `fastapi_add_transactional_email` tool installs a production-grade, provider-agnostic transactional email layer into a FastAPI project. Teams frequently hard-code a single email provider SDK at the top of a handler function, which makes provider migration require hunting dozens of call sites, debugging mismatched API shapes, and discovering missing delivery events only when compliance auditors ask for them. This tool eliminates that pattern by generating: (a) a `app/email/providers/` package with three lazy provider adapters — `ResendProvider`, `PostmarkProvider`, `SendgridProvider` — each with an identical `send(*, to, subject, html, from_address, text)` interface so the calling code never changes when the provider does; (b) a `DeliveryTracker` that writes one `email_events` row per lifecycle event (sent / delivered / bounced / complained), storing only the redacted recipient address (`u***@example.com`) so a database dump cannot leak PII; (c) a `EmailEvent` SQLAlchemy model with `message_id`, `event_type`, `recipient_redacted`, `provider`, and `occurred_at` columns and an index on `message_id` for O(1) event lookup; (d) matching Pydantic schemas (`EmailEventRead`, `EmailEventList`) and two HTTP routes — `POST /email/webhook/{provider}` (ingests delivery events from provider webhook callbacks) and `GET /email/events` (lists recent events for admin dashboards); (e) an Alembic migration chained to the current head; and (f) four settings fields (`EMAIL_PROVIDER`, `RESEND_API_KEY`, `POSTMARK_API_KEY`, `SENDGRID_API_KEY`) injected inside the `Settings` class body so pydantic-settings picks them up from environment variables without code changes.

Key design decisions: all three provider SDKs are **lazy-imported** inside the `send()` method body — the app boots cleanly even when none of the provider packages are installed, and operators install only the one they use (`pip install resend`); the provider is selected at call time from `settings.EMAIL_PROVIDER`, so switching is a single env-var change with zero application code changes; the full recipient address is **never** stored in any column or log line — only `recipient_redacted` is persisted; webhook routes parse provider-specific payloads through a `_parse_webhook()` dispatcher that degrades gracefully (unknown providers are logged and ignored, returning `{"status": "ok"}` so provider retries do not loop); the tool is **idempotent** — a second run detects `DeliveryTracker` in `app/email/delivery_tracker.py` and returns `status="no_op"` without touching any file; and `execution_time_ms` is set on every return path.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | Must complete within CI step budget; measured via `execution_time_ms` in `ToolResult` (T-18) |
| Files created | ≥ 8 | Provider package (4 files), tracker, model, schemas, routes, migration (T-04) |
| Files modified | ≥ 2 | Config, models `__init__`, routes `__init__` — at least two must exist (T-05) |
| Max function LOC in generated code | ≤ 50 | Each generated function stays auditable; enforced by AST walk (T-07) |
| `send()` latency overhead | 0 ms | Adapter is a thin wrapper; network RTT to provider is the bottleneck |
| `POST /email/webhook/{provider}` latency | < 30 ms | Single DB insert via `DeliveryTracker.track()` |
| `GET /email/events` latency | < 50 ms | `SELECT ... ORDER BY occurred_at DESC LIMIT 50` backed by index |
| Migration runtime | < 1 s | Single `CREATE TABLE` + index |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── main.py
│   ├── core/
│   │   └── config.py        # Settings class, no EMAIL_* fields
│   ├── models/
│   │   └── __init__.py      # Base + User imports only
│   └── routes/
│       └── __init__.py      # api_router, no email router
├── alembic/versions/
│   └── 0001_initial.py
└── requirements.txt         # no resend/postmark/sendgrid
```

Email is either absent or hard-coded as `import resend` at module level. No delivery tracking. Provider migration requires a full rewrite.

### 4.2 Provider package init: AFTER

```python
# app/email/providers/__init__.py
"""Email provider adapters — lazy-imported multi-provider support."""

from __future__ import annotations
from app.core.config import settings


def get_provider():
    """Return the configured email provider adapter.

    Returns:
        An adapter instance for the configured EMAIL_PROVIDER.

    Raises:
        ValueError: When EMAIL_PROVIDER is set to an unknown value.
    """
    provider = (settings.EMAIL_PROVIDER or "resend").lower()
    if provider == "resend":
        from app.email.providers.resend_provider import ResendProvider
        return ResendProvider()
    if provider == "postmark":
        from app.email.providers.postmark_provider import PostmarkProvider
        return PostmarkProvider()
    if provider == "sendgrid":
        from app.email.providers.sendgrid_provider import SendgridProvider
        return SendgridProvider()
    raise ValueError(f"Unknown EMAIL_PROVIDER={provider!r}.")
```

### 4.3 DeliveryTracker: AFTER

```python
# app/email/delivery_tracker.py
"""DeliveryTracker — record and query email delivery events.

The recipient address is NEVER stored in full — only the redacted form
(u***@example.com) is persisted.
"""

class DeliveryTracker:
    def __init__(self, session: AsyncSession) -> None: ...

    async def track(
        self, *, message_id: str, event_type: str,
        recipient: str, provider: str,
    ) -> None:
        """Record a delivery event. Recipient is redacted before write."""

    async def list_events(self, *, limit: int = 50, offset: int = 0) -> list:
        """Return the most recent email events, newest first."""
```

### 4.4 EmailEvent model: AFTER

```python
# app/models/email_event.py
class EmailEvent(Base):
    __tablename__ = "email_events"

    id: Mapped[uuid.UUID]             # primary key
    message_id: Mapped[str]           # String(255), index=True
    event_type: Mapped[str]           # sent/delivered/bounced/complained
    recipient_redacted: Mapped[str]   # u***@example.com — PII never stored
    provider: Mapped[str]             # resend/postmark/sendgrid
    occurred_at: Mapped[datetime]     # timezone-aware
```

### 4.5 Webhook route: AFTER

```python
# app/api/routes/email_events.py
router = APIRouter(prefix="/email", tags=["email"])

@router.post("/webhook/{provider}", status_code=200)
async def email_webhook(provider: str, request: Request, ...) -> dict[str, str]:
    """Ingest a delivery event webhook from an email provider."""
    payload = await request.json()
    event_type, message_id, recipient = _parse_webhook(provider, payload)
    if event_type:
        await tracker.track(message_id=message_id, event_type=event_type,
                            recipient=recipient, provider=provider)
    return {"status": "ok"}
```

### 4.6 Config patch: AFTER

```python
# app/core/config.py  (diff, added by _patch_config)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # --- Transactional email — added by add_transactional_email tool ---
    EMAIL_PROVIDER: str = "resend"
    RESEND_API_KEY: str = ""
    POSTMARK_API_KEY: str = ""
    SENDGRID_API_KEY: str = ""
```

### 4.7 Typical caller usage (after install)

```python
# app/api/routes/auth.py
from app.email.providers import get_provider

@router.post("/register")
async def register(data: RegisterRequest) -> dict:
    user = await create_user(session, data)
    provider = get_provider()
    msg_id = provider.send(
        to=user.email,
        subject="Welcome!",
        html="<p>Welcome to the app.</p>",
    )
    return {"user_id": str(user.id), "email_queued": bool(msg_id)}
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Tool is idempotent on second run** | Pre-flight checks `"DeliveryTracker" in app/email/delivery_tracker.py` and returns `status="no_op"` |
| QS-2 | **`dry_run=True` writes zero files** | Early return guarded by `if inp.dry_run:` before any filesystem write |
| QS-3 | **Every generated `.py` file AST-parses** | `ast.parse` run on each created `.py`; tool raises `status="error"` on `SyntaxError` |
| QS-4 | **No generated function exceeds 50 LOC** | All helpers and adapter methods kept small by construction; assertable via AST walk |
| QS-5 | **Recipient address is never stored in full** | `_redact_email()` applied before every `EmailEvent` write in `DeliveryTracker.track()` |
| QS-6 | **API keys never logged or echoed** | Keys read from `settings` at call time; no log statement emits their values |
| QS-7 | **Provider SDKs are lazy-imported** | `import resend`, `from postmarker...`, `from sendgrid...` all inside method bodies |
| QS-8 | **Unknown webhook providers are silently ignored** | `_parse_webhook` returns `("", "", "")` for unknown providers; tracker skips empty `event_type` |
| QS-9 | **`EMAIL_*` fields live inside `class Settings`** | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` with 4-space indent |
| QS-10 | **`EmailEvent` model is registered in `app/models/__init__.py`** | `_patch_models_init` appends `from app.models.email_event import EmailEvent  # noqa: F401` |
| QS-11 | **Migration is chained to current head** | `find_migration_head(versions_dir)` called; falls back to `"0001_initial"` |
| QS-12 | **Router registered in `app/routes/__init__.py`** | `_patch_routes_init` injects import + `api_router.include_router(email_events_router)` |
| QS-13 | **`execution_time_ms` is set on every return path** | `_elapsed_ms(start)` called on success, no_op, dry_run, and error branches |
| QS-14 | **Prerequisites validated before any write** | `ensure_prerequisites(BASE_MODEL, MODELS_INIT, CONFIG_SETTINGS, ROUTES_INIT, ALEMBIC_VERSIONS, REQUIREMENTS_TXT)` runs first |
| QS-15 | **`next_steps` include `alembic` and provider SDK install guidance** | Hard-coded strings in success branch |

---

## 6. Completeness Criteria

Every criterion is tied to a real assertion in `test_add_transactional_email.py`.

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | Tool returns `status="success"` on a fresh project | `result.status == "success"` | T-01 (`test_success_status`) |
| CC-02 | Second run returns `status="no_op"` with zero file ops | `r2.status == "no_op"` and both lists empty | T-02 (`test_idempotent`) |
| CC-03 | `dry_run=True` writes zero bytes to the filesystem | `before == after` dict over every `.py` in tree | T-03 (`test_dry_run`) |
| CC-04 | Tool creates at least 8 new files | `len(result.files_created) >= 8` and each path exists | T-04 (`test_files_created_count`) |
| CC-05 | Tool modifies at least 2 existing files | `len(result.files_modified) >= 2` and each path exists | T-05 (`test_files_modified_count`) |
| CC-06 | Every generated `.py` AST-parses cleanly | `ast.parse` over all `.py` files in project tree | T-06 (`test_all_py_parse`) |
| CC-07 | No generated function exceeds 50 LOC in `app/` | AST walk of `FunctionDef`/`AsyncFunctionDef`, `max_loc <= 50` | T-07 (`test_no_function_over_50_loc`) |
| CC-08 | `EMAIL_PROVIDER` exists inside `class Settings` body with 4-space indent | String scan + indent check | T-08 (`test_config_fields_patched`) |
| CC-09 | `EmailEvent` is registered in `app/models/__init__.py` | `"EmailEvent" in content` of `models/__init__.py` | T-09 (`test_models_init_patched`) |
| CC-10 | Email router is registered in `app/routes/__init__.py` | `"email" in content.lower()` of `routes/__init__.py` | T-10 (`test_routes_registered`) |
| CC-11 | `app/email/providers/__init__.py` contains `get_provider` | File exists + `"get_provider" in content` | T-11 (`test_providers_package_created`) |
| CC-12 | All three provider files exist with correct class names | `ResendProvider`, `PostmarkProvider`, `SendgridProvider` found | T-12 (`test_provider_adapters_created`) |
| CC-13 | `app/email/delivery_tracker.py` contains `DeliveryTracker` and `_redact_email` | File exists + substring checks | T-13 (`test_delivery_tracker_created`) |
| CC-14 | `app/models/email_event.py` exists and declares `class EmailEvent` | File exists + `"class EmailEvent" in content` | T-14 (`test_email_event_model_created`) |
| CC-15 | `app/api/routes/email_events.py` contains `email_webhook` and `list_email_events` | File exists + substring checks | T-15 (`test_email_routes_created`) |
| CC-16 | Alembic migration file exists and references `email_events` table | File exists + `"email_events" in content` | T-16 (`test_migration_created`) |
| CC-17 | `recipient_redacted` is the only PII-adjacent field in the model | `"recipient_redacted" in content` and `"recipient:" not in content` of model file | T-17 (`test_pii_safe_model`) |
| CC-18 | `execution_time_ms` is a positive integer on the success path | `result.execution_time_ms > 0` | T-18 (`test_execution_time_recorded`) |
| CC-19 | `next_steps` include `alembic` and provider SDK install guidance | Lowercased join of `next_steps` contains `"alembic"` and `"pip install"` | T-19 (`test_next_steps_mention_alembic_and_pip`) |
| CC-20 | Running the tool twice leaves the project AST-parseable | `ast.parse` over all `.py` files after two runs | T-20 (`test_idempotent_project_still_parses`) |

---

## 7. Definition of Done (DoD)

- [ ] All 20 Completeness Criteria verified by `test_add_transactional_email.py`
- [ ] `add_transactional_email.py` runs `ast.parse` on every created `.py` file before returning success
- [ ] `add_transactional_email.py` detects `"DeliveryTracker"` fingerprint and returns `status="no_op"` on second run
- [ ] `dry_run=True` returns success with empty `files_created`/`files_modified`
- [ ] All three provider SDKs are lazy-imported (inside method bodies, not at module level)
- [ ] `_redact_email` is applied before every `EmailEvent` insert — never the full address
- [ ] API keys (`RESEND_API_KEY`, etc.) are read from `settings` at call time, never logged
- [ ] `EMAIL_*` fields anchored inside `class Settings` on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30`
- [ ] `_patch_models_init` idempotently appends `EmailEvent` import
- [ ] `_patch_routes_init` idempotently registers `email_events_router`
- [ ] `find_migration_head` used to chain migration to current head
- [ ] Webhook route `email_webhook` returns `{"status": "ok"}` for unknown providers (no 4xx/5xx)
- [ ] `execution_time_ms` is set on every return path (success, no_op, dry_run, error)
- [ ] Tool exits within 5 s on a fresh fixture project
- [ ] `MCP_TOOL` descriptor exposes `{name, description, tags, entry}` quartet

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-EMAIL-01 | The tool is ALWAYS idempotent on second invocation | Fingerprint check `"DeliveryTracker" in delivery_tracker.py` short-circuits to `status="no_op"` | T-02, T-20 |
| INV-EMAIL-02 | `dry_run=True` NEVER writes to disk | Early return guarded by `if inp.dry_run:` before any write | T-03 |
| INV-EMAIL-03 | Every generated `.py` file MUST parse as valid Python | Final loop `for path in files_created: if .py: ast.parse(p.read_text())` | T-06, T-20 |
| INV-EMAIL-04 | Recipient address MUST be redacted before any DB write | `_redact_email(recipient)` called inside `DeliveryTracker.track()` — never the raw address | T-13, T-17 |
| INV-EMAIL-05 | Provider SDKs MUST be lazy-imported inside method bodies | `import resend`, `from postmarker...`, `from sendgrid...` are inside `send()` / `__call__()` — never at module level | T-12 |
| INV-EMAIL-06 | API keys MUST be read from `settings` at call time — never logged | Adapter reads `settings.RESEND_API_KEY` etc. immediately before use; no `logger.info(key)` | T-08 |
| INV-EMAIL-07 | `EmailEvent` MUST be registered in `app/models/__init__.py` | `_patch_models_init` appends import idempotently | T-09 |
| INV-EMAIL-08 | `EMAIL_*` settings MUST live inside `class Settings` body | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` with 4-space indent | T-08 |
| INV-EMAIL-09 | Alembic migration MUST be chained to the current head | `find_migration_head(versions_dir) or "0001_initial"` | T-16 |
| INV-EMAIL-10 | `webhook/{provider}` route MUST return 200 for unknown providers | `_parse_webhook` returns `("", "", "")` for unknown; tracker skips; route returns `{"status": "ok"}` | T-15 |
| INV-EMAIL-11 | `ToolResult.execution_time_ms` MUST be positive on every return path | `_elapsed_ms(start)` called on success, no_op, dry_run, and error branches | T-18 |
| INV-EMAIL-12 | `next_steps` MUST reference `alembic` and `pip install` for provider SDK | Hard-coded strings in the success branch | T-19 |

---

## 9. User Stories

### 9.1 Core install flow (US-01 .. US-05)

**US-01: Install email layer into a clean FastAPI project**
- **As a** backend engineer who needs transactional email
- **I want** to run one tool call and get all three providers wired up
- **So that** I stop hard-coding a single SDK everywhere
- **Given:** FastAPI project with `app/core/config.py`, `app/models/base.py`, `alembic/versions/`, `requirements.txt`
- **When:** `add_transactional_email(ToolInput(project_dir=...))`
- **Then:**
  - Returns `ToolResult.status == "success"` (INV-EMAIL-01)
  - `files_created` contains ≥ 8 paths (CC-04)
  - `files_modified` contains ≥ 2 paths (CC-05)
  - Verified by T-01, T-04, T-05

**US-02: Re-run the tool on an already-installed project**
- **As a** CI job that re-runs tooling on every commit
- **I want** the tool to skip work when already applied
- **So that** I do not corrupt the project
- **Given:** Project where `app/email/delivery_tracker.py` already contains `DeliveryTracker`
- **When:** `add_transactional_email(...)` invoked a second time
- **Then:**
  - Returns `status="no_op"` (INV-EMAIL-01)
  - `files_created == []` and `files_modified == []`
  - All `.py` files still AST-parse (INV-EMAIL-03)
  - Verified by T-02, T-20

**US-03: Dry-run to preview changes**
- **As a** developer reviewing a tool invocation
- **I want** to see what would change without touching files
- **So that** I can audit before committing
- **Given:** Fresh FastAPI fixture project
- **When:** `add_transactional_email(ToolInput(project_dir=..., dry_run=True))`
- **Then:**
  - Returns `status="success"` with informational notes
  - `files_created == []` and `files_modified == []`
  - Filesystem byte-identical before and after (INV-EMAIL-02)
  - Verified by T-03

**US-04: Switch provider via env var**
- **As a** platform engineer migrating from Resend to Postmark
- **I want** to change `EMAIL_PROVIDER=postmark` in `.env`
- **So that** all email calls automatically use Postmark without code changes
- **Given:** `get_provider()` reads `settings.EMAIL_PROVIDER` at call time
- **When:** `EMAIL_PROVIDER=postmark` is set in environment
- **Then:**
  - `get_provider()` returns `PostmarkProvider()` instance
  - No application code changes required (QS-7)
  - Verified by T-11

**US-05: Generated project stays auditable**
- **As a** code reviewer
- **I want** every generated function to be short
- **So that** I can read and approve it
- **Given:** Tool just emitted provider adapters, tracker, routes
- **When:** I AST-walk `app/` for functions
- **Then:**
  - No `FunctionDef`/`AsyncFunctionDef` has `end_lineno - lineno + 1 > 50` (QS-4)
  - Verified by T-07

### 9.2 Provider adapters (US-06 .. US-10)

**US-06: Send via Resend without crashing when SDK absent**
- **As a** developer in a fresh Docker image without `resend` installed
- **I want** the app to start cleanly
- **So that** SDK absence is a runtime error not a boot error
- **Given:** `resend` package not installed; `EMAIL_PROVIDER=resend`
- **When:** `ResendProvider().send(...)` is called
- **Then:**
  - `ImportError("resend package is required: pip install resend")` raised
  - App does NOT crash at boot (QS-7)
  - Verified by T-12

**US-07: All three provider adapters share the same interface**
- **As a** developer writing a generic `send_welcome_email` helper
- **I want** `provider.send(to=, subject=, html=, from_address=, text=)` to work regardless of provider
- **So that** I write the call once
- **Given:** Three distinct provider classes
- **When:** Each is instantiated and `send()` is called with the same kwargs
- **Then:**
  - All three accept `to`, `subject`, `html`, `from_address`, `text` keyword arguments (T-12)

**US-08: Postmark adapter uses `postmarker` SDK**
- **As a** Postmark customer
- **I want** the Postmark adapter to use the official `postmarker` SDK
- **So that** I get native response types (MessageID)
- **Given:** `EMAIL_PROVIDER=postmark`
- **When:** `PostmarkProvider().send(...)` is called
- **Then:**
  - `from postmarker.core import PostmarkClient` imported lazily inside `send()`
  - Returns `str(response.get("MessageID", ""))` (T-12)

**US-09: SendGrid adapter includes `text/plain` fallback**
- **As a** sender wanting accessibility
- **I want** `text=` kwarg forwarded to SendGrid
- **So that** email clients without HTML support see plain text
- **Given:** `EMAIL_PROVIDER=sendgrid`; `text="Plain text fallback"`
- **When:** `SendgridProvider().send(..., text="Plain text fallback")`
- **Then:**
  - `Content("text/plain", text)` added to `Mail` object (T-12)

**US-10: PII is never stored after delivery tracking**
- **As a** privacy officer
- **I want** recipient email addresses redacted before any DB write
- **So that** a database dump cannot reveal user emails
- **Given:** `DeliveryTracker.track(recipient="jane@example.com", ...)`
- **When:** Tracker writes the `EmailEvent` row
- **Then:**
  - `recipient_redacted = "j***@example.com"` in DB
  - `"jane@example.com"` never appears in any column (INV-EMAIL-04)
  - Verified by T-13, T-17

### 9.3 Webhook routes (US-11 .. US-15)

**US-11: Ingest a Resend delivery event**
- **As a** Resend webhook consumer
- **I want** `POST /email/webhook/resend` to record the event
- **So that** operators can audit delivery rates
- **Given:** Resend sends `{"type": "delivered", "data": {"email_id": "abc", "to": ["user@example.com"]}}`
- **When:** Webhook POST received
- **Then:**
  - `event_type="delivered"`, `message_id="abc"` extracted by `_parse_webhook`
  - `DeliveryTracker.track()` called; `EmailEvent` row inserted
  - Returns `{"status": "ok"}` (INV-EMAIL-10, T-15)

**US-12: Ingest a Postmark delivery event**
- **As a** Postmark webhook consumer
- **I want** `POST /email/webhook/postmark` to parse Postmark's schema
- **So that** events record correctly
- **Given:** Postmark sends `{"RecordType": "Delivery", "MessageID": "xyz", "Recipient": "u@e.com"}`
- **When:** Webhook POST received
- **Then:**
  - `event_type="delivery"`, `message_id="xyz"` extracted
  - Row inserted; returns `{"status": "ok"}` (T-15)

**US-13: Ingest a SendGrid delivery event**
- **As a** SendGrid webhook consumer
- **I want** `POST /email/webhook/sendgrid` to handle SendGrid's array format
- **So that** bulk event batches parse correctly
- **Given:** SendGrid sends `[{"event": "delivered", "sg_message_id": "sgid", "email": "u@e.com"}]`
- **When:** Webhook POST received
- **Then:**
  - First element parsed; `event_type="delivered"` extracted (T-15)

**US-14: Unknown provider returns 200, not 4xx**
- **As a** provider that sends webhook retries on 4xx
- **I want** unknown provider URLs to return 200
- **So that** providers do not retry-loop
- **Given:** `POST /email/webhook/unknown_provider`
- **When:** Request received
- **Then:**
  - `_parse_webhook` returns `("", "", "")` for unknown provider
  - Tracker skips (empty event_type check)
  - Returns `{"status": "ok"}` (INV-EMAIL-10, T-15)

**US-15: List recent delivery events**
- **As a** support engineer
- **I want** `GET /email/events?limit=20`
- **So that** I can diagnose delivery issues
- **Given:** Several `EmailEvent` rows exist
- **When:** `GET /email/events?limit=20`
- **Then:**
  - Returns `EmailEventList` with `items` (newest first) and `total`
  - `recipient_redacted` field shown; full address never present (T-15)

### 9.4 Audit model and migration (US-16 .. US-20)

**US-16: EmailEvent model has correct columns**
- **As a** DBA reviewing the schema
- **I want** the `email_events` table to have `message_id`, `event_type`, `recipient_redacted`, `provider`, `occurred_at`
- **So that** I can query delivery status
- **Given:** Migration applied
- **When:** Schema inspected
- **Then:**
  - All five columns present with correct types (T-14, T-16)

**US-17: `message_id` is indexed**
- **As a** developer correlating webhook events with outbound message IDs
- **I want** `message_id` indexed
- **So that** provider webhook lookups are O(1)
- **Given:** `EmailEvent` model with `index=True` on `message_id`
- **When:** `SELECT ... WHERE message_id = ?`
- **Then:**
  - Planner uses index; no sequential scan (T-14)

**US-18: Migration chained to current head**
- **As a** team using incremental migrations
- **I want** `down_revision` pointing to the current Alembic head
- **So that** `alembic upgrade head` works in sequence
- **Given:** Project with an existing migration chain
- **When:** Tool generates migration
- **Then:**
  - `down_revision` matches `find_migration_head()` result (INV-EMAIL-09, T-16)

**US-19: `downgrade()` drops the table cleanly**
- **As a** developer rolling back
- **I want** `alembic downgrade -1` to remove the `email_events` table
- **So that** rollback leaves a clean state
- **Given:** Migration has `downgrade()` function
- **When:** `downgrade()` runs
- **Then:**
  - `op.drop_table("email_events")` executed (T-16)

**US-20: EmailEvent registered in models `__init__`**
- **As a** SQLAlchemy Base that uses `metadata.create_all()`
- **I want** `EmailEvent` imported in `app/models/__init__.py`
- **So that** Alembic discovers the table automatically
- **Given:** `_patch_models_init` ran
- **When:** `import app.models` is evaluated
- **Then:**
  - `EmailEvent` is in scope; `Base.metadata.tables["email_events"]` accessible (INV-EMAIL-07, T-09)

### 9.5 Config, requirements, and operator experience (US-21 .. US-25)

**US-21: Config fields bind from environment variables**
- **As an** ops engineer
- **I want** `EMAIL_PROVIDER=sendgrid` in `.env` to take effect
- **So that** I do not rebuild images for provider changes
- **Given:** pydantic-settings reads `class Settings`
- **When:** `Settings()` instantiated at boot
- **Then:**
  - `EMAIL_PROVIDER` inside `class Settings` picks up env var (INV-EMAIL-08)
  - Verified by T-08

**US-22: No provider SDK required at boot**
- **As a** Docker image with minimal dependencies
- **I want** the app to start even when all three provider SDKs are absent
- **So that** I install only what I use
- **Given:** `resend`, `postmarker`, `sendgrid` not installed
- **When:** App starts
- **Then:**
  - No `ImportError` at boot; lazy imports only triggered on `send()` call (INV-EMAIL-05, T-12)

**US-23: `next_steps` guide operator to install and configure**
- **As a** developer who just ran the tool
- **I want** `next_steps` to include `alembic` and provider SDK install
- **So that** I do not miss post-install steps
- **Given:** Success return path
- **When:** Caller inspects `result.next_steps`
- **Then:**
  - Contains `"alembic upgrade head"` and at least one `"pip install"` item (INV-EMAIL-12, T-19)

**US-24: Execution time is recorded**
- **As a** CI pipeline measuring tool overhead
- **I want** `execution_time_ms` to be set
- **So that** I can flag regressions
- **Given:** Tool executes normally
- **When:** Result inspected
- **Then:**
  - `result.execution_time_ms > 0` (INV-EMAIL-11, T-18)

**US-25: Second run does not add duplicate model imports**
- **As a** developer who accidentally re-runs tools
- **I want** `models/__init__.py` to remain parseable with exactly one `EmailEvent` import
- **So that** my code review sees a clean diff
- **Given:** Tool ran twice
- **When:** `app/models/__init__.py` read
- **Then:**
  - Exactly one `from app.models.email_event import EmailEvent` line (T-20, INV-EMAIL-01)

---

## 10. Test Plan

All 20 tests live in `adapt/extend/infrastructure/test_add_transactional_email.py` and each test creates a fresh fixture project via `create_fixture_project(name=...)`.

### 10.1 Category A — Tool execution (T-01 .. T-05)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | `test_success_status` | Fixture `email_t01` | `add_transactional_email(ToolInput(project_dir))` | `result.status == "success"` (INV-EMAIL-01, CC-01) |
| T-02 | `test_idempotent` | Fixture `email_t02`; run tool once | Run tool a second time | `r2.status == "no_op"`; both lists empty (INV-EMAIL-01, CC-02) |
| T-03 | `test_dry_run` | Fixture `email_t03`; snapshot all `.py` | `add_transactional_email(ToolInput(dry_run=True))` | `status == "success"`; empty lists; byte-identical FS (INV-EMAIL-02, CC-03) |
| T-04 | `test_files_created_count` | Fixture `email_t04` | Run tool | `len(files_created) >= 8`; every path exists (CC-04) |
| T-05 | `test_files_modified_count` | Fixture `email_t05` | Run tool | `len(files_modified) >= 2`; every path exists (CC-05) |

### 10.2 Category B — Generated code quality (T-06 .. T-10)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-06 | `test_all_py_parse` | Fixture `email_t06`; run tool | AST-parse every `.py` in project | No `SyntaxError` (INV-EMAIL-03, CC-06) |
| T-07 | `test_no_function_over_50_loc` | Fixture `email_t07`; run tool | AST walk over `app/` for `FunctionDef`/`AsyncFunctionDef` | `max_loc <= 50` (QS-4, CC-07) |
| T-08 | `test_config_fields_patched` | Fixture `email_t08`; run tool | Read `app/core/config.py` | Contains `EMAIL_PROVIDER`; line starts with 4-space indent (INV-EMAIL-08, CC-08) |
| T-09 | `test_models_init_patched` | Fixture `email_t09`; run tool | Read `app/models/__init__.py` | Contains `"EmailEvent"` (INV-EMAIL-07, CC-09) |
| T-10 | `test_routes_registered` | Fixture `email_t10`; run tool | Read `app/routes/__init__.py` | Contains `"email"` (case-insensitive) (CC-10) |

### 10.3 Category C — Domain-specific modules (T-11 .. T-17)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-11 | `test_providers_package_created` | Fixture `email_t11`; run tool | Read `app/email/providers/__init__.py` | File exists; contains `"get_provider"` (INV-EMAIL-05, CC-11) |
| T-12 | `test_provider_adapters_created` | Fixture `email_t12`; run tool | Read all three provider files | `ResendProvider`, `PostmarkProvider`, `SendgridProvider` present; provider SDKs imported inside `send()` body (INV-EMAIL-05, CC-12) |
| T-13 | `test_delivery_tracker_created` | Fixture `email_t13`; run tool | Read `app/email/delivery_tracker.py` | Contains `DeliveryTracker` and `_redact_email` (INV-EMAIL-04, CC-13) |
| T-14 | `test_email_event_model_created` | Fixture `email_t14`; run tool | Read `app/models/email_event.py` | File exists; contains `"class EmailEvent"`, `"message_id"`, `"recipient_redacted"` (CC-14) |
| T-15 | `test_email_routes_created` | Fixture `email_t15`; run tool | Read `app/api/routes/email_events.py` | Contains `email_webhook` and `list_email_events` (CC-15) |
| T-16 | `test_migration_created` | Fixture `email_t16`; run tool | Read `alembic/versions/add_email_events.py` | File exists; contains `"email_events"` and non-placeholder `down_revision` (INV-EMAIL-09, CC-16) |
| T-17 | `test_pii_safe_model` | Fixture `email_t17`; run tool | Read `app/models/email_event.py` | Contains `"recipient_redacted"`; does NOT contain bare `"recipient:"` column (INV-EMAIL-04, CC-17) |

### 10.4 Category D — Meta (T-18 .. T-20)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-18 | `test_execution_time_recorded` | Fixture `email_t18`; run tool | Read `result.execution_time_ms` | `> 0` (INV-EMAIL-11, CC-18) |
| T-19 | `test_next_steps_mention_alembic_and_pip` | Fixture `email_t19`; run tool | Lowercase-join `result.next_steps` | Contains `"alembic"` and `"pip install"` (INV-EMAIL-12, CC-19) |
| T-20 | `test_idempotent_project_still_parses` | Fixture `email_t20`; run tool twice | AST-parse every `.py` | No `SyntaxError` (INV-EMAIL-01, INV-EMAIL-03, CC-20) |

### 10.5 Test execution

```bash
PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_transactional_email.py -v
```

Target: 20/20 passed, 0 failed.

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| `add_arq_worker` (TOOL-053) | No | ✅ Compatible | `send_email_task` in arq's TASK_REGISTRY is the natural target for async email sends; `get_provider().send(...)` called from inside the task |
| `add_email_templates` (TOOL-055) | Yes — TOOL-055 runs AFTER | ✅ Compatible | TOOL-055 renders Jinja2 HTML; `html=` kwarg passed to adapter's `send()` |
| `add_stripe_checkout` (TOOL-054) | No | ✅ Compatible | Payment confirmation emails sent via `get_provider().send(...)` from Stripe webhook handler |
| `add_multi_tenancy` (TOOL-008) | No | ✅ Compatible | `email_events` table has no tenant FK by default; add manually if per-tenant delivery tracking is needed |
| `add_webhook_receiver` (TOOL-016) | No | ✅ Compatible | Provider delivery webhooks arrive via `POST /email/webhook/{provider}` — same webhook receiver infrastructure |
| `add_rate_limiting` | No | ⚠️ Caveat | Rate-limit `POST /email/webhook/{provider}` by IP to protect against webhook floods; do NOT rate-limit by user |
| `add_audit_log` (TOOL-005) | No | ✅ Compatible | `email_events` provides native audit trail; no need to duplicate in the audit log table |
| `add_rbac` (TOOL-012) | Yes — RBAC runs AFTER | ⚠️ Caveat | Add `require("email:read")` guard to `GET /email/events` after RBAC is installed |
| `add_cursor_pagination` (TOOL-002) | No | ✅ Compatible | `list_email_events` can be cursor-paginated by `occurred_at DESC` |
| `add_soft_delete` (TOOL-001) | No | ⚠️ Caveat | `EmailEvent` rows MUST NOT use soft-delete — delivery audit must be irrevocable |

**Conflicts:** None identified. The email layer is self-contained; `get_provider()` is a pure function with no global state.

---

## 12. Rollback Procedure

### 12.1 Code rollback (before deploy)

```bash
git checkout HEAD -- \
  app/core/config.py \
  app/models/__init__.py \
  app/routes/__init__.py

rm -rf \
  app/email/ \
  app/models/email_event.py \
  app/schemas/email_event.py \
  app/api/routes/email_events.py \
  alembic/versions/add_email_events.py
```

### 12.2 Database rollback (after deploy)

```bash
alembic downgrade -1   # drops email_events table
```

### 12.3 Data preservation

Archive before downgrade if delivery records are compliance-relevant:

```sql
CREATE TABLE email_events_archive_<date> AS SELECT * FROM email_events;
```

---

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-01 | Tool runs on a project with no `app/` directory | `validate_project_dir` fails → `status="error"` with `execution_time_ms > 0` |
| EC-02 | Missing prerequisites (`CONFIG_SETTINGS`, etc.) | `ensure_prerequisites` errors → `status="error"` with list of missing prereqs |
| EC-03 | `app/email/delivery_tracker.py` already contains `DeliveryTracker` | Early return `status="no_op"` — zero file writes |
| EC-04 | `dry_run=True` on fresh project | Returns `status="success"` with notes; filesystem unchanged (INV-EMAIL-02) |
| EC-05 | `app/core/config.py` already contains `EMAIL_PROVIDER` | `_patch_config` early-returns; no duplicate block |
| EC-06 | `app/core/config.py` lacks `ACCESS_TOKEN_EXPIRE_MINUTES` anchor | Falls back to inserting before `settings = Settings()`; if absent, appends at EOF |
| EC-07 | `alembic/versions/` missing | Migration step skipped silently; other writes proceed |
| EC-08 | `app/models/__init__.py` already imports `EmailEvent` | `_patch_models_init` early-returns after marker check — no duplicate line |
| EC-09 | `app/routes/__init__.py` already contains email router | `_patch_routes_init` early-returns; no duplicate `include_router` |
| EC-10 | Provider webhook payload has unexpected schema | `_parse_webhook` returns `("", "", "")` → tracker skips; route returns `{"status": "ok"}` |
| EC-11 | `find_migration_head` returns `None` | Migration `down_revision = "0001_initial"` — still a valid chain root |
| EC-12 | `app/schemas/` directory missing | Created via `mkdir(parents=True, exist_ok=True)` before schema file write |
| EC-13 | `app/api/routes/` directory missing | Created via `mkdir(parents=True, exist_ok=True)` before routes file write |
| EC-14 | Email address has no `@` (malformed) | `_redact_email` returns `"***@***"` — no crash, no PII leak |
| EC-15 | Tool runs twice back-to-back via CI | Second run returns `no_op`; project AST remains parseable (T-20) |

---

## 14. Security Considerations

| # | Concern | Mitigation |
|---|---------|------------|
| SEC-01 | API keys in logs | Keys read from `settings` at call time; no `logger.*` statement emits key values (INV-EMAIL-06) |
| SEC-02 | PII in database | `_redact_email()` applied before every `EmailEvent.recipient_redacted` write; full address never persisted (INV-EMAIL-04) |
| SEC-03 | Webhook endpoint open to abuse | Webhook route at `POST /email/webhook/{provider}` is unauthenticated by design (providers cannot present user tokens); rate-limit by IP in production |
| SEC-04 | Email injection via `from_address` | `from_address` is a string parameter; adapters pass it directly to provider SDK which validates it; no server-side header injection possible via the HTTP/JSON API |
| SEC-05 | Delivery events enumerable via `GET /email/events` | Route should be guarded by admin role after `add_rbac` is installed; add `CurrentUser` gate at minimum |

---

## 15. Observability

| Signal | Location | Notes |
|--------|----------|-------|
| `email.delivery` log line | `DeliveryTracker.track()` | `provider`, `event_type`, `msg_id` logged at INFO |
| `email_webhook: unknown provider` warning | `_parse_webhook()` | Emitted at WARNING when `provider` not in {resend, postmark, sendgrid} |
| `send()` errors | Each provider adapter | Unhandled exceptions propagate to caller; adapt to background task for retry |
| `email_events` table | PostgreSQL | Full audit trail; query `SELECT event_type, COUNT(*) FROM email_events GROUP BY 1` for delivery stats |

---

## 16. Changelog

| Version | Date | Change |
|---------|------|--------|
| v1 | 2026-04-15 | Initial spec — Resend, Postmark, SendGrid adapters; DeliveryTracker; PII-safe model; 20 CCs |
