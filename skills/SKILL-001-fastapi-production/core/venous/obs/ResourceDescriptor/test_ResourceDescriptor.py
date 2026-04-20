"""Unit tests for ResourceDescriptor."""

from __future__ import annotations

import pytest

from ResourceDescriptor import ALLOWED_ENVIRONMENTS, ResourceDescriptor, ResourceInvariantError


def _make(**overrides: object) -> ResourceDescriptor:
    defaults: dict[str, object] = {
        "service_name": "checkout",
        "service_namespace": "payments",
        "service_version": "2026.04.3",
        "service_instance_id": "pod-abc-123",
        "deployment_environment": "production",
        "attributes": {},
    }
    defaults.update(overrides)
    return ResourceDescriptor(**defaults)  # type: ignore[arg-type]


# RD_INV_01 — service.name required
def test_inv_service_name_required_confirms() -> None:
    d = _make(service_name="ok")
    assert d.service_name == "ok"


def test_inv_service_name_required_prevents() -> None:
    with pytest.raises(ResourceInvariantError):
        _make(service_name="")


def test_inv_service_name_required_under_failure() -> None:
    for bad in ("", None):
        with pytest.raises((ResourceInvariantError, TypeError)):
            _make(service_name=bad)  # type: ignore[arg-type]


# RD_INV_02 — instance id stable + non-empty
def test_inv_instance_id_stable_confirms() -> None:
    d = _make(service_instance_id="unique-1")
    assert d.service_instance_id == "unique-1"


def test_inv_instance_id_stable_prevents() -> None:
    with pytest.raises(ResourceInvariantError):
        _make(service_instance_id="")


def test_inv_instance_id_stable_under_failure() -> None:
    d = _make(service_instance_id="i-1")
    # Since frozen, attribute cannot be rebound.
    with pytest.raises((TypeError, AttributeError)):
        d.service_instance_id = "i-2"  # type: ignore[misc]


# RD_INV_03 — env enum
def test_inv_env_enum_confirms() -> None:
    for env in ALLOWED_ENVIRONMENTS:
        _make(deployment_environment=env)


def test_inv_env_enum_prevents() -> None:
    for bad in ("prod", "qa", "custom", "Development", ""):
        with pytest.raises(ResourceInvariantError):
            _make(deployment_environment=bad)


def test_inv_env_enum_under_failure() -> None:
    # Case must match exactly.
    with pytest.raises(ResourceInvariantError):
        _make(deployment_environment="Production")


# RD_INV_04 — immutable
def test_inv_immutable_confirms() -> None:
    d = _make()
    d2 = d.merged_with({"region": "us-east-1"})
    assert d2 is not d
    assert "region" not in d.attributes


def test_inv_immutable_prevents() -> None:
    d = _make(attributes={"a": "1"})
    # The returned attributes mapping on fresh is a copy.
    d.attributes["injected"] = "x"  # type: ignore[index]
    d2 = _make(service_name="other")
    assert "injected" not in d2.attributes


def test_inv_immutable_under_failure() -> None:
    d = _make(attributes={"cloud.provider": "aws"})
    d2 = d.merged_with({"cloud.region": "us-east-1"})
    d3 = d2.merged_with({"cloud.zone": "us-east-1a"})
    assert "cloud.zone" not in d.attributes
    assert "cloud.zone" not in d2.attributes
    assert d3.attributes["cloud.zone"] == "us-east-1a"


# RD_INV_05 — canonical SemConv keys
def test_inv_canonical_keys_confirms() -> None:
    d = _make()
    a = d.to_attributes()
    for required in ("service.name", "service.version", "service.instance.id",
                     "deployment.environment.name"):
        assert required in a


def test_inv_canonical_keys_prevents() -> None:
    d = _make()
    a = d.to_attributes()
    for wrong in ("serviceName", "service_name", "Service.Name"):
        assert wrong not in a


def test_inv_canonical_keys_under_failure() -> None:
    d = _make(service_namespace=None)
    a = d.to_attributes()
    # Namespace omitted → key absent rather than empty.
    assert "service.namespace" not in a


# RD_INV_06 — no secrets
def test_inv_no_secrets_confirms() -> None:
    _make(attributes={"cloud.provider": "aws"})


def test_inv_no_secrets_prevents() -> None:
    with pytest.raises(ResourceInvariantError):
        _make(attributes={"password": "hunter2"})
    with pytest.raises(ResourceInvariantError):
        _make(attributes={"api_key": "sk-abc"})


def test_inv_no_secrets_under_failure() -> None:
    d = _make()
    with pytest.raises(ResourceInvariantError):
        d.merged_with({"bearer_token": "abc123"})
