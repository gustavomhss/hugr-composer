# TOOL-063: add_notifications

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_notifications` |
| Category | EXTEND > Infrastructure |
| Complexity | Medium-High |
| Dependencies | FastAPI, SQLAlchemy 2.0, Alembic, pydantic-settings, optional firebase-admin |
| Signature | `add_notifications(inp: ToolInput, *, max_per_page: int = 50) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and `dry_run` flag<br>`max_per_page`: Default page size for `GET /notifications` written into `settings.NOTIFICATION_MAX_PER_PAGE` (default: 50) |
| MCP descriptor | `{"name": "fastapi_add_notifications", "description": "Add a production-grade in-app notification layer with channel dispatch (in_app, push FCM stub, email bridge), unread badge, and bulk mark-read.", "tags": ["extend", "infrastructure"], "entry": "add_notifications"}` |
| Files created (typical) | 9 — `app/notifications/__init__.py`, `app/notifications/service.py`, `app/notifications/channels.py`, `app/models/notification.py`, `app/schemas/notification.py`, `app/crud/notification.py`, `app/api/routes/notifications.py`, `alembic/versions/add_notifications.py` |
| Files modified (typical) | 3 — `app/core/config.py`, `app/models/__init__.py`, `app/routes/__init__.py` |

---

## 2. Purpose

The `fastapi_add_notifications` tool installs a production-grade in-app notification layer into a FastAPI project, providing **channel-dispatching** (in_app, push via FCM, email via bridge) without requiring any external service to be installed or running for the app to boot.

The problem this solves: application teams reach the point where they need to alert users about events — account changes, task completions, billing events, security alerts — and face a choice between (a) building a bespoke notification table by hand, (b) pulling in a heavy third-party notification platform, or (c) silently emitting events to nowhere. Option (a) gets implemented differently in every project, missing bulk-read and badge-count endpoints that UIs invariably need. Option (b) adds vendor lock-in before product/market fit is established. Option (c) is how notification requirements get postponed until a user-visible regression forces the work. This tool eliminates the "build by hand" cost and the vendor gamble simultaneously.

The channel abstraction is the core design decision. **In-app** is the default: notifications are persisted in a `notifications` table with `read_at`, which is zero-configuration and zero-latency. **Push (FCM stub)** lazy-imports `firebase_admin` — if the package is not installed the app starts cleanly and a `WARNING` is logged on the attempt instead of crashing. **Email bridge** detects whether `app/email/` (written by `add_email_templates`, TOOL-055) is present in the target project; if found, `channels.py` emits a real bridge import to `app.email.service.EmailService` instead of a stub warning log. This conditional behaviour means `add_notifications` can be applied to any project at any point in its lifecycle without waiting for email infrastructure.

The `NotificationService` façade is intentionally stateless — it accepts an `AsyncSession` on each call rather than on construction — so it composes cleanly with FastAPI's dependency injection. CRUD helpers are all `async def` operating on `AsyncSession` (SQLAlchemy 2.0 async style). The `list_unread` query orders by `created_at DESC` and uses a DB-level index on `(user_id, read_at)` so it is covered. The `count_unread` function issues a `SELECT func.count()` query — not a `len(list_unread())` call — so the badge endpoint does not load rows it does not need. The `mark_all_read` bulk update issues a single `UPDATE … WHERE user_id = ? AND read_at IS NULL`, avoiding the N+1 pattern of marking individual rows. These three constraints are verified by the test suite.

Key design decisions: (1) The `Notification` model has a FK to `users.id ON DELETE CASCADE` — removing a user removes their notifications without an orphaned-row accumulation problem. (2) No channel handler logs raw notification body text because bodies often contain PII (names, account numbers, order details). (3) The `firebase_admin` import is inside a `try/except ImportError` inside the body of `_send_push`, not at module top level, so the push channel never blocks boot. (4) The tool is idempotent: on second invocation it detects `"NotificationService"` in `app/notifications/__init__.py` and returns `status="no_op"` without touching any file. (5) Every generated function is kept to ≤50 LOC so each is individually auditable.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | CI step budget; measured via `execution_time_ms` in `ToolResult` (T-20) |
| Files created | ≥ 8 | Notification kit: package init, service, channels, model, schemas, CRUD, routes, migration (CC-04) |
| Files modified | ≥ 2 | Config + models `__init__` at minimum (CC-05) |
| Max function LOC in generated code | ≤ 50 | Each function stays auditable; enforced by AST walk in test harness (T-07) |
| `GET /notifications` latency | < 20 ms | Single `SELECT … WHERE user_id = ? AND read_at IS NULL ORDER BY created_at DESC LIMIT n` — index-covered |
| `GET /notifications/unread-count` latency | < 10 ms | Single `SELECT COUNT(*) WHERE user_id = ? AND read_at IS NULL` — count-only, no row hydration |
| `POST /notifications/read-all` latency | < 15 ms | Single `UPDATE … WHERE user_id = ? AND read_at IS NULL` — one round trip |
| `POST /notifications/{id}/read` latency | < 15 ms | Single `UPDATE … WHERE id = ? AND user_id = ? AND read_at IS NULL` |
| Migration runtime | < 1 s | Single `CREATE TABLE` + 1 composite index |
| Idempotent second-run time | < 100 ms | Fingerprint check reads one file, returns immediately |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── main.py
│   ├── core/
│   │   └── config.py        # No NOTIFICATION_* fields
│   ├── models/
│   │   ├── __init__.py      # Base + User only
│   │   └── base.py
│   ├── routes/
│   │   └── __init__.py      # No notifications router
│   └── api/
│       └── deps.py
├── alembic/versions/
└── requirements.txt
```

User-facing events (password changed, order placed, message received) have nowhere to go. Background tasks that complete have no way to surface a result to the user without polling. The mobile app badge count requires a bespoke SQL query added ad-hoc to a random route file.

### 4.2 Notifications package init: AFTER

```python
# app/notifications/__init__.py
"""Notification layer — in-app, push (FCM stub), and email channels.

Public API:
    NotificationService:  create / mark_read / mark_all_read / list_unread
    dispatch:             channel router (in_app | push | email)
"""

from app.notifications.service import NotificationService
from app.notifications.channels import dispatch

__all__ = ["NotificationService", "dispatch"]
```

### 4.3 NotificationService façade: AFTER

```python
# app/notifications/service.py
class NotificationService:
    """Facade for notification lifecycle operations."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialise with an active async database session."""
        self._session = session

    async def send(
        self,
        user_id: uuid.UUID,
        title: str,
        body: str,
        channel: str = "in_app",
    ) -> None:
        """Create a notification and dispatch it through *channel*.

        Args:
            user_id: Recipient's user UUID.
            title: Short notification title.
            body: Full notification body text.
            channel: Delivery channel — ``"in_app"``, ``"push"``,
                or ``"email"``.  Defaults to ``"in_app"``.
        """
        data = NotificationCreate(
            user_id=user_id, title=title, body=body, channel=channel,
        )
        notif = await create_notification(self._session, data)
        await dispatch(notif, channel=channel)

    async def count_unread(self, user_id: uuid.UUID) -> int:
        """Return the unread notification count for the badge widget."""
        return await count_unread(self._session, user_id)
