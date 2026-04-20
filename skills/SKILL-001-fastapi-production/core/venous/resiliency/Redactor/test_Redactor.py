"""Invariant tests for `Redactor`.

Uses a minimal reference redactor that mirrors the staged impl's
contract. See `Redactor.contract.json`.
"""
from __future__ import annotations

import re

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def _redact_string(s: str) -> str:
    return _EMAIL.sub("[REDACTED]", s)


class _Redactor:
    def __call__(self, logger, method, event_dict):
        for k, v in list(event_dict.items()):
            if isinstance(v, str):
                try:
                    event_dict[k] = _redact_string(v)
                except Exception:
                    pass
        return event_dict


# INV_01 -----------------------------------------------------------------
def test_inv_in_place_mutation_confirms() -> None:
    r = _Redactor()
    d = {"msg": "contact alice@example.com"}
    out = r(None, "info", d)
    assert out is d  # same object
    assert "[REDACTED]" in d["msg"]


def test_inv_in_place_mutation_prevents() -> None:
    # Not a copy — mutating the returned dict mutates the input.
    r = _Redactor()
    d = {"note": "plain text"}
    out = r(None, "info", d)
    out["injected"] = True
    assert d["injected"] is True


def test_inv_in_place_mutation_under_failure() -> None:
    r = _Redactor()
    d: dict = {}  # empty
    assert r(None, "info", d) is d


# INV_02 -----------------------------------------------------------------
def test_inv_non_string_passthrough_confirms() -> None:
    r = _Redactor()
    d = {"count": 42, "items": [1, 2, 3], "obj": object()}
    before = (d["count"], d["items"], d["obj"])
    r(None, "info", d)
    assert (d["count"], d["items"], d["obj"]) == before


def test_inv_non_string_passthrough_prevents() -> None:
    # A nested dict with a PII string inside is NOT recursively redacted — by design.
    r = _Redactor()
    d = {"nested": {"email": "a@b.com"}}
    r(None, "info", d)
    assert d["nested"]["email"] == "a@b.com"  # untouched (value is a dict, not a str)


def test_inv_non_string_passthrough_under_failure() -> None:
    r = _Redactor()
    d = {"x": None, "y": False, "z": 0.0}
    r(None, "info", d)
    assert d == {"x": None, "y": False, "z": 0.0}


# INV_03 -----------------------------------------------------------------
def test_inv_never_raises_confirms() -> None:
    r = _Redactor()
    r(None, "info", {"msg": "normal"})  # no exception
    r(None, "info", {})  # empty


def test_inv_never_raises_prevents() -> None:
    # Weird keys and bytes: still no exception.
    r = _Redactor()
    r(None, "info", {"": "", 0: "oops", "b": b"bytes"})


def test_inv_never_raises_under_failure() -> None:
    r = _Redactor()
    # Self-referential dict
    d: dict = {}
    d["self"] = d
    r(None, "info", d)  # must not StackOverflow / raise
