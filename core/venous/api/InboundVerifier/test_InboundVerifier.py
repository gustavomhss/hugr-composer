"""Unit tests for InboundVerifier (IV_INV_01..03)."""
from __future__ import annotations

import pytest

from InboundVerifier import InboundVerifier, VerifiedEvent


# ---------------------------------------------------------------------------
# IV_INV_01 — named contract (subclass MUST set name)
# ---------------------------------------------------------------------------
def test_inv_verify_confirms() -> None:
    """A concrete subclass with `name` + `verify` works as expected."""

    class FakeVerifier(InboundVerifier):
        name = "fake"

        def verify(self, body: bytes, headers: dict[str, str]) -> VerifiedEvent:
            return {"event": "ok", "body": body.decode()}

    v = FakeVerifier()
    assert v.name == "fake"
    out = v.verify(b"{}", {"x-sig": "abc"})
    assert out == {"event": "ok", "body": "{}"}


def test_subclass_without_name_rejected_at_definition() -> None:
    """IV_INV_01: a subclass that forgets `name` fails at class creation."""
    with pytest.raises(TypeError, match="name"):
        class BadVerifier(InboundVerifier):  # type: ignore[misc] # intentional
            # no `name =` here
            def verify(self, body: bytes, headers: dict[str, str]) -> VerifiedEvent:
                return {}


def test_subclass_with_empty_name_rejected() -> None:
    """IV_INV_01: empty-string name is not enough."""
    with pytest.raises(TypeError, match="name"):
        class EmptyName(InboundVerifier):
            name = ""

            def verify(self, body: bytes, headers: dict[str, str]) -> VerifiedEvent:
                return {}


# ---------------------------------------------------------------------------
# IV_INV_02 — verify-or-raise (abstract enforced by ABC)
# ---------------------------------------------------------------------------
def test_inv_verify_prevents() -> None:
    """Cannot instantiate base or subclasses that don't implement verify."""
    with pytest.raises(TypeError, match="abstract"):
        InboundVerifier()  # type: ignore[abstract]

    class Partial(InboundVerifier):
        name = "partial"
        # Intentionally does NOT implement verify.

    with pytest.raises(TypeError, match="abstract"):
        Partial()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# IV_INV_03 — framework-free (no fastapi/starlette imports)
# ---------------------------------------------------------------------------
def test_inv_verify_under_failure() -> None:
    """The base module MUST NOT import FastAPI or Starlette.

    A subclass that raises a custom exception propagates unchanged —
    the base does nothing to translate it.
    """
    import InboundVerifier as module
    source = open(module.__file__).read()
    for banned in ("from fastapi ", "from starlette ", "import fastapi", "import starlette"):
        assert banned not in source, (
            f"InboundVerifier.py must stay framework-free; found {banned!r}"
        )

    class StrictVerifier(InboundVerifier):
        name = "strict"

        def verify(self, body: bytes, headers: dict[str, str]) -> VerifiedEvent:
            if b"bad" in body:
                raise ValueError("signature mismatch")
            return {"ok": True}

    v = StrictVerifier()
    assert v.verify(b"good", {}) == {"ok": True}
    with pytest.raises(ValueError, match="signature mismatch"):
        v.verify(b"bad-sig", {})
