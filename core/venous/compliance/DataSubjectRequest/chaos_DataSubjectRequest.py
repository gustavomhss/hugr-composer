"""Chaos tests for DataSubjectRequest."""

from __future__ import annotations

import threading
from datetime import datetime, timezone

import pytest

from DataSubjectRequest import DataSubjectRequestError, InMemoryDataSubjectRequest


UTC = timezone.utc
T = datetime(2026, 1, 1, tzinfo=UTC)


def test_chaos_concurrent_opens_counted() -> None:
    d = InMemoryDataSubjectRequest()

    def worker(i: int) -> None:
        d.open(f"s-{i}", "access", T)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(30)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert d.size == 30


def test_chaos_invalid_kind_rejected() -> None:
    d = InMemoryDataSubjectRequest()
    for bad in ("ACCESS", "copy", "", "erasure "):
        with pytest.raises(DataSubjectRequestError):
            d.open("s", bad, T)  # type: ignore[arg-type]


def test_chaos_naive_received_at_rejected() -> None:
    d = InMemoryDataSubjectRequest()
    with pytest.raises(DataSubjectRequestError):
        d.open("s", "access", datetime(2026, 1, 1))


def test_chaos_manifest_bytes_required() -> None:
    d = InMemoryDataSubjectRequest()
    rid = d.open("s", "access", T)
    with pytest.raises(DataSubjectRequestError):
        d.attach_artifact(rid, "users", "not-bytes")  # type: ignore[arg-type]


def test_chaos_unknown_request_id_everywhere() -> None:
    d = InMemoryDataSubjectRequest()
    with pytest.raises(DataSubjectRequestError):
        d.attach_artifact("nope", "s", b"")
    with pytest.raises(DataSubjectRequestError):
        d.close("nope", outcome="completed")
    with pytest.raises(DataSubjectRequestError):
        d.due_at("nope")
