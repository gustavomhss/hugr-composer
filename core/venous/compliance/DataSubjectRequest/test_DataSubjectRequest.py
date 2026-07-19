"""Unit tests for DataSubjectRequest — 3 per invariant."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from DataSubjectRequest import (
    STATUTORY_WINDOW,
    DataSubjectRequestError,
    InMemoryDataSubjectRequest,
)

UTC = UTC
T0 = datetime(2026, 1, 1, tzinfo=UTC)


class _Sink:
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

    def append(self, actor: str, action: str, resource: str, outcome: str,
               attributes: object) -> str:
        self.rows.append({"action": action, "resource": resource,
                          "outcome": outcome, "attrs": dict(attributes)})  # type: ignore[arg-type]
        return "h"


# DSR_INV_01 — due_at computed from received_at.
def test_inv_due_at_statutory_confirms() -> None:
    d = InMemoryDataSubjectRequest()
    rid = d.open("alice", "access", T0)
    assert d.due_at(rid) == T0 + STATUTORY_WINDOW


def test_inv_due_at_statutory_prevents() -> None:
    d = InMemoryDataSubjectRequest()
    with pytest.raises(DataSubjectRequestError):
        d.open("", "access", T0)
    with pytest.raises(DataSubjectRequestError):
        d.open("alice", "nope", T0)  # type: ignore[arg-type]
    with pytest.raises(DataSubjectRequestError):
        d.open("alice", "access", datetime(2026, 1, 1))


def test_inv_due_at_statutory_under_failure() -> None:
    d = InMemoryDataSubjectRequest()
    with pytest.raises(DataSubjectRequestError):
        d.due_at("unknown-id")


# DSR_INV_02 — every required store MUST attach.
def test_inv_store_artifacts_confirms() -> None:
    d = InMemoryDataSubjectRequest(required_stores={"users", "events"})
    rid = d.open("s", "access", T0)
    d.attach_artifact(rid, "users", b"users-manifest-v1")
    d.attach_artifact(rid, "events", b"events-manifest-v1")
    d.close(rid, outcome="completed")


def test_inv_store_artifacts_prevents() -> None:
    d = InMemoryDataSubjectRequest(required_stores={"users", "events"})
    rid = d.open("s", "access", T0)
    d.attach_artifact(rid, "users", b"users-manifest-v1")
    with pytest.raises(DataSubjectRequestError):
        d.close(rid, outcome="completed")  # missing 'events'


def test_inv_store_artifacts_under_failure() -> None:
    d = InMemoryDataSubjectRequest()
    rid = d.open("s", "access", T0)
    d.close(rid, outcome="completed")
    with pytest.raises(DataSubjectRequestError):
        d.attach_artifact(rid, "late", b"x-manifest-post-close")


# DSR_INV_03 — erasure requires cascade artifact.
def test_inv_erasure_cascade_confirms() -> None:
    d = InMemoryDataSubjectRequest()
    rid = d.open("s", "erasure", T0)
    d.attach_artifact(rid, "cascade", b"cascade-erasure-manifest-proof")
    d.close(rid, outcome="completed")


def test_inv_erasure_cascade_prevents() -> None:
    d = InMemoryDataSubjectRequest()
    rid = d.open("s", "erasure", T0)
    with pytest.raises(DataSubjectRequestError):
        d.close(rid, outcome="completed")  # no cascade


def test_inv_erasure_cascade_under_failure() -> None:
    d = InMemoryDataSubjectRequest()
    rid = d.open("s", "erasure", T0)
    d.attach_artifact(rid, "users", b"only-users-manifest-proof")
    with pytest.raises(DataSubjectRequestError):
        d.close(rid, outcome="completed")


# DSR_INV_04 — every action emits an audit entry.
def test_inv_audit_on_action_confirms() -> None:
    sink = _Sink()
    d = InMemoryDataSubjectRequest(audit_sink=sink)
    rid = d.open("s", "access", T0)
    d.attach_artifact(rid, "users", b"users-manifest-for-audit")
    d.close(rid, outcome="completed")
    actions = [r["action"] for r in sink.rows]
    assert actions == ["dsr.open", "dsr.attach_artifact", "dsr.close"]


def test_inv_audit_on_action_prevents() -> None:
    # No audit sink → no emissions; behavior still correct.
    d = InMemoryDataSubjectRequest()
    rid = d.open("s", "access", T0)
    d.close(rid, outcome="completed")
    assert d.size == 1


def test_inv_audit_on_action_under_failure() -> None:
    # Empty outcome at close is refused — no audit emitted for broken action.
    sink = _Sink()
    d = InMemoryDataSubjectRequest(audit_sink=sink)
    rid = d.open("s", "access", T0)
    with pytest.raises(DataSubjectRequestError):
        d.close(rid, outcome="")
    # Only the open emitted.
    assert [r["action"] for r in sink.rows] == ["dsr.open"]


# DSR_INV_05 — export delivery via time-bound signed URL.
_EXPORT_KEY = b"test-export-signing-key-32bytes-!"


def test_inv_signed_export_confirms() -> None:
    d = InMemoryDataSubjectRequest(export_signing_key=_EXPORT_KEY)
    rid = d.open("s", "access", T0)
    url = d.signed_export_url(rid, T0 + timedelta(hours=1))
    assert url.startswith("https://") and "expires=" in url and "sig=" in url
    # Signature round-trips via verify.
    expires_str = url.split("expires=")[1].split("&")[0]
    sig = url.split("sig=")[1]
    assert d.verify_export_url_signature(rid, int(expires_str), sig)
    # Tampering with expires breaks the signature.
    assert not d.verify_export_url_signature(rid, int(expires_str) + 1, sig)


def test_inv_signed_export_prevents() -> None:
    d = InMemoryDataSubjectRequest(export_signing_key=_EXPORT_KEY)
    rid = d.open("s", "erasure", T0)  # wrong kind
    with pytest.raises(DataSubjectRequestError):
        d.signed_export_url(rid, T0)


def test_inv_signed_export_under_failure() -> None:
    d = InMemoryDataSubjectRequest(export_signing_key=_EXPORT_KEY)
    with pytest.raises(DataSubjectRequestError):
        d.signed_export_url("nope", T0)
