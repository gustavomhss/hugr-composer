"""Regression tests for W2 batch — close ALL remaining B0.14 waivers.

Closes the final 11 entries in ``r_write_schemas_strict._WAIVED_TOOLS``
in a single PR. Pattern is structural: each write schema gets
``model_config = ConfigDict(extra="forbid")``; genuinely opaque
``dict``/``Any``/``list[Any]`` fields get a ``# pragma: schema-any: ...``
bypass (Jinja2 template context, framework-specific ML metric blobs,
framework-defined model input).

After this PR ``_WAIVED_TOOLS`` is empty — B0.14 covers every write
schema template in the catalog with no exceptions.

One parametrized assertion per tool covers:

* Each declared write schema in the template carries ``extra="forbid"``
  in its ``model_config`` (parsed at runtime via Pydantic introspection
  rather than AST so we catch real Pydantic behaviour, not just
  syntactic appearance).
* The tool is NOT in ``_WAIVED_TOOLS``.

Plus per-tool behaviour assertions for the smuggling defence (unknown
keys must raise ``ValidationError``).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent.parent
sys.path.insert(0, str(SKILL_ROOT))


# ---------------------------------------------------------------------------
# Template loader — same shape the rule uses, so the template
# can be exec'd here without touching the live ``adapt/`` import path.
# ---------------------------------------------------------------------------

_PLACEHOLDER_BRACED_RE = re.compile(r"\$\{[^}]+\}")
_PLACEHOLDER_BARE_RE = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*")


def _clean(src: str) -> str:
    src = _PLACEHOLDER_BRACED_RE.sub("PLACEHOLDER", src)
    src = _PLACEHOLDER_BARE_RE.sub("PLACEHOLDER", src)
    return src


def _exec_template(path: Path) -> dict:
    """Compile + exec a ``.py.tmpl`` (placeholders stripped) into a fresh ns.

    Registers the namespace in ``sys.modules`` under its synthetic
    ``__name__`` so Python 3.14's dataclasses ``_is_type`` resolver
    (which does ``sys.modules.get(cls.__module__).__dict__``) can
    walk back. Templates using ``@dataclass(frozen=True)`` with
    stringized annotations break otherwise.
    """
    import types

    src = _clean(path.read_text(encoding="utf-8"))
    mod_name = f"under_test_{path.stem}"
    fake_mod = types.ModuleType(mod_name)
    sys.modules[mod_name] = fake_mod
    ns = fake_mod.__dict__
    ns["__name__"] = mod_name
    exec(compile(src, str(path), "exec"), ns)  # noqa: S102 — exec is the test
    return ns


# ---------------------------------------------------------------------------
# Per-tool spec: (tool_name, template_relpath, [(write_schema_name,
# valid_kwargs, smuggled_kwarg)]).
# ---------------------------------------------------------------------------

_TOOLS: list[tuple[str, str, list[tuple[str, dict, str]]]] = [
    (
        "add_compliance_engine",
        "adapt/extend/infrastructure/add_compliance_engine/templates/compliance_schemas.py.tmpl",
        [("ErasureRequest", {}, "is_admin")],
    ),
    (
        "add_email_templates",
        "adapt/extend/infrastructure/add_email_templates/templates/schemas.py.tmpl",
        [("EmailPreviewRequest", {"template": "welcome"}, "is_admin")],
    ),
    (
        "add_file_upload",
        "adapt/extend/crud_data/add_file_upload/templates/file_schemas.py.tmpl",
        [
            (
                "PresignedUploadRequest",
                {
                    "filename": "a.png",
                    "content_type": "image/png",
                    "size_bytes": 100,
                },
                "is_admin",
            ),
            ("UploadConfirmRequest", {}, "is_admin"),
        ],
    ),
    (
        "add_ml_model_registry",
        "adapt/extend/infrastructure/add_ml_model_registry/templates/ml_model_schemas.py.tmpl",
        [
            ("MLModelCreate", {"name": "m", "version": "1"}, "is_admin"),
            ("MLModelPromote", {"version": "1"}, "is_admin"),
        ],
    ),
    (
        "add_ml_model_server",
        "adapt/extend/infrastructure/add_ml_model_server/templates/ml_schemas.py.tmpl",
        [
            (
                "PredictionRequest",
                {"input": [1.0, 2.0], "model_name": "m"},
                "is_admin",
            ),
            (
                "BatchPredictionRequest",
                {"inputs": [[1.0]], "model_name": "m"},
                "is_admin",
            ),
        ],
    ),
    (
        "add_pdf_reports",
        "adapt/extend/infrastructure/add_pdf_reports/templates/schemas.py.tmpl",
        [("ReportRequest", {"template_name": "invoice"}, "is_admin")],
    ),
    (
        "add_push_notifications_native",
        "adapt/extend/infrastructure/add_push_notifications_native/templates/schemas.py.tmpl",
        [
            (
                "DeviceTokenCreate",
                {
                    "user_id": "00000000-0000-0000-0000-000000000000",
                    "platform": "ios",
                    "token": "tok",
                },
                "is_admin",
            ),
            (
                "PushSendRequest",
                {"title": "t", "body": "b"},
                "is_admin",
            ),
        ],
    ),
    (
        "add_sms_otp",
        "adapt/extend/auth_access/add_sms_otp/templates/schemas.py.tmpl",
        [
            ("OtpSendRequest", {"phone": "+15555550100"}, "is_admin"),
            (
                "OtpVerifyRequest",
                {"phone": "+15555550100", "code": "123456"},
                "is_admin",
            ),
        ],
    ),
    (
        "add_stripe_checkout",
        "adapt/extend/infrastructure/add_stripe_checkout/templates/payment_schemas.py.tmpl",
        [
            (
                "CheckoutSessionCreate",
                {
                    "amount_cents": 1000,
                    "currency": "USD",
                    "product_name": "Widget",
                },
                "is_admin",
            )
        ],
    ),
    (
        "add_stripe_refund_flow",
        "adapt/extend/infrastructure/add_stripe_refund_flow/templates/refund_schemas.py.tmpl",
        [
            (
                "RefundRequest",
                {
                    "payment_id": "00000000-0000-0000-0000-000000000000",
                    "amount_cents": 500,
                },
                "is_admin",
            )
        ],
    ),
    (
        "add_webhook_sender",
        "adapt/extend/realtime/add_webhook_sender/templates/webhook_schemas.py.tmpl",
        [
            ("WebhookCreate", {"url": "https://example.com/wh"}, "is_admin"),
            ("WebhookUpdate", {}, "is_admin"),
        ],
    ),
]


def _flatten_ids() -> list[str]:
    out: list[str] = []
    for tool, _, specs in _TOOLS:
        for cls_name, _, _ in specs:
            out.append(f"{tool}::{cls_name}")
    return out


def _flatten_params() -> list[tuple[str, str, str, dict, str]]:
    out: list[tuple[str, str, str, dict, str]] = []
    for tool, tmpl, specs in _TOOLS:
        for cls_name, valid, smuggled in specs:
            out.append((tool, tmpl, cls_name, valid, smuggled))
    return out


# ---------------------------------------------------------------------------
# Per-write-schema assertions.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tool,tmpl_rel,cls_name,valid_kwargs,smuggled_key",
    _flatten_params(),
    ids=_flatten_ids(),
)
def test_b0_14_write_schema_carries_extra_forbid(
    tool: str,
    tmpl_rel: str,
    cls_name: str,
    valid_kwargs: dict,
    smuggled_key: str,
) -> None:
    """Each declared write schema must declare ``extra="forbid"`` AND
    reject an unknown key — the mass-assignment / key-smuggling defence
    pattern P5 exists to enforce.
    """
    from pydantic import ValidationError

    tmpl_path = SKILL_ROOT / tmpl_rel
    assert tmpl_path.exists(), f"template missing: {tmpl_rel}"
    ns = _exec_template(tmpl_path)
    cls = ns.get(cls_name)
    assert cls is not None, (
        f"{cls_name} not exported from {tmpl_rel} — the regression "
        "test asserts a schema that no longer exists."
    )
    # Some schemas reference types only present in the exec namespace
    # (AnyHttpUrl, Literal etc.) — rebuild before instantiating.
    cls.model_rebuild(_types_namespace=ns)

    # 1. Pydantic-native check: model_config['extra'] must == 'forbid'.
    extra = cls.model_config.get("extra")
    assert extra == "forbid", (
        f"{tool}::{cls_name} must declare ConfigDict(extra='forbid'); "
        f"got extra={extra!r}. Without it, mass-assignment / key smuggling "
        "(B0.14 / pattern P5) goes through silently."
    )

    # 2. Behaviour check: unknown key on a valid payload must raise.
    with pytest.raises(ValidationError):
        cls(**valid_kwargs, **{smuggled_key: "x"})


# ---------------------------------------------------------------------------
# Waiver list is empty — B0.14 covers every write schema in the catalog.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool", [t for t, _, _ in _TOOLS])
def test_b0_14_waiver_removed(tool: str) -> None:
    """All 11 entries closed in this batch PR must be gone from
    ``_WAIVED_TOOLS`` — the fix is meaningless if the rule still skips
    the template."""
    from engine.audit.contract_rules.r_write_schemas_strict import _WAIVED_TOOLS

    assert tool not in _WAIVED_TOOLS, (
        f"B0.14 waiver entry for {tool} was NOT removed; the rule will "
        "skip the template and a future regression won't be caught."
    )


def test_b0_14_no_waivers_remain() -> None:
    """After this batch ``_WAIVED_TOOLS`` should be empty — B0.14 is a
    structural rule now, not a debt list."""
    from engine.audit.contract_rules.r_write_schemas_strict import _WAIVED_TOOLS

    assert _WAIVED_TOOLS == frozenset(), (
        f"_WAIVED_TOOLS must be empty after the W2 batch PR; still "
        f"holds: {sorted(_WAIVED_TOOLS)}. Any new entry means a new "
        "B0.14 debt item — add a fix-PR, don't reopen the waiver list."
    )
