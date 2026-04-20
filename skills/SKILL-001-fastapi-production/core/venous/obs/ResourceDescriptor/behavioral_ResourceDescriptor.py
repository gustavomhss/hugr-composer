"""Behavioral scenarios for ResourceDescriptor."""

from __future__ import annotations

import pytest

from ResourceDescriptor import ResourceDescriptor, ResourceInvariantError


def _make(**o: object) -> ResourceDescriptor:
    base = dict(service_name="checkout", service_namespace="payments",
                service_version="1.0.0", service_instance_id="i-1",
                deployment_environment="production", attributes={})
    base.update(o)
    return ResourceDescriptor(**base)  # type: ignore[arg-type]


def test_scenario_build_production() -> None:
    d = _make()
    a = d.to_attributes()
    assert a["service.name"] == "checkout"
    assert a["deployment.environment.name"] == "production"


def test_scenario_merge_cloud_attributes() -> None:
    d = _make(attributes={"cloud.provider": "aws"})
    d2 = d.merged_with({"cloud.region": "us-east-1"})
    assert d2.attributes["cloud.region"] == "us-east-1"
    assert "cloud.region" not in d.attributes


def test_scenario_missing_service_name_fails_fast() -> None:
    with pytest.raises(ResourceInvariantError):
        _make(service_name="")


def test_scenario_environment_typo_rejected() -> None:
    with pytest.raises(ResourceInvariantError):
        _make(deployment_environment="prod")


def test_scenario_secret_attribute_rejected() -> None:
    with pytest.raises(ResourceInvariantError):
        _make(attributes={"api_key": "sk-abc"})


def test_scenario_canonical_keys_emitted() -> None:
    d = _make()
    keys = d.to_attributes().keys()
    assert "service.name" in keys
    assert "deployment.environment.name" in keys