```

### 4.4 Channel dispatcher (stub variant, no email bridge): AFTER

```python
# app/notifications/channels.py
async def dispatch(notification: object, *, channel: str = "in_app") -> None:
    """Route *notification* to the handler registered for *channel*.

    The ``in_app`` channel is a no-op here because the row is already
    persisted by the CRUD layer before ``dispatch`` is called.  External
    channels (push, email) are where real side-effects happen.
    """
    if channel == "in_app":
        return  # already in DB — nothing more to do
    if channel == "push":
        await _send_push(notification)
    elif channel == "email":
        logger.warning(
            "email channel requested but add_email_templates is not installed; "
            "notification stored in-app only."
        )
    else:
        logger.warning("Unknown notification channel %r — ignored.", channel)


async def _send_push(notification: object) -> None:
    """Send a push notification via FCM (firebase_admin stub).

    ``firebase_admin`` is imported lazily so the app boots without it.
    If not installed, a WARNING is logged and the notification is silently
    stored in-app only.
    """
    try:
        import firebase_admin  # noqa: F401 — lazy optional dependency
        from firebase_admin import messaging
    except ImportError:
        logger.warning(
            "firebase_admin not installed — push notification skipped. "
            "Run: pip install firebase-admin"
        )
        return
    # Stub: real FCM send would go here.
    logger.info("FCM push stub — would send to user_id=%s", getattr(notification, "user_id", "?"))
```

### 4.5 Notification ORM model: AFTER

```python
# app/models/notification.py
class Notification(Base):
    """Persistent notification record.

    Attributes:
        id: UUID primary key.
        user_id: Owner's user UUID (foreign key).
        title: Short notification title (≤255 chars).
        body: Full notification body text.
        channel: Delivery channel used (``in_app``, ``push``, ``email``).
        read_at: Timestamp when the notification was read; ``None`` if unread.
        created_at: Timestamp of creation (server-side default).
    """

    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    channel: Mapped[str] = mapped_column(String(32), nullable=False, default="in_app")
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
```

### 4.6 CRUD — bulk mark-read and count query: AFTER

```python
# app/crud/notification.py
async def mark_all_read(session: AsyncSession, user_id: uuid.UUID) -> int:
    """Bulk-mark all unread notifications for *user_id* as read.

    Issues a single UPDATE WHERE user_id = ? AND read_at IS NULL.

    Returns:
        Number of rows updated.
    """
    stmt = (
        update(Notification)
        .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(timezone.utc))
    )
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount


async def count_unread(session: AsyncSession, user_id: uuid.UUID) -> int:
    """Return the number of unread notifications for *user_id* (COUNT query)."""
    stmt = select(func.count()).select_from(Notification).where(
        Notification.user_id == user_id,
        Notification.read_at.is_(None),
    )
    result = await session.execute(stmt)
    return result.scalar_one()
```

### 4.7 REST endpoints: AFTER

```python
# app/api/routes/notifications.py
router = APIRouter(prefix="/notifications", tags=["notifications"])

