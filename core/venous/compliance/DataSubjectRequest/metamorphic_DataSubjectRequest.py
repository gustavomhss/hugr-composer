"""Metamorphic tests for DataSubjectRequest."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from DataSubjectRequest import STATUTORY_WINDOW, InMemoryDataSubjectRequest


UTC = timezone.utc


def test_metamorphic_due_at_is_pure() -> None:
    d = InMemoryDataSubjectRequest()
    t = datetime(2026, 1, 1, tzinfo=UTC)
    rid = d.open("s", "access", t)
    assert d.due_at(rid) == t + STATUTORY_WINDOW


def test_metamorphic_two_requests_independent() -> None:
    d = InMemoryDataSubjectRequest(required_stores={"users"})
    r1 = d.open("s-1", "access", datetime(2026, 1, 1, tzinfo=UTC))
    r2 = d.open("s-2", "access", datetime(2026, 2, 1, tzinfo=UTC))
    d.attach_artifact(r1, "users", b"users-manifest-metamorphic")
    d.close(r1, outcome="completed")
    # r2 remains open; size counts both.
    assert d.size == 2


def test_metamorphic_attach_after_close_rejected() -> None:
    import pytest

    from DataSubjectRequest import DataSubjectRequestError

    d = InMemoryDataSubjectRequest()
    rid = d.open("s", "access", datetime(2026, 1, 1, tzinfo=UTC))
    d.close(rid, outcome="completed")
    with pytest.raises(DataSubjectRequestError):
        d.attach_artifact(rid, "x", b"late")


def test_metamorphic_double_close_rejected() -> None:
    import pytest

    from DataSubjectRequest import DataSubjectRequestError

    d = InMemoryDataSubjectRequest()
    rid = d.open("s", "access", datetime(2026, 1, 1, tzinfo=UTC))
    d.close(rid, outcome="completed")
    with pytest.raises(DataSubjectRequestError):
        d.close(rid, outcome="completed")


def test_differential_erasure_vs_access_close() -> None:
    import pytest

    from DataSubjectRequest import DataSubjectRequestError

    d = InMemoryDataSubjectRequest()
    r_acc = d.open("s", "access", datetime(2026, 1, 1, tzinfo=UTC))
    r_er = d.open("s", "erasure", datetime(2026, 1, 1, tzinfo=UTC))
    # Access closes without artifacts; erasure does not.
    d.close(r_acc, outcome="completed")
    with pytest.raises(DataSubjectRequestError):
        d.close(r_er, outcome="completed")
