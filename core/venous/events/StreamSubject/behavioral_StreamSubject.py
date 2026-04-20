"""Behavioral scenarios for StreamSubject."""

from __future__ import annotations

import pytest

from StreamSubject import StreamSubject, StreamSubjectError, SubjectRegistry


def test_scenario_fanout_routes_to_matching_patterns() -> None:
    reg = SubjectRegistry()
    reg.subscribe("orders.>", "fulfillment")
    reg.subscribe("orders.*.v1", "analytics")
    reg.subscribe("payments.>", "risk")
    # Publication matches first two subscribers, not the third.
    s = StreamSubject("orders.created.v1")
    matched = reg.publish(s)
    assert matched == 2


def test_scenario_unsubscribe_removes_routing() -> None:
    reg = SubjectRegistry()
    reg.subscribe("a.>", "c1")
    s = StreamSubject("a.b.c")
    assert reg.publish(s) == 1
    reg.unsubscribe("a.>", "c1")
    assert reg.publish(s) == 0


def test_scenario_multi_tenant_isolation() -> None:
    # Patterns namespaced by tenant prefix prevent cross-tenant delivery.
    reg = SubjectRegistry()
    reg.subscribe("tenant-a.>", "ingress-a")
    reg.subscribe("tenant-b.>", "ingress-b")
    s = StreamSubject("tenant-a.orders.v1")
    matched = reg.publish(s)
    assert matched == 1  # only ingress-a


def test_scenario_publishable_subject_rejects_wildcards() -> None:
    with pytest.raises(StreamSubjectError):
        StreamSubject("orders.*")


def test_scenario_greedy_wildcard_matches_deep_subjects() -> None:
    s = StreamSubject("a.b.c.d.e.f")
    assert s.matches("a.>")
    assert not s.matches("x.>")


def test_scenario_registry_tracks_deliveries() -> None:
    reg = SubjectRegistry()
    reg.subscribe("a.>", "c1")
    reg.publish(StreamSubject("a.b"))
    reg.publish(StreamSubject("a.c"))
    # Two deliveries recorded for the single subscription.
    assert len(reg.deliveries()) == 2
