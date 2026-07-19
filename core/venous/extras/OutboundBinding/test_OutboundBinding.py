"""Unit tests for OutboundBinding — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

import pytest
from OutboundBinding import (
    BindingComponent,
    BindingDeadlineExceededError,
    BindingInvocation,
    InMemoryOutboundBinding,
    OutboundBindingError,
    validate_invocation,
    validate_metadata_secrets,
)


async def _echo_exec(req: BindingInvocation) -> tuple[bytes, Mapping[str, str]]:
    return req.data, {"echo": "true"}


def _registry(name: str = "sendgrid", ops: frozenset[str] = frozenset({"create", "get"})) -> dict[str, BindingComponent]:
    return {name: BindingComponent(name=name, allowed_operations=ops, execute=_echo_exec)}


# ---------------------------------------------------------------------------
# OBND_INV_01 — operation must be declared
# ---------------------------------------------------------------------------
def test_inv_operation_allowlist_confirms() -> None:
    reg = _registry()
    req = BindingInvocation(binding_name="sendgrid", operation="create", data=b"x", metadata={})
    validate_invocation(req, reg)


def test_inv_operation_allowlist_prevents() -> None:
    reg = _registry()
    req = BindingInvocation(binding_name="sendgrid", operation="delete", data=b"x", metadata={})
    with pytest.raises(OutboundBindingError, match="OBND-INV-01"):
        validate_invocation(req, reg)


def test_inv_operation_allowlist_under_failure() -> None:
    binding = InMemoryOutboundBinding(_registry())
    req = BindingInvocation(binding_name="sendgrid", operation="purge", data=b"x", metadata={})
    with pytest.raises(OutboundBindingError, match="OBND-INV-01"):
        asyncio.run(binding.invoke(req))


# ---------------------------------------------------------------------------
# OBND_INV_02 — binding_name must resolve
# ---------------------------------------------------------------------------
def test_inv_binding_name_resolves_confirms() -> None:
    reg = _registry("s3", frozenset({"put"}))
    req = BindingInvocation(binding_name="s3", operation="put", data=b"", metadata={})
    validate_invocation(req, reg)


def test_inv_binding_name_resolves_prevents() -> None:
    reg = _registry()
    req = BindingInvocation(binding_name="nonexistent", operation="create", data=b"", metadata={})
    with pytest.raises(OutboundBindingError, match="OBND-INV-02"):
        validate_invocation(req, reg)


def test_inv_binding_name_resolves_under_failure() -> None:
    binding = InMemoryOutboundBinding(_registry())
    # Empty binding_name also fails.
    req = BindingInvocation(binding_name="", operation="create", data=b"", metadata={})
    with pytest.raises(OutboundBindingError, match="OBND-INV-02"):
        asyncio.run(binding.invoke(req))


# ---------------------------------------------------------------------------
# OBND_INV_03 — no plaintext secrets in metadata
# ---------------------------------------------------------------------------
def test_inv_no_plaintext_secrets_confirms() -> None:
    validate_metadata_secrets({"emailTo": "alice@example.com", "region": "us-east-1"})


def test_inv_no_plaintext_secrets_prevents() -> None:
    with pytest.raises(OutboundBindingError, match="OBND-INV-03"):
        validate_metadata_secrets({"auth": "Bearer abcdefghijklmnopqrstuv12345"})
    with pytest.raises(OutboundBindingError, match="OBND-INV-03"):
        validate_metadata_secrets({"api_key": "any-value"})


def test_inv_no_plaintext_secrets_under_failure() -> None:
    binding = InMemoryOutboundBinding(_registry())
    req = BindingInvocation(
        binding_name="sendgrid", operation="create", data=b"x",
        metadata={"password": "supersecret"},
    )
    with pytest.raises(OutboundBindingError, match="OBND-INV-03"):
        asyncio.run(binding.invoke(req))


# ---------------------------------------------------------------------------
# OBND_INV_04 — bytes roundtrip unchanged
# ---------------------------------------------------------------------------
def test_inv_bytes_roundtrip_confirms() -> None:
    binding = InMemoryOutboundBinding(_registry())
    payload = bytes(range(256))
    req = BindingInvocation(binding_name="sendgrid", operation="create", data=payload, metadata={})
    out, _ = asyncio.run(binding.invoke(req))
    assert out == payload


def test_inv_bytes_roundtrip_prevents() -> None:
    reg = _registry()
    req = BindingInvocation(binding_name="sendgrid", operation="create", data="not-bytes", metadata={})  # type: ignore[arg-type]
    with pytest.raises(OutboundBindingError, match="OBND-INV-04"):
        validate_invocation(req, reg)


def test_inv_bytes_roundtrip_under_failure() -> None:
    async def mutate_exec(req: BindingInvocation) -> tuple[bytes, Mapping[str, str]]:
        return "oops-str-not-bytes", {}  # type: ignore[return-value]

    reg = {"bad": BindingComponent(name="bad", allowed_operations=frozenset({"x"}), execute=mutate_exec)}
    binding = InMemoryOutboundBinding(reg)
    req = BindingInvocation(binding_name="bad", operation="x", data=b"ok", metadata={})
    with pytest.raises(OutboundBindingError, match="OBND-INV-04"):
        asyncio.run(binding.invoke(req))


# ---------------------------------------------------------------------------
# OBND_INV_05 — timeout honored
# ---------------------------------------------------------------------------
def test_inv_timeout_honored_confirms() -> None:
    binding = InMemoryOutboundBinding(_registry())
    req = BindingInvocation(binding_name="sendgrid", operation="create", data=b"fast", metadata={})
    out, _ = asyncio.run(binding.invoke(req, timeout_s=1.0))
    assert out == b"fast"


def test_inv_timeout_honored_prevents() -> None:
    async def slow_exec(req: BindingInvocation) -> tuple[bytes, Mapping[str, str]]:
        await asyncio.sleep(5.0)
        return req.data, {}

    reg = {"slow": BindingComponent(name="slow", allowed_operations=frozenset({"x"}), execute=slow_exec)}
    binding = InMemoryOutboundBinding(reg, default_timeout_s=0.01)
    req = BindingInvocation(binding_name="slow", operation="x", data=b"", metadata={})
    with pytest.raises(BindingDeadlineExceededError, match="OBND-INV-05"):
        asyncio.run(binding.invoke(req))


def test_inv_timeout_honored_under_failure() -> None:
    binding = InMemoryOutboundBinding(_registry())
    req = BindingInvocation(binding_name="sendgrid", operation="create", data=b"", metadata={})
    # Passing timeout_s <= 0 MUST raise (no infinite wait).
    with pytest.raises(OutboundBindingError, match="OBND-INV-05"):
        asyncio.run(binding.invoke(req, timeout_s=0))
