"""Regression test for R6-O3-P5 — OnboardingRequest.admin_email validation.

Round-6 Opus-3 finding P5: ``OnboardingRequest`` in
``add_tenant_onboarding/templates/onboarding_schemas.py.tmpl`` imports
``EmailStr`` but declares ``admin_email: str``. The initial admin user
is high-privilege (root tenant identity), so an unvalidated email is a
spam / SSRF / header-injection vector in the welcome-mail path that the
tool wires up downstream (``SendWelcomeEmailStep``).

This test parses the template, materializes the ``OnboardingRequest``
class in an isolated namespace, and asserts:

  * **Valid input** — a well-formed email passes.
  * **Invalid input** — four injection-shaped payloads raise
    ``ValidationError``:
        - ``"<script>"`` — HTML/JS injection probe.
        - ``""`` — empty string (Pydantic v2 bare-str accepts this).
        - ``"not-an-email"`` — missing ``@``, plainly invalid.
        - 10 MB string — buffer-pressure probe; bare-str accepts it
          silently and ships it to the SMTP path.

Pre-fix the test FAILS — bare ``str`` accepts every probe above. After
``admin_email: EmailStr`` the test passes (Pydantic + ``email-validator``
reject all four).

Run::

    PYTHONPATH=. .venv/bin/pytest engine/tests/test_r6_o3_p5_onboarding_emailstr.py -v
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent.parent
sys.path.insert(0, str(SKILL_ROOT))

TEMPLATE = (
    SKILL_ROOT
    / "adapt"
    / "extend"
    / "infrastructure"
    / "add_tenant_onboarding"
    / "templates"
    / "onboarding_schemas.py.tmpl"
)


# ---------------------------------------------------------------------------
# Template loader — substitute ``${name}`` / ``$name`` placeholders so the
# template parses as a valid Python module, then exec it into an isolated
# namespace. Same approach as the B0.14 rule's _clean_placeholders.
# ---------------------------------------------------------------------------

_PLACEHOLDER_BRACED_RE = re.compile(r"\$\{[^}]+\}")
_PLACEHOLDER_BARE_RE = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*")


def _materialize_onboarding_request() -> type:
    """Exec the template and return the live ``OnboardingRequest`` class."""
    src = TEMPLATE.read_text(encoding="utf-8")
    src = _PLACEHOLDER_BRACED_RE.sub("PLACEHOLDER", src)
    src = _PLACEHOLDER_BARE_RE.sub("PLACEHOLDER", src)

    ns: dict = {"__name__": "onboarding_schemas_under_test"}
    exec(compile(src, str(TEMPLATE), "exec"), ns)  # noqa: S102 — template exec is the test
    cls = ns.get("OnboardingRequest")
    assert cls is not None, "OnboardingRequest not defined in template"
    # ``from __future__ import annotations`` makes every field annotation a
    # forward-ref. Pydantic can't resolve ``EmailStr`` from the exec ns, so
    # we rebuild the model with explicit types in scope. (Pre-fix the
    # annotation is bare ``str`` and rebuild is a no-op — keeps the test
    # one-shot regardless of fix state.)
    try:
        cls.model_rebuild(_types_namespace=ns)
    except Exception:  # noqa: BLE001 — rebuild may be unnecessary pre-fix
        pass
    return cls


# ---------------------------------------------------------------------------
# Test cases.
# ---------------------------------------------------------------------------


def test_valid_email_accepted() -> None:
    """Sanity: a well-formed email passes regardless of bug status."""
    OnboardingRequest = _materialize_onboarding_request()
    req = OnboardingRequest(tenant_name="Acme", admin_email="admin@example.com")
    assert req.tenant_name == "Acme"
    assert str(req.admin_email) == "admin@example.com"


_INVALID_PAYLOADS = [
    ("html_injection_probe", "<script>alert(1)</script>"),
    ("empty_string", ""),
    ("missing_at_sign", "not-an-email"),
    ("ten_megabyte_string", "a" * 10_000_000),
]


@pytest.mark.parametrize(
    ("label", "payload"),
    _INVALID_PAYLOADS,
    ids=[label for label, _ in _INVALID_PAYLOADS],
)
def test_invalid_email_rejected(label: str, payload: str) -> None:
    """R6-O3-P5: every injection-shaped admin_email must raise ValidationError.

    Pre-fix (bare ``str``) ALL four are accepted — the test fails on the
    first parametrize case. Post-fix (``EmailStr``) all four are rejected
    by ``email-validator``.
    """
    OnboardingRequest = _materialize_onboarding_request()
    with pytest.raises(ValidationError):
        OnboardingRequest(tenant_name="Acme", admin_email=payload)
