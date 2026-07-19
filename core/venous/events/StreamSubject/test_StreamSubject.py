"""Unit tests for StreamSubject — 3 per invariant."""

from __future__ import annotations

import pytest
from StreamSubject import (
    StreamSubject,
    StreamSubjectError,
    SubjectRegistry,
    validate_pattern,
    validate_subject_name,
)


# ---------------------------------------------------------------------------
# SS_INV_01 — token chars and naming rules
# ---------------------------------------------------------------------------
def test_inv_token_chars_confirms() -> None:
    s = StreamSubject("orders.created.v1")
    assert s.name == "orders.created.v1"
    assert s.matches("orders.*.v1")


def test_inv_token_chars_prevents() -> None:
    for bad in ("a..b", " leading", "x y", "a\x00b", "a*b", "a>b"):
        with pytest.raises(StreamSubjectError):
            StreamSubject(bad)
    with pytest.raises(StreamSubjectError):
        validate_subject_name("")


def test_inv_token_chars_under_failure() -> None:
    # Many mutated names, all rejected.
    for i in range(50):
        with pytest.raises(StreamSubjectError):
            StreamSubject(f"x y.{i}")  # whitespace rejected


# ---------------------------------------------------------------------------
# SS_INV_02 — greedy '>' only at end
# ---------------------------------------------------------------------------
def test_inv_greedy_terminal_confirms() -> None:
    s = StreamSubject("orders.created.v1")
    assert s.matches("orders.>")
    assert s.matches("orders.created.>")


def test_inv_greedy_terminal_prevents() -> None:
    # '>' in non-final position is rejected.
    s = StreamSubject("a.b.c")
    with pytest.raises(StreamSubjectError):
        s.matches(">.b")
    with pytest.raises(StreamSubjectError):
        validate_pattern("a.>.b")


def test_inv_greedy_terminal_under_failure() -> None:
    s = StreamSubject("a.b.c.d.e")
    # Greedy matches one or more trailing tokens.
    assert s.matches("a.>")
    assert s.matches("a.b.>")
    assert s.matches("a.b.c.d.>")


# ---------------------------------------------------------------------------
# SS_INV_03 — '*' is exactly one token
# ---------------------------------------------------------------------------
def test_inv_star_exactly_one_confirms() -> None:
    s = StreamSubject("orders.created.v1")
    assert s.matches("orders.*.v1")
    assert s.matches("*.*.*")


def test_inv_star_exactly_one_prevents() -> None:
    s = StreamSubject("a.b.c")
    # * matches exactly one token — too few tokens is no match.
    assert not s.matches("*")
    assert not s.matches("*.*")


def test_inv_star_exactly_one_under_failure() -> None:
    s = StreamSubject("a.b.c.d")
    # * never matches across multiple tokens.
    assert not s.matches("a.*")
    assert not s.matches("a.*.c")
    assert s.matches("a.*.c.d")


# ---------------------------------------------------------------------------
# SS_INV_04 — '$' prefix forbidden for user subjects
# ---------------------------------------------------------------------------
def test_inv_system_prefix_confirms() -> None:
    # Non-dollar names always succeed.
    StreamSubject("orders.created")


def test_inv_system_prefix_prevents() -> None:
    for bad in ("$SYS.x", "$admin.hot", "$.nope"):
        with pytest.raises(StreamSubjectError):
            StreamSubject(bad)


def test_inv_system_prefix_under_failure() -> None:
    # Mid-string '$' is allowed; only a LEADING '$' is rejected.
    s = StreamSubject("a$.b")
    assert s.name == "a$.b"


# ---------------------------------------------------------------------------
# SS_INV_05 — no wildcards in publishable subject
# ---------------------------------------------------------------------------
def test_inv_no_wildcard_publish_confirms() -> None:
    # Regular publishable subject accepted.
    s = StreamSubject("orders.v1")
    reg = SubjectRegistry()
    reg.subscribe("orders.>", "c1")
    assert reg.publish(s) == 1


def test_inv_no_wildcard_publish_prevents() -> None:
    for bad in ("*", ">", "a.*", "a.>", "a.b.>"):
        with pytest.raises(StreamSubjectError):
            StreamSubject(bad)


def test_inv_no_wildcard_publish_under_failure() -> None:
    # Under load, every wildcard publish attempt is rejected.
    for i in range(25):
        with pytest.raises(StreamSubjectError):
            StreamSubject(f"a.b.*{i}")  # invalid: * not at token boundary
