"""Behavioral scenarios for DataSubjectRequest."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from DataSubjectRequest import DataSubjectRequestError, InMemoryDataSubjectRequest


UTC = timezone.utc
T = datetime(2026, 1, 1, tzinfo=UTC)


def test_scenario_full_rtbf() -> None:
    d = InMemoryDataSubjectRequest(required_stores={"users", "events", "backups", "cascade"})
    rid = d.open("subject-42", "erasure", T)
    for s in ("users", "events", "backups", "cascade"):
        d.attach_artifact(rid, s, b"erasure-proof-manifest")
    d.close(rid, outcome="completed")


def test_scenario_access_request() -> None:
    d = InMemoryDataSubjectRequest(required_stores={"users"})
    rid = d.open("s", "access", T)
    d.attach_artifact(rid, "users", b"export-manifest")
    d.close(rid, outcome="completed")


def test_scenario_due_at_unpausable() -> None:
    from datetime import timedelta
    d = InMemoryDataSubjectRequest()
    rid = d.open("s", "access", T)
    # Due 30 days from received_at regardless of later internal steps.
    assert d.due_at(rid) == T + timedelta(days=30)


def test_scenario_cannot_close_missing_cascade() -> None:
    d = InMemoryDataSubjectRequest()
    rid = d.open("s", "erasure", T)
    with pytest.raises(DataSubjectRequestError):
        d.close(rid, outcome="completed")


def test_scenario_portability_export_url_time_bound() -> None:
    d = InMemoryDataSubjectRequest(
        export_signing_key=b"behavioral-export-key-32bytes-ok",
    )
    rid = d.open("s", "portability", T)
    url = d.signed_export_url(rid, T)
    assert "expires=" in url and "sig=" in url
