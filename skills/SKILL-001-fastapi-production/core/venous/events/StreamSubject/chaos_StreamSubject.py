"""Chaos / fault injection for StreamSubject."""

from __future__ import annotations

import threading

import pytest

from StreamSubject import StreamSubject, StreamSubjectError, SubjectRegistry


def test_chaos_null_byte_rejected() -> None:
    with pytest.raises(StreamSubjectError):
        StreamSubject("a.\x00.b")


def test_chaos_whitespace_rejected() -> None:
    with pytest.raises(StreamSubjectError):
        StreamSubject("a. b")
    with pytest.raises(StreamSubjectError):
        StreamSubject("a.b ")


def test_chaos_empty_token_rejected() -> None:
    with pytest.raises(StreamSubjectError):
        StreamSubject("a..b")


def test_chaos_system_prefix_rejected() -> None:
    with pytest.raises(StreamSubjectError):
        StreamSubject("$system")


def test_chaos_concurrent_registry_updates() -> None:
    reg = SubjectRegistry()
    def subscribe_many(tid: int) -> None:
        for i in range(100):
            reg.subscribe(f"t{tid}.a.>", f"c-{tid}-{i}")
    threads = [threading.Thread(target=subscribe_many, args=(t,)) for t in range(4)]
    for t in threads: t.start()
    for t in threads: t.join()
    # Four tenant patterns should each have 100 subscribers; every publish
    # matches exactly one tenant's pattern.
    for tid in range(4):
        count = reg.publish(StreamSubject(f"t{tid}.a.b"))
        assert count == 100


def test_chaos_deep_subject_name_hops() -> None:
    # 50 dot-separated tokens — matcher still works.
    s = StreamSubject(".".join(f"t{i}" for i in range(50)))
    assert s.matches("t0.>")
    assert s.matches("t0.t1.t2.>")


def test_chaos_greedy_mid_pattern_raises() -> None:
    s = StreamSubject("a.b.c")
    with pytest.raises(StreamSubjectError):
        s.matches("a.>.c")
