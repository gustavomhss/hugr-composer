"""Metamorphic + differential for ResourceDescriptor."""

from __future__ import annotations

from ResourceDescriptor import ResourceDescriptor


def _make(**o: object) -> ResourceDescriptor:
    base = dict(service_name="a", service_namespace=None, service_version="1",
                service_instance_id="i-1", deployment_environment="production", attributes={})
    base.update(o)
    return ResourceDescriptor(**base)  # type: ignore[arg-type]


def test_metamorphic_merge_associative() -> None:
    d = _make()
    d1 = d.merged_with({"a": "1"}).merged_with({"b": "2"})
    d2 = d.merged_with({"b": "2"}).merged_with({"a": "1"})
    assert d1.attributes == d2.attributes


def test_metamorphic_merge_none_is_noop() -> None:
    d = _make(attributes={"a": "1"})
    d2 = d.merged_with({})
    assert d2.attributes == d.attributes


def test_metamorphic_to_attributes_stable() -> None:
    d = _make()
    first = d.to_attributes()
    for _ in range(5):
        assert d.to_attributes() == first


def test_metamorphic_merge_overrides_last_wins() -> None:
    d = _make(attributes={"k": "v1"})
    d2 = d.merged_with({"k": "v2"})
    assert d2.attributes["k"] == "v2"


def test_metamorphic_different_instances_distinct() -> None:
    a = _make(service_instance_id="i-1")
    b = _make(service_instance_id="i-2")
    assert a.service_instance_id != b.service_instance_id


def test_differential_namespace_presence() -> None:
    with_ns = _make(service_namespace="payments")
    without = _make(service_namespace=None)
    assert "service.namespace" in with_ns.to_attributes()
    assert "service.namespace" not in without.to_attributes()
