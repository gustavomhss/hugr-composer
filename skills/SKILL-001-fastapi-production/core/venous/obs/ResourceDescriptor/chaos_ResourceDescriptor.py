"""Chaos tests for ResourceDescriptor."""

from __future__ import annotations

import pytest

from ResourceDescriptor import ResourceDescriptor, ResourceInvariantError


def _make(**o: object) -> ResourceDescriptor:
    base = dict(service_name="a", service_namespace=None, service_version="1",
                service_instance_id="i", deployment_environment="production", attributes={})
    base.update(o)
    return ResourceDescriptor(**base)  # type: ignore[arg-type]


def test_chaos_secret_substring_in_attribute_rejected() -> None:
    for bad in ("password=x", "api_key=1", "bearer_token=t"):
        with pytest.raises(ResourceInvariantError):
            _make(attributes={"k": bad})


def test_chaos_invalid_env_values() -> None:
    for env in ("PROD", "Production", "prod ", "", "qa"):
        with pytest.raises(ResourceInvariantError):
            _make(deployment_environment=env)


def test_chaos_merge_with_secret_rejected() -> None:
    d = _make()
    with pytest.raises(ResourceInvariantError):
        d.merged_with({"authorization": "Bearer abc"})


def test_chaos_empty_instance_id_rejected() -> None:
    with pytest.raises(ResourceInvariantError):
        _make(service_instance_id="")


def test_chaos_immutable_after_merge() -> None:
    d = _make(attributes={"a": "1"})
    d.merged_with({"b": "2"})
    assert "b" not in d.attributes


def test_chaos_bulk_merges_stable() -> None:
    d = _make()
    current = d
    for i in range(100):
        current = current.merged_with({f"k{i}": f"v{i}"})
    assert len(current.attributes) == 100
