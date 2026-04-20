"""Behavioral end-to-end scenarios for OutboundBinding."""

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
)


async def _echo(req: BindingInvocation) -> tuple[bytes, Mapping[str, str]]:
    return req.data, {"echo": "1"}


def test_scenario_send_email_via_sendgrid_adapter() -> None:
    reg = {"sendgrid": BindingComponent(
        name="sendgrid", allowed_operations=frozenset({"create"}), execute=_echo,
    )}
    binding = InMemoryOutboundBinding(reg)
    inv = BindingInvocation(
        binding_name="sendgrid", operation="create",
        data=b"<html>hi</html>",
        metadata={"emailTo": "u@x.com"},
    )
    out, md = asyncio.run(binding.invoke(inv))
    assert out == b"<html>hi</html>"
    assert md["echo"] == "1"
    assert binding.invocations == 1


def test_scenario_unknown_operation_is_refused_before_execute() -> None:
    called = False

    async def spy(_req: BindingInvocation) -> tuple[bytes, Mapping[str, str]]:
        nonlocal called
        called = True
        return b"", {}

    reg = {"x": BindingComponent(name="x", allowed_operations=frozenset({"a"}), execute=spy)}
    binding = InMemoryOutboundBinding(reg)
    inv = BindingInvocation(binding_name="x", operation="b", data=b"", metadata={})
    with pytest.raises(OutboundBindingError):
        asyncio.run(binding.invoke(inv))
    assert called is False


def test_scenario_timeout_surfaces_as_deadline_exceeded() -> None:
    async def slow(_req: BindingInvocation) -> tuple[bytes, Mapping[str, str]]:
        await asyncio.sleep(5)
        return b"", {}

    reg = {"slow": BindingComponent(name="slow", allowed_operations=frozenset({"x"}), execute=slow)}
    binding = InMemoryOutboundBinding(reg, default_timeout_s=0.02)
    with pytest.raises(BindingDeadlineExceededError):
        asyncio.run(binding.invoke(BindingInvocation(
            binding_name="slow", operation="x", data=b"", metadata={},
        )))


def test_scenario_registry_isolation() -> None:
    reg_a = {"a": BindingComponent(name="a", allowed_operations=frozenset({"op"}), execute=_echo)}
    reg_b = {"b": BindingComponent(name="b", allowed_operations=frozenset({"op"}), execute=_echo)}
    binding_a = InMemoryOutboundBinding(reg_a)
    binding_b = InMemoryOutboundBinding(reg_b)
    with pytest.raises(OutboundBindingError):
        asyncio.run(binding_a.invoke(BindingInvocation(
            binding_name="b", operation="op", data=b"", metadata={},
        )))
    asyncio.run(binding_b.invoke(BindingInvocation(
        binding_name="b", operation="op", data=b"", metadata={},
    )))


def test_scenario_metadata_with_bearer_rejected() -> None:
    reg = {"x": BindingComponent(name="x", allowed_operations=frozenset({"op"}), execute=_echo)}
    binding = InMemoryOutboundBinding(reg)
    inv = BindingInvocation(
        binding_name="x", operation="op", data=b"",
        metadata={"auth": "Bearer abcdefghijklmnopqrstuvwx"},
    )
    with pytest.raises(OutboundBindingError):
        asyncio.run(binding.invoke(inv))


def test_scenario_roundtrip_of_large_binary_payload() -> None:
    reg = {"r": BindingComponent(name="r", allowed_operations=frozenset({"op"}), execute=_echo)}
    binding = InMemoryOutboundBinding(reg)
    payload = bytes((i % 251 for i in range(8192)))
    out, _ = asyncio.run(binding.invoke(BindingInvocation(
        binding_name="r", operation="op", data=payload, metadata={},
    )))
    assert out == payload