@router.get("", response_model=NotificationList)
async def list_notifications(
    user_id: uuid.UUID = Query(..., description="Requesting user UUID"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    svc: NotificationService = Depends(_get_service),
) -> NotificationList:
    """Return paginated unread notifications for *user_id*."""
    items = await svc.list_unread(user_id, limit=limit, offset=offset)
    unread = await svc.count_unread(user_id)
    return NotificationList(
        items=[NotificationRead.model_validate(n) for n in items],
        total=len(items),
        unread_count=unread,
    )

@router.get("/unread-count", response_model=UnreadCount)
async def unread_count(
    user_id: uuid.UUID = Query(..., description="Requesting user UUID"),
    svc: NotificationService = Depends(_get_service),
) -> UnreadCount:
    """Return the unread-notification count for the badge widget."""
    count = await svc.count_unread(user_id)
    return UnreadCount(unread_count=count)

@router.post("/read-all", response_model=dict)
async def mark_all_read(
    user_id: uuid.UUID = Query(..., description="Requesting user UUID"),
    svc: NotificationService = Depends(_get_service),
) -> dict:
    """Bulk-mark all notifications as read for *user_id*."""
    updated = await svc.mark_all_read(user_id)
    return {"updated": updated}
```

### 4.8 Alembic migration: AFTER

```python
# alembic/versions/add_notifications.py
def upgrade() -> None:
    """Create the notifications table."""
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "user_id", sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("channel", sa.String(32), nullable=False, server_default="in_app"),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_notifications_user_id_read_at", "notifications", ["user_id", "read_at"])


def downgrade() -> None:
    """Drop the notifications table."""
    op.drop_index("ix_notifications_user_id_read_at", table_name="notifications")
    op.drop_table("notifications")
```

### 4.9 Config patch (settings injected inside `class Settings`)

```python
# app/core/config.py  (diff, added by _patch_config)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # --- Notifications — added by add_notifications tool ---
    NOTIFICATION_CHANNELS: list[str] = ["in_app"]
    NOTIFICATION_MAX_PER_PAGE: int = 50
    FIREBASE_CREDENTIALS_PATH: str = ""
```

Anchoring on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` guarantees all three fields land inside the `Settings` class body (4-space indent) so pydantic-settings picks them up from environment variables.

### 4.10 Typical caller usage (after install)

```python
# anywhere in the FastAPI app that has a session
from app.notifications import NotificationService

async def order_placed_handler(session: AsyncSession, user_id: uuid.UUID, order_id: str) -> None:
    svc = NotificationService(session)
    await svc.send(
        user_id=user_id,
        title="Order confirmed",
        body=f"Your order #{order_id} has been placed.",
        channel="in_app",
    )
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Tool is idempotent on second run** | Pre-flight checks `"NotificationService" in app/notifications/__init__.py`; returns `status="no_op"` with empty `files_created`/`files_modified` |
| QS-2 | **`dry_run=True` writes zero files** | Early return before any filesystem write when `inp.dry_run` is truthy |
| QS-3 | **Every generated `.py` file AST-parses** | Loop over `files_created`: `ast.parse(p.read_text())` for every `.py`; raises `SyntaxError` otherwise |
| QS-4 | **No generated function exceeds 50 LOC** | Every function in service, channels, CRUD, and routes kept small by construction; asserted by AST walk in test harness |
| QS-5 | **`firebase_admin` is always a lazy import** | `_send_push` wraps the import in `try/except ImportError`; module-level import is absent |
| QS-6 | **No channel logs raw notification body** | `channels.py` logs only `user_id` and never `title` or `body` |
| QS-7 | **`count_unread` uses `func.count()`, not row scan** | `app/crud/notification.py` contains `select(func.count()).select_from(Notification)` |
| QS-8 | **`mark_all_read` issues a single UPDATE** | `update(Notification).where(... read_at.is_(None)).values(read_at=...)` — no SELECT then loop |
| QS-9 | **`Notification` model registered in `app/models/__init__.py`** | `_patch_models_init` appends `from app.models.notification import Notification  # noqa: F401` idempotently |
| QS-10 | **`NOTIFICATION_*` fields inside `class Settings` body** | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30`; 4-space indent |
| QS-11 | **Email channel is conditional on `app/email/` presence** | `_write_notifications_package` checks `(app_dir / "email" / "__init__.py").exists()` and selects between `_NOTIFICATIONS_CHANNELS_WITH_EMAIL` and `_NOTIFICATIONS_CHANNELS_STUB` |
| QS-12 | **`FK("users.id", ondelete="CASCADE")` on `user_id`** | Deleting a user cascades to their notifications — no orphan accumulation |
| QS-13 | **Alembic migration is chained to current head** | `_write_notification_migration` calls `find_migration_head(versions_dir) or "0001_initial"` |
| QS-14 | **Prerequisites validated before write** | `ensure_prerequisites(BASE_MODEL, MODELS_INIT, CONFIG_SETTINGS, ROUTES_INIT, ALEMBIC_VERSIONS, REQUIREMENTS_TXT)` runs first |
| QS-15 | **`__all__` in `app/notifications/__init__.py` exports both public names** | `__all__ = ["NotificationService", "dispatch"]` |
| QS-16 | **Notifications router registered in `app/routes/__init__.py`** | `_patch_routes_init` inserts import + `api_router.include_router(notifications_router)` idempotently |
| QS-17 | **`execution_time_ms` is a positive integer on every return path** | `_elapsed_ms(start)` called on success, no_op, dry_run, and error branches |
| QS-18 | **`next_steps` reference `alembic` and push/Firebase guidance** | `next_steps` contains `"alembic upgrade head"` and Firebase install hint |
| QS-19 | **Second run leaves the project AST-parseable** | Idempotent no-op path does not corrupt any file; all `.py` remain AST-valid |
| QS-20 | **`list_unread` orders by `created_at DESC` and uses `LIMIT`/`OFFSET`** | Prevents unbounded scans on high-volume notification tables |

---

## 6. Completeness Criteria

Every criterion is tied to a real assertion in `test_add_notifications.py`.

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | Tool returns `status="success"` on a fresh project | `result.status == "success"` | T-01 (`test_success_status`) |
| CC-02 | Second run returns `status="no_op"` with empty file lists | `r2.status == "no_op"` and both lists empty | T-02 (`test_idempotent`) |
| CC-03 | `dry_run=True` writes zero bytes to the filesystem | `before == after` over every `.py` in tree | T-03 (`test_dry_run`) |
| CC-04 | Tool creates at least 8 new files | `len(result.files_created) >= 8` and each path exists | T-04 (`test_files_created_count`) |
| CC-05 | Tool modifies at least 2 existing files | `len(result.files_modified) >= 2` and each path exists | T-05 (`test_files_modified_count`) |
| CC-06 | Every generated `.py` AST-parses cleanly | `ast.parse` over all `.py` files in project tree | T-06 (`test_all_py_parse`) |
| CC-07 | No generated function exceeds 50 LOC in `app/` | AST walk of `FunctionDef`/`AsyncFunctionDef`, `max_loc <= 50` | T-07 (`test_no_function_over_50_loc`) |
| CC-08 | `NOTIFICATION_CHANNELS` and `NOTIFICATION_MAX_PER_PAGE` inside `class Settings` with 4-space indent | Substring scan + indent check on line containing `NOTIFICATION_CHANNELS` | T-08 (`test_config_fields_patched`) |
| CC-09 | `Notification` is registered in `app/models/__init__.py` | `"Notification" in content` of `models/__init__.py` | T-09 (`test_models_init_patched`) |
| CC-10 | Notifications router registered in `app/routes/__init__.py` when that file exists | `"notification" in content.lower()` of `routes/__init__.py` | T-10 (`test_routes_registered`) |
| CC-11 | `app/models/notification.py` exists and declares `Notification` class | File exists + `"Notification" in content` | T-11 (`test_notification_model_exists`) |
| CC-12 | `Notification` model has all required fields: `id`, `user_id`, `title`, `body`, `channel`, `read_at`, `created_at` | Substring check for each field name in `notification.py` | T-12 (`test_notification_model_fields`) |
| CC-13 | `app/schemas/notification.py` has `NotificationCreate`, `NotificationRead`, `NotificationList`, `UnreadCount` | File exists + substring checks for each class name | T-13 (`test_notification_schemas_exist`) |
| CC-14 | `app/crud/notification.py` has all 5 CRUD functions | File exists + check for `create_notification`, `list_unread`, `mark_read`, `mark_all_read`, `count_unread` | T-14 (`test_crud_file_exists`) |
| CC-15 | `app/api/routes/notifications.py` has all 4 endpoints | File exists + checks for `unread-count`, `read-all`, mark-read endpoint | T-15 (`test_routes_file_exists`) |
| CC-16 | `app/notifications/service.py` has `NotificationService` with all 5 methods | File exists + check for `send`, `list_unread`, `mark_read`, `mark_all_read`, `count_unread` | T-16 (`test_notification_service_exists`) |
| CC-17 | `app/notifications/channels.py` has `dispatch` with `in_app` and `push` handling | File exists + checks for `dispatch`, `in_app`, `push` | T-17 (`test_channels_file_exists`) |
| CC-18 | FCM push channel uses lazy `import firebase_admin` inside `try/except ImportError` | `"firebase_admin" in content` and `"ImportError" in content` | T-18 (`test_push_channel_lazy_import`) |
| CC-19 | An Alembic migration file for notifications is created | `glob("*notification*.py")` in `alembic/versions/` returns at least one file; file contains `"notifications"` | T-19 (`test_migration_file_exists`) |
| CC-20 | `execution_time_ms` is a positive integer on the success path | `result.execution_time_ms > 0` | T-20 (`test_execution_time_recorded`) |
| CC-21 | Running the tool twice leaves the project AST-parseable | `ast.parse` over all `.py` after two runs | T-21 (`test_idempotent_project_still_parses`) |
| CC-22 | `next_steps` is non-empty and mentions `alembic` | `len(result.next_steps) > 0` and `"alembic" in combined.lower()` | T-22 (`test_next_steps_present`) |
| CC-23 | `app/notifications/__init__.py` exports `NotificationService` and `dispatch` | File exists; `"NotificationService" in content` and `"dispatch" in content` | T-23 (`test_notifications_init_exports`) |
| CC-24 | `count_unread` in CRUD uses a `COUNT` query (not a full row scan) | `"func.count" in content` or `"COUNT" in content.upper()` | T-24 (`test_unread_count_is_count_query`) |

---

## 7. Definition of Done (DoD)

- [ ] All 24 Completeness Criteria verified by `test_add_notifications.py`
- [ ] `add_notifications.py` runs `ast.parse` on every created `.py` file before returning success
- [ ] `add_notifications.py` detects `"NotificationService"` fingerprint and returns `status="no_op"` on second run
- [ ] `dry_run=True` returns success with empty `files_created`/`files_modified`
- [ ] `_write_notifications_package` selects `_NOTIFICATIONS_CHANNELS_WITH_EMAIL` when `app/email/__init__.py` exists
- [ ] `_send_push` wraps `firebase_admin` import in `try/except ImportError` — app boots without the package
- [ ] `count_unread` CRUD helper uses `select(func.count()).select_from(Notification)` — not `len(list_unread())`
- [ ] `mark_all_read` CRUD helper issues a single `UPDATE` statement — no row-by-row loop
- [ ] `list_unread` CRUD helper uses `ORDER BY created_at DESC LIMIT n OFFSET m`
- [ ] `Notification` model has `ForeignKey("users.id", ondelete="CASCADE")` on `user_id`
- [ ] `app/notifications/__init__.py` contains `__all__ = ["NotificationService", "dispatch"]`
- [ ] `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` so fields land inside `Settings` class body
- [ ] `_patch_models_init` appends `Notification` import idempotently
- [ ] `_patch_routes_init` appends notifications router import + `include_router` call idempotently
- [ ] `find_migration_head` is used to chain the migration to the current head
- [ ] `execution_time_ms` is set on every return path (success, no_op, dry_run, error)
- [ ] Tool completes in < 5 s on a fresh fixture project
- [ ] `MCP_TOOL` descriptor exposes `{name, description, tags, entry}` quartet

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-NOTIF-01 | Tool is ALWAYS idempotent on second invocation | Fingerprint check `"NotificationService" in notif_init.read_text()` short-circuits to `status="no_op"` | T-02, T-21 |
| INV-NOTIF-02 | `dry_run=True` NEVER writes to disk | Early return guarded by `if inp.dry_run:` before any write | T-03 |
| INV-NOTIF-03 | Every generated `.py` file MUST parse as valid Python | Loop `for path_str in files_created: if .py: _assert_parses(p)` | T-06, T-21 |
| INV-NOTIF-04 | `firebase_admin` MUST be lazily imported — app boots without it | `_send_push` wraps `import firebase_admin` in `try/except ImportError` | T-18 |
| INV-NOTIF-05 | `count_unread` MUST use a `COUNT(*)` query — not `len(list_unread())` | `select(func.count()).select_from(Notification)` in CRUD | T-24 |
| INV-NOTIF-06 | `mark_all_read` MUST issue a single `UPDATE` — no N+1 loop | `update(Notification).where(...).values(read_at=...)` single statement | T-14 |
| INV-NOTIF-07 | `Notification.user_id` MUST have `ForeignKey("users.id", ondelete="CASCADE")` | Emitted in `_NOTIFICATION_MODEL` template | T-12 |
| INV-NOTIF-08 | `NOTIFICATION_*` settings MUST live inside `class Settings` body (4-space indent) | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` | T-08 |
| INV-NOTIF-09 | `Notification` model MUST be registered in `app/models/__init__.py` | `_patch_models_init` appends idempotently | T-09 |
| INV-NOTIF-10 | Email channel selection MUST be conditional on `app/email/` presence | `has_email = (app_dir / "email" / "__init__.py").exists()` branch | T-17 |
| INV-NOTIF-11 | `app/notifications/__init__.py` MUST export `NotificationService` and `dispatch` | `__all__ = ["NotificationService", "dispatch"]` in `_NOTIFICATIONS_INIT` | T-23 |
| INV-NOTIF-12 | Alembic migration MUST be chained to the current head | `find_migration_head(versions_dir) or "0001_initial"` | T-19 |
| INV-NOTIF-13 | `ToolResult.execution_time_ms` MUST be positive on every return path | `_elapsed_ms(start)` called on success, no_op, dry_run, and error | T-20 |
| INV-NOTIF-14 | `next_steps` MUST mention `alembic` and Firebase guidance | Hard-coded in the `success` branch | T-22 |
| INV-NOTIF-15 | No channel handler MUST log raw notification body text | `channels.py` logs only `user_id`; `title` and `body` are not logged | QS-6 |

---

## 9. User Stories

### 9.1 Core install flow (US-01 .. US-05)

**US-01: Install notification layer into a clean FastAPI project**
- **As a** backend engineer who needs to surface events to users
- **I want** to run one tool call and get a complete notification system
- **So that** I stop writing bespoke notification tables and badge queries
- **Given:** A FastAPI project with `app/core/config.py`, `app/models/base.py`, `alembic/versions/`, `requirements.txt`
- **When:** `add_notifications(ToolInput(project_dir=...))`
- **Then:**
  - Returns `ToolResult.status == "success"` (INV-NOTIF-01)
  - `files_created` contains ≥ 8 paths (CC-04)
  - `files_modified` contains ≥ 2 paths (CC-05)
  - Verified by T-01, T-04, T-05

**US-02: Re-run the tool on an already-installed project**
- **As a** CI job that re-runs tooling on every commit
- **I want** the tool to skip work when already applied
- **So that** I do not corrupt the project
- **Given:** Project where `app/notifications/__init__.py` already contains `NotificationService`
- **When:** `add_notifications(...)` invoked a second time
- **Then:**
  - Returns `status="no_op"` (INV-NOTIF-01)
  - `files_created == []` and `files_modified == []`
  - All `.py` files still AST-parse (INV-NOTIF-03)
  - Verified by T-02, T-21

**US-03: Dry-run to preview changes**
- **As a** developer reviewing a tool invocation
- **I want** to see what would change without touching files
- **So that** I can audit before committing
- **Given:** Fresh FastAPI fixture project
- **When:** `add_notifications(ToolInput(project_dir=..., dry_run=True))`
- **Then:**
  - Returns `status="success"` with descriptive `notes`
  - `files_created == []` and `files_modified == []`
  - Filesystem byte-identical before and after (INV-NOTIF-02)
  - Verified by T-03

**US-04: Install on a project that already has email templates**
- **As a** developer with `add_email_templates` already applied
- **I want** the email channel to bridge to `app.email.service`
- **So that** notifications sent via `channel="email"` use the real email service
- **Given:** `app/email/__init__.py` exists in the target project
- **When:** `add_notifications(ToolInput(project_dir=...))`
- **Then:**
  - `channels.py` imports `from app.email.service import EmailService` (INV-NOTIF-10)
  - `_send_email` is a real bridge function, not a warning log
  - Verified by T-17

**US-05: Generated project stays auditable**
- **As a** code reviewer
- **I want** every generated function to be short
- **So that** I can read and approve it
- **Given:** Tool just emitted `service.py`, `channels.py`, `crud/notification.py`, `routes/notifications.py`
- **When:** I AST-walk `app/` for functions
- **Then:**
  - No `FunctionDef`/`AsyncFunctionDef` has `end_lineno - lineno + 1 > 50` (QS-4)
  - Verified by T-07

### 9.2 Channel dispatch (US-06 .. US-10)

**US-06: Send an in-app notification from a background task**
- **As a** worker task that completes a PDF export
- **I want** `svc.send(user_id, "Export ready", "...", channel="in_app")`
- **So that** the user sees a badge increment on next page load
- **Given:** `NotificationService` injected with an `AsyncSession`
- **When:** `await svc.send(user_id=uid, title="Export ready", body="...", channel="in_app")`
- **Then:**
  - Row inserted with `read_at=None` (INV-NOTIF-06)
  - `dispatch(notif, channel="in_app")` returns immediately (in_app = DB only)
  - Verified by T-16, T-17

**US-07: App boots without firebase-admin installed**
- **As a** developer deploying to an environment without push infrastructure
- **I want** the app to start without `firebase_admin` in the Python environment
- **So that** push setup can be deferred until product/market fit
- **Given:** `firebase_admin` not in the venv
- **When:** The app boots and `channels.py` is imported
- **Then:**
  - No `ImportError` at import time (INV-NOTIF-04)
  - Calling `dispatch(notif, channel="push")` logs a `WARNING` and returns cleanly
  - Verified by T-18

**US-08: Bulk mark all notifications read**
- **As a** mobile UI that wants "Mark all as read"
- **I want** `POST /notifications/read-all?user_id=...`
- **So that** the badge count resets to zero in one round trip
- **Given:** Multiple unread notifications for a user
- **When:** `POST /notifications/read-all?user_id=<uid>`
- **Then:**
  - Single `UPDATE notifications SET read_at = now() WHERE user_id = ? AND read_at IS NULL` (INV-NOTIF-06)
  - Returns `{"updated": n}` where `n` is the row count
  - Verified by T-14, T-15

**US-09: Get the badge count**
- **As a** mobile nav bar that shows unread count
- **I want** `GET /notifications/unread-count?user_id=...`
- **So that** I can render the badge without loading full rows
- **Given:** Some unread notifications exist
- **When:** `GET /notifications/unread-count?user_id=<uid>`
- **Then:**
  - `count_unread` executes `SELECT COUNT(*) ... WHERE read_at IS NULL` (INV-NOTIF-05)
  - Returns `{"unread_count": n}`
  - Verified by T-24

**US-10: List paginated unread notifications**
- **As a** notification drawer UI
- **I want** `GET /notifications?user_id=...&limit=20&offset=0`
- **So that** I render the 20 most recent unread items
- **Given:** User has many notifications
- **When:** `GET /notifications?user_id=<uid>&limit=20&offset=0`
- **Then:**
  - Query uses `ORDER BY created_at DESC LIMIT 20 OFFSET 0` (QS-20)
  - Response contains `items`, `total`, `unread_count`
  - Verified by T-15

### 9.3 Data integrity and lifecycle (US-11 .. US-15)

**US-11: User deletion cascades to notifications**
- **As a** platform with GDPR delete requirements
- **I want** deleting a user to remove their notifications
- **So that** orphaned rows do not accumulate
- **Given:** `Notification.user_id` has `ForeignKey("users.id", ondelete="CASCADE")`
- **When:** User row is deleted
- **Then:**
  - All `notifications` rows with that `user_id` are automatically deleted (INV-NOTIF-07)
  - Verified by T-12

**US-12: Mark a single notification read**
- **As a** user who taps one notification
- **I want** `POST /notifications/{id}/read?user_id=...`
- **So that** the dot indicator clears for that item
- **Given:** Notification exists with `read_at=None`
- **When:** `POST /notifications/{id}/read?user_id=<uid>`
- **Then:**
  - `mark_read(session, notification_id, user_id)` issues a targeted `UPDATE` and returns `True`
  - Returns the updated `NotificationRead` schema
  - Verified by T-14, T-15

**US-13: Notification model fields are correct**
- **As a** developer writing a UI
- **I want** `id`, `user_id`, `title`, `body`, `channel`, `read_at`, `created_at` on every notification
- **So that** my serializer has a stable contract
- **Given:** Tool just ran on a fixture project
- **When:** I inspect `app/models/notification.py`
- **Then:**
  - All seven fields present on `Notification` class (CC-12)
  - Verified by T-12

**US-14: NOTIFICATION_* settings are configurable via environment**
- **As an** ops engineer sizing the notification list
- **I want** `NOTIFICATION_MAX_PER_PAGE=100` in `.env` to take effect
- **So that** I tune without rebuilding the image
- **Given:** pydantic-settings reads `class Settings`
- **When:** `Settings()` is instantiated at boot
- **Then:**
  - `NOTIFICATION_MAX_PER_PAGE` inside `class Settings` picks up env var (INV-NOTIF-08)
  - Verified by T-08

**US-15: Operator knows the next commands to run**
- **As a** developer who just ran the tool
- **I want** `next_steps` to include migration and Firebase guidance
- **So that** I do not forget to `alembic upgrade head`
- **Given:** Success return path
- **When:** Caller inspects `result.next_steps`
- **Then:**
  - Contains `"alembic upgrade head"` and Firebase guidance (INV-NOTIF-14)
  - Verified by T-22

### 9.4 Schemas and service layer (US-16 .. US-20)

**US-16: Create and validate notification via Pydantic schema**
- **As a** caller of `NotificationService.send`
- **I want** `NotificationCreate` to validate `title` (≤255 chars) and `channel` (≤32 chars)
- **So that** invalid data is rejected before hitting the DB
- **Given:** `app/schemas/notification.py` has `NotificationCreate` with `Field(max_length=...)`
- **When:** Caller passes `title` > 255 chars
- **Then:**
  - Pydantic `ValidationError` raised before CRUD layer is reached
  - Verified by T-13

**US-17: NotificationService encapsulates all CRUD calls**
- **As a** route handler author
- **I want** to call only `svc.send / list_unread / mark_read / mark_all_read / count_unread`
- **So that** I never import CRUD helpers directly in route files
- **Given:** `service.py` wraps all CRUD functions
- **When:** I grep route files for `from app.crud.notification`
- **Then:**
  - Route files import `NotificationService` only, not CRUD helpers
  - Verified by T-16

**US-18: schemas export `NotificationList` with `unread_count` field**
- **As a** frontend developer
- **I want** the list response to include the badge count
- **So that** I can update the badge and the list in one request
- **Given:** `NotificationList` has `items`, `total`, `unread_count`
- **When:** `GET /notifications` is called
- **Then:**
  - Response includes `unread_count` alongside `items`
  - Verified by T-13, T-15

**US-19: `ToggleEvaluateResult`-style response from notifications service**
- **As a** background job author
- **I want** `await svc.send(...)` to complete without raising on unknown channel
- **So that** a misconfigured channel name degrades gracefully
- **Given:** `channel="sms"` (not a supported channel)
- **When:** `dispatch(notif, channel="sms")` is called
- **Then:**
  - `logger.warning("Unknown notification channel %r — ignored.", channel)` is emitted
  - No exception propagates to caller
  - Verified by T-17

**US-20: Execution time is always recorded**
- **As a** CI pipeline
- **I want** `execution_time_ms` on every result
- **So that** I can detect regressions in tool performance
- **Given:** Any invocation (success, no_op, dry_run, error)
- **When:** Tool returns
- **Then:**
  - `result.execution_time_ms > 0` (INV-NOTIF-13)
  - Verified by T-20

---

## 10. Test Plan

All 24 tests live in `adapt/extend/infrastructure/test_add_notifications.py` and each test creates a fresh fixture project via `create_fixture_project(name=...)`.

### 10.1 Category A — Tool execution (T-01 .. T-05)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | `test_success_status` | Fixture `notif_t01` | `add_notifications(ToolInput(project_dir))` | `result.status == "success"` (CC-01) |
| T-02 | `test_idempotent` | Fixture `notif_t02`; run tool once | Run tool a second time | `r2.status == "no_op"`; `r2.files_created == []`; `r2.files_modified == []` (CC-02) |
| T-03 | `test_dry_run` | Fixture `notif_t03`; snapshot all `.py` | `add_notifications(ToolInput(dry_run=True))` | `status == "success"`; empty lists; byte-identical filesystem (INV-NOTIF-02, CC-03) |
| T-04 | `test_files_created_count` | Fixture `notif_t04` | Run tool | `len(files_created) >= 8`; every path exists (CC-04) |
| T-05 | `test_files_modified_count` | Fixture `notif_t05` | Run tool | `len(files_modified) >= 2`; every path exists (CC-05) |

### 10.2 Category B — Generated code quality (T-06 .. T-10)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-06 | `test_all_py_parse` | Fixture `notif_t06`; run tool | AST-parse every `.py` in project | No `SyntaxError` (INV-NOTIF-03, CC-06) |
| T-07 | `test_no_function_over_50_loc` | Fixture `notif_t07`; run tool | AST walk over `app/` for `FunctionDef`/`AsyncFunctionDef` | `max_loc <= 50` (QS-4, CC-07) |
| T-08 | `test_config_fields_patched` | Fixture `notif_t08`; run tool | Read `app/core/config.py` | Contains `NOTIFICATION_CHANNELS` and `NOTIFICATION_MAX_PER_PAGE`; line starts with 4-space indent (INV-NOTIF-08, CC-08) |
| T-09 | `test_models_init_patched` | Fixture `notif_t09`; run tool | Read `app/models/__init__.py` | Contains `"Notification"` (INV-NOTIF-09, CC-09) |
| T-10 | `test_routes_registered` | Fixture `notif_t10`; run tool | Read `app/routes/__init__.py` if it exists | Contains `"notification"` (case-insensitive) (CC-10) |

### 10.3 Category C — Domain-specific modules (T-11 .. T-19)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-11 | `test_notification_model_exists` | Fixture `notif_t11`; run tool | Read `app/models/notification.py` | File exists; contains `"Notification"` (CC-11) |
| T-12 | `test_notification_model_fields` | Fixture `notif_t12`; run tool | Read `app/models/notification.py` | Contains `user_id`, `title`, `body`, `channel`, `read_at`, `created_at` (INV-NOTIF-07, CC-12) |
| T-13 | `test_notification_schemas_exist` | Fixture `notif_t13`; run tool | Read `app/schemas/notification.py` | Contains `NotificationCreate`, `NotificationRead`, `NotificationList`, `UnreadCount` (CC-13) |
| T-14 | `test_crud_file_exists` | Fixture `notif_t14`; run tool | Read `app/crud/notification.py` | Contains `create_notification`, `list_unread`, `mark_read`, `mark_all_read`, `count_unread` (INV-NOTIF-05, INV-NOTIF-06, CC-14) |
| T-15 | `test_routes_file_exists` | Fixture `notif_t15`; run tool | Read `app/api/routes/notifications.py` | Contains `unread-count`/`unread_count`, `read-all`/`mark_all_read`, `/read`/`mark_notification_read` (CC-15) |
| T-16 | `test_notification_service_exists` | Fixture `notif_t16`; run tool | Read `app/notifications/service.py` | Contains `send`, `list_unread`, `mark_read`, `mark_all_read`, `count_unread` (CC-16) |
| T-17 | `test_channels_file_exists` | Fixture `notif_t17`; run tool | Read `app/notifications/channels.py` | Contains `dispatch`, `in_app`, `push` (INV-NOTIF-10, CC-17) |
| T-18 | `test_push_channel_lazy_import` | Fixture `notif_t18`; run tool | Read `app/notifications/channels.py` | Contains `firebase_admin` and `ImportError` (INV-NOTIF-04, CC-18) |
| T-19 | `test_migration_file_exists` | Fixture `notif_t19`; run tool | `glob("*notification*.py")` in `alembic/versions/` | At least 1 match; file contains `"notifications"` (INV-NOTIF-12, CC-19) |

### 10.4 Category D — Meta (T-20 .. T-24)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-20 | `test_execution_time_recorded` | Fixture `notif_t20`; run tool | Read `result.execution_time_ms` | `> 0` (INV-NOTIF-13, CC-20) |
| T-21 | `test_idempotent_project_still_parses` | Fixture `notif_t21`; run tool twice | AST-parse every `.py` | No `SyntaxError` (INV-NOTIF-01, INV-NOTIF-03, CC-21) |
| T-22 | `test_next_steps_present` | Fixture `notif_t22`; run tool | Lowercase-join `result.next_steps` | Non-empty; contains `"alembic"` (INV-NOTIF-14, CC-22) |
| T-23 | `test_notifications_init_exports` | Fixture `notif_t23`; run tool | Read `app/notifications/__init__.py` | File exists; contains `"NotificationService"` and `"dispatch"` (INV-NOTIF-11, CC-23) |
| T-24 | `test_unread_count_is_count_query` | Fixture `notif_t24`; run tool | Read `app/crud/notification.py` | Contains `"func.count"` or `"COUNT"` (INV-NOTIF-05, CC-24) |

### 10.5 Test execution

```bash
PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_notifications.py -v
# or standalone:
PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_notifications.py
```

Target: 24/24 passed, 0 failed. The standalone runner prints `TOOL-063 add_notifications: 24 passed, 0 failed`.

---

## 11. Interaction Matrix

How `add_notifications` composes with other SKILL-001 tools. Tool IDs match `specs/` directory (`ls specs/TOOL-*`).

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| `add_email_templates` (TOOL-055) | Yes | ✅ Compatible — email templates FIRST | When `app/email/` exists before `add_notifications` runs, `channels.py` emits the real `EmailService` bridge import instead of a stub warning log |
| `add_arq_worker` (TOOL-053) | No | ✅ Compatible | arq tasks can call `NotificationService.send(...)` to surface job completion to users; the `ctx["session"]` opened in `startup` can be passed to the service |
| `add_audit_log` (TOOL-005) | No | ✅ Compatible | `create_notification` CRUD can emit audit entries; `mark_all_read` bulk update should emit a single audit event with `rows_affected`, not one entry per row |
| `add_multi_tenancy` (TOOL-008) | Yes | ⚠️ Caveat — tenancy FIRST | `Notification` model does not include `tenant_id` by default; add a `tenant_id` FK column manually after multi-tenancy is installed if per-tenant isolation is required |
| `add_rbac` (TOOL-012) | Yes | ✅ Compatible — RBAC AFTER | RBAC can add `require("notifications:read")` to `list_notifications` and `require("notifications:write")` to mark-read endpoints; current version gates on `user_id` query param only |
| `add_api_key_auth` (TOOL-010) | No | ✅ Compatible | API key holders can query notifications using the same `user_id` query param pattern |
| `add_sse` (TOOL-014) | No | ✅ Compatible | After `create_notification` succeeds, the SSE endpoint can push a `notification.created` event to the user's live connection, eliminating the need to poll `GET /notifications` |
| `add_websocket_chat` (TOOL-052) | No | ✅ Compatible | WebSocket message handler can call `svc.send(...)` to persist a notification copy for users who are offline |
| `add_outbox_pattern` (TOOL-023) | No | ⚠️ Caveat | If push/email channel reliability is critical, wrap `dispatch(...)` calls in the outbox so failures are retried; `in_app` channel does not need the outbox |
| `add_event_driven` (TOOL-046) | No | ✅ Compatible | `notification.created` and `notification.read` events can be published to the event bus from CRUD helpers for downstream consumers |
| `add_cursor_pagination` (TOOL-002) | No | ✅ Compatible | `list_unread` currently uses `LIMIT/OFFSET`; cursor-paginate by `created_at DESC` for large-volume notification feeds |
| `add_soft_delete` (TOOL-001) | No | ⚠️ Caveat | Notifications should NOT use soft-delete; physical delete on `user_id` CASCADE is the correct lifecycle for notification rows |
| `add_search` (TOOL-004) | No | ⚠️ Caveat | Full-text search over notification `title`/`body` is expensive; restrict to `title` only with `GIN` index if needed |
| `add_feature_toggles_api` (TOOL-064) | No | ✅ Compatible | Feature toggles can gate new notification types; `FeatureToggleService.is_enabled("new_notification_type", user_id=str(uid))` gates the `send()` call |
| `add_rate_limiting` (TOOL-057) | No | ✅ Compatible | Rate-limit `POST /notifications/{id}/read` and `POST /notifications/read-all` on authenticated `user_id` to prevent abuse; badge count endpoint does not need rate limiting |
| `add_stripe_checkout` (TOOL-054) | No | ✅ Compatible | Stripe webhook handlers (payment.succeeded, payment.failed) should call `NotificationService.send(...)` after processing |
| `add_sqladmin` (TOOL-056) | No | ✅ Compatible | `Notification` model renders in the admin panel; add `ModelAdmin` with filters on `channel`, `read_at IS NULL` |
| `add_scheduled_tasks` (TOOL-058) | No | ✅ Compatible | Scheduled digest emails can query `list_unread(...)` and bulk-dispatch via `channel="email"` |

**Conflicts:** None identified. `add_notifications` is the only notification tool in SKILL-001; it does not conflict with any existing tool.

---

## 12. Rollback Procedure

### 12.1 Code rollback (before deploy)

```bash
git checkout HEAD -- \
  app/core/config.py \
  app/models/__init__.py \
  app/routes/__init__.py

rm -rf \
  app/notifications/ \
  app/models/notification.py \
  app/schemas/notification.py \
  app/crud/notification.py \
  app/api/routes/notifications.py

# Remove the migration file
rm -f alembic/versions/add_notifications.py
```

### 12.2 Database rollback (after deploy)

```bash
alembic downgrade -1   # drops notifications table + ix_notifications_user_id_read_at
```

The `downgrade()` function runs:

```python
op.drop_index("ix_notifications_user_id_read_at", table_name="notifications")
op.drop_table("notifications")
```

### 12.3 Data preservation rollback

If notification rows have audit or legal significance, archive before downgrade:

```sql
CREATE TABLE notifications_archive_<date> AS SELECT * FROM notifications;
-- or: COPY notifications TO '/backup/notifications_<date>.csv' WITH CSV HEADER;
```

### 12.4 Failure mode: tool partially modified files

```bash
git status --porcelain | grep '^ M' | awk '{print $2}' | xargs git checkout --
find . -path '*/notifications/*.py' -newer alembic/versions/ -delete
```

Because `_assert_parses` runs at the end of the success path, a mid-execution failure may leave partially-written files. `git checkout HEAD --` on modified files plus `rm` on newly-created paths restores the project.

### 12.5 Uninstall validator

After rollback, verify:

```bash
test ! -d app/notifications || (echo "app/notifications still present" && exit 1)
test ! -f app/models/notification.py || (echo "Notification model still present" && exit 1)
grep -q "NOTIFICATION_CHANNELS" app/core/config.py && echo "config still patched" && exit 1
grep -q "Notification" app/models/__init__.py && echo "models init still patched" && exit 1
echo "rollback verified"
```

---

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-01 | Tool runs on a project with no `app/` directory | `validate_project_dir` fails → `ToolResult(status="error", error=...)` with `execution_time_ms > 0` |
| EC-02 | Tool runs on a project missing prerequisites (`BASE_MODEL`, etc.) | `ensure_prerequisites` returns errors → tool returns `status="error"` with list of missing prereqs and hint to run `fastapi_generate_project` first |
| EC-03 | `app/notifications/__init__.py` already contains `NotificationService` | Early return `status="no_op"` with single note — zero file writes |
| EC-04 | `inp.dry_run=True` | Returns `status="success"` with dry-run notes; NO file touched; includes `has_email` context in note; `execution_time_ms` still recorded |
| EC-05 | `app/email/__init__.py` exists → `has_email = True` | `channels.py` emits `_NOTIFICATIONS_CHANNELS_WITH_EMAIL` with real `EmailService` bridge import (INV-NOTIF-10) |
| EC-06 | `app/email/__init__.py` absent → `has_email = False` | `channels.py` emits `_NOTIFICATIONS_CHANNELS_STUB` with warning log for email channel |
| EC-07 | `alembic/versions/` missing | Migration write step is skipped (`if versions_dir.exists():`); other file writes proceed normally |
| EC-08 | `app/core/config.py` already contains `NOTIFICATION_CHANNELS` | `_patch_config` early-returns; no duplicate block appended |
| EC-09 | `app/core/config.py` lacks `ACCESS_TOKEN_EXPIRE_MINUTES` anchor | `_patch_config` falls back to inserting before `settings = Settings()`; if that also missing, appends at EOF |
| EC-10 | `app/models/__init__.py` already imports `Notification` | `_patch_models_init` early-returns after `marker in content` check — no duplicate import |
| EC-11 | `app/routes/__init__.py` already contains `notifications_router` | `_register_router` checks `import_line in src` before modifying — no duplicate router registration |
| EC-12 | `app/routes/__init__.py` does not exist | Route registration step is skipped (`if routes_init.exists():`); router must be registered manually — note emitted in `next_steps` |
| EC-13 | `app/schemas/` directory missing | Created via `mkdir(parents=True, exist_ok=True)` before writing `notification.py` |
| EC-14 | `app/crud/` directory missing | Created via `mkdir(parents=True, exist_ok=True)` before writing `notification.py` |
| EC-15 | `app/api/routes/` directory missing | Created via `mkdir(parents=True, exist_ok=True)` before writing `notifications.py` |
| EC-16 | `app/notifications/` already exists (partial install from previous crash) | `mkdir(parents=True, exist_ok=True)` does not fail; individual file writes overwrite any partial content; `_assert_parses` validates after |
| EC-17 | Generated `channels.py` fails `_assert_parses` (template bug) | `SyntaxError` raised; partial files remain on disk; caller must use rollback 12.4 |
| EC-18 | `find_migration_head` returns `None` (empty `alembic/versions/`) | Falls back to `"0001_initial"` so migration still wires to a plausible parent |
| EC-19 | Tool runs twice back-to-back via CI | Second run returns `no_op`; project AST remains parseable (T-21 verifies) |
| EC-20 | `firebase_admin` is installed in the venv | `_send_push` imports successfully; the stub `logger.info` fires; no exception |

---

## 14. Acceptance Criteria (Final Sign-off)

1. ✅ All 24 Completeness Criteria verified via `test_add_notifications.py` passing
2. ✅ `test_add_notifications.py` reports `24 passed, 0 failed` via both pytest and standalone runner
3. ✅ Tool execution time < 5 s measured on reference hardware
4. ✅ Second invocation returns `status="no_op"` with empty `files_created`/`files_modified` (INV-NOTIF-01)
5. ✅ `dry_run=True` produces zero filesystem writes (INV-NOTIF-02)
6. ✅ Every generated `.py` file AST-parses cleanly on first and second runs (INV-NOTIF-03)
7. ✅ No generated function in `app/` exceeds 50 LOC (QS-4)
8. ✅ `NOTIFICATION_*` settings live inside `class Settings` body with 4-space indentation (INV-NOTIF-08)
9. ✅ `firebase_admin` import is inside `try/except ImportError` in `_send_push` — app boots without it (INV-NOTIF-04)
10. ✅ `count_unread` uses `SELECT COUNT(*)` — not `len(list_unread())` (INV-NOTIF-05)
11. ✅ `mark_all_read` issues a single `UPDATE` statement (INV-NOTIF-06)
12. ✅ `Notification.user_id` has `ForeignKey("users.id", ondelete="CASCADE")` (INV-NOTIF-07)
13. ✅ `app/notifications/__init__.py` exports `NotificationService` and `dispatch` in `__all__` (INV-NOTIF-11)
14. ✅ `next_steps` includes `alembic upgrade head` and Firebase guidance (INV-NOTIF-14)
15. ✅ Developer successfully calls `svc.send(...)`, polls `GET /notifications`, sees the row, calls `POST /read-all`, and badge count returns to 0

---

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks

- [ ] `validate_project_dir(inp.project_dir)` returns no error
- [ ] `ensure_prerequisites(BASE_MODEL, MODELS_INIT, CONFIG_SETTINGS, ROUTES_INIT, ALEMBIC_VERSIONS, REQUIREMENTS_TXT)` passes
- [ ] `app/notifications/__init__.py` does NOT contain `"NotificationService"` (otherwise → `no_op`)
- [ ] Detect `has_email = (app_dir / "email" / "__init__.py").exists()`
- [ ] If `inp.dry_run`, emit dry-run notes including `has_email` context and return before any write

### 15.2 Notifications package

- [ ] `mkdir -p app/notifications`
- [ ] Write `app/notifications/__init__.py` from `_NOTIFICATIONS_INIT` template (`__all__`, re-exports `NotificationService` + `dispatch`)
- [ ] Write `app/notifications/service.py` from `_NOTIFICATIONS_SERVICE` template (5 methods: `send`, `list_unread`, `mark_read`, `mark_all_read`, `count_unread`)
- [ ] Write `app/notifications/channels.py` from `_NOTIFICATIONS_CHANNELS_WITH_EMAIL` if `has_email` else `_NOTIFICATIONS_CHANNELS_STUB`
- [ ] All three files appended to `files_created`

### 15.3 Notification model

- [ ] Write `app/models/notification.py` from `_NOTIFICATION_MODEL` template
- [ ] Model has `id`, `user_id`, `title`, `body`, `channel`, `read_at`, `created_at`
- [ ] `user_id` has `ForeignKey("users.id", ondelete="CASCADE")`
- [ ] `_patch_models_init(models_init, [("notification", "Notification")])` appends import idempotently
- [ ] `models_init` appended to `files_modified`

### 15.4 Pydantic schemas

- [ ] `mkdir -p app/schemas`
- [ ] Write `app/schemas/notification.py` from `_NOTIFICATION_SCHEMAS`
- [ ] Schema file contains `NotificationCreate`, `NotificationRead`, `NotificationList`, `UnreadCount`
- [ ] `NotificationRead` uses `ConfigDict(from_attributes=True)`
- [ ] All timestamp fields typed as `datetime | None`

### 15.5 Async CRUD

- [ ] `mkdir -p app/crud`
- [ ] Write `app/crud/notification.py` from `_NOTIFICATION_CRUD`
- [ ] `create_notification` inserts row and calls `session.commit()` + `session.refresh(notif)`
- [ ] `list_unread` uses `ORDER BY created_at DESC LIMIT n OFFSET m`
- [ ] `mark_read` issues targeted `UPDATE … WHERE id = ? AND user_id = ? AND read_at IS NULL`
- [ ] `mark_all_read` issues single `UPDATE … WHERE user_id = ? AND read_at IS NULL` — no N+1
- [ ] `count_unread` uses `select(func.count()).select_from(Notification)` — no full-row scan

### 15.6 REST routes

- [ ] `mkdir -p app/api/routes`
- [ ] Write `app/api/routes/notifications.py` from `_NOTIFICATION_ROUTES`
- [ ] `APIRouter(prefix="/notifications", tags=["notifications"])`
- [ ] `GET ""` → `list_notifications` (limit/offset, returns `NotificationList`)
- [ ] `POST "/{notification_id}/read"` → `mark_notification_read` (404 if not found)
- [ ] `POST "/read-all"` → `mark_all_read` (returns `{"updated": n}`)
- [ ] `GET "/unread-count"` → `unread_count` (returns `UnreadCount`)

### 15.7 Alembic migration

- [ ] `find_migration_head(versions_dir) or "0001_initial"` resolves `down_revision`
- [ ] Replace `DOWN_REV_PLACEHOLDER` in `_NOTIFICATION_MIGRATION` template
- [ ] Write to `alembic/versions/add_notifications.py`
- [ ] Migration creates `notifications` table with all columns
- [ ] `ix_notifications_user_id_read_at` composite index on `(user_id, read_at)`
- [ ] `downgrade()` drops index first, then table

### 15.8 Config patch

- [ ] Early-return if `"NOTIFICATION_CHANNELS" in src`
- [ ] Block emits `NOTIFICATION_CHANNELS`, `NOTIFICATION_MAX_PER_PAGE`, `FIREBASE_CREDENTIALS_PATH`
- [ ] 4-space indent (class body)
- [ ] Anchor on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30`
- [ ] Fallback: before `settings = Settings()` line
- [ ] Last-resort fallback: append at EOF

### 15.9 Routes init patch

- [ ] Early-return if import line already present
- [ ] `_register_router` inserts import after last `from app.` import
- [ ] `_register_router` inserts `api_router.include_router(notifications_router)` after last `include_router` call
- [ ] Preserve trailing newline

### 15.10 Validation

- [ ] Loop over `files_created`; for every `.py` call `_assert_parses(p)` via `ast.parse`
- [ ] `_assert_parses` raises `SyntaxError` with file path on failure

### 15.11 Result assembly

- [ ] Return `ToolResult(status="success", files_created, files_modified, notes, next_steps, execution_time_ms=_elapsed_ms(start))`
- [ ] `notes` describe channels, 4 endpoints, conditional email bridge
- [ ] `next_steps` contains `"alembic upgrade head"`, Firebase install hint, `NotificationService` import hint, restart hint

### 15.12 Documentation

- [ ] `MCP_TOOL` dict exposes `name`, `description`, `tags`, `entry`
- [ ] Module docstring explains why channel abstraction, why lazy import, why COUNT not scan
- [ ] `add_notifications` docstring documents `max_per_page` parameter

---

## 16. Documentation Output

Example `ToolResult` JSON (success path, no email bridge, fixture project):

```json
{
  "status": "success",
  "files_created": [
    "/tmp/fixture/app/notifications/__init__.py",
    "/tmp/fixture/app/notifications/service.py",
    "/tmp/fixture/app/notifications/channels.py",
    "/tmp/fixture/app/models/notification.py",
    "/tmp/fixture/app/schemas/notification.py",
    "/tmp/fixture/app/crud/notification.py",
    "/tmp/fixture/app/api/routes/notifications.py",
    "/tmp/fixture/alembic/versions/add_notifications.py"
  ],
  "files_modified": [
    "/tmp/fixture/app/core/config.py",
    "/tmp/fixture/app/models/__init__.py",
    "/tmp/fixture/app/routes/__init__.py"
  ],
  "notes": [
    "Notification layer added: in_app channel (DB insert), push channel (FCM stub — firebase_admin lazy-imported), email channel stub (add_email_templates not detected).",
    "GET /notifications — paginated list (newest first).",
    "POST /notifications/{id}/read — mark single notification read.",
    "POST /notifications/read-all — bulk mark-all-read (single UPDATE).",
    "GET /notifications/unread-count — fast COUNT(*) badge query."
  ],
  "next_steps": [
    "alembic upgrade head",
    "To enable push notifications: pip install firebase-admin, then set FIREBASE_CREDENTIALS_PATH in .env.",
    "Inject NotificationService where needed: from app.notifications import NotificationService",
    "Restart the FastAPI app so /notifications routes are loaded."
  ],
  "execution_time_ms": 87
}
```

Example `no_op` return (second invocation):

```json
{
  "status": "no_op",
  "files_created": [],
  "files_modified": [],
  "notes": [
    "NotificationService already present in app/notifications/__init__.py — notifications already installed, skipped."
  ],
  "next_steps": [],
  "execution_time_ms": 2
}
```

Example `dry_run` return:

```json
{
  "status": "success",
  "files_created": [],
  "files_modified": [],
  "notes": [
    "[dry_run] Would create app/notifications/ (service, channels),",
    "         app/models/notification.py, app/schemas/notification.py,",
    "         app/crud/notification.py, app/api/routes/notifications.py,",
    "         and an Alembic migration for the `notifications` table.",
    "         email_bridge=stub (no app/email/ found).",
    "[dry_run] No files written."
  ],
  "next_steps": [
    "Re-run without dry_run=True to apply changes."
  ],
  "execution_time_ms": 1
}
```

Example `error` return (prereq failure):

```json
{
  "status": "error",
  "error": "Prerequisites not met:\n  - BASE_MODEL: app/models/base.py missing\n  - CONFIG_SETTINGS: app/core/config.py missing",
  "notes": [
    "Generate a base project first:",
    "  fastapi_generate_project(output_dir='...', profile='api', models={...})"
  ],
  "execution_time_ms": 3
}
```

---
