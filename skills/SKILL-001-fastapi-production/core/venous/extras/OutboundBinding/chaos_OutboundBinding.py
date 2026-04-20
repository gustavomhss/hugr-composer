"""Chaos / fault-injection for OutboundBinding."""

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
    return req.data, {}


def test_chaos_empty_payload_accepted() -> None:
    reg = {"x": BindingComponent(name="x", allowed_operations=frozenset({"op"}), execute=_echo)}
    binding = InMemoryOutboundBinding(reg)
    out, _ = asyncio.run(binding.invoke(BindingInvocation(
        binding_name="x", operation="op", data=b"", metadata={},
    )))
    assert out == b""


def test_chaos_large_payload_roundtrip_under_load() -> None:
    reg = {"x": BindingComponent(name="x", allowed_operations=frozenset({"op"}), execute=_echo)}
    binding = InMemoryOutboundBinding(reg)
    payload = b"\xff" * 65536
    for _ in range(20):
        out, _ = asyncio.run(binding.invoke(BindingInvocation(
            binding_name="x", operation="op", data=payload, metadata={},
        )))
        assert out == payload


def test_chaos_adapter_crashes_surfaces_as_error() -> None:
    async def crash(_req: BindingInvocation) -> tuple[bytes, Mapping[str, str]]:
        raise RuntimeError("downstream dead")

    reg = {"c": BindingComponent(name="c", allowed_operations=frozenset({"op"}), execute=crash)}
    binding = InMemoryOutboundBinding(reg)
    with pytest.raises(RuntimeError, match="downstream dead"):
        asyncio.run(binding.invoke(BindingInvocation(
            binding_name="c", operation="op", data=b"", metadata={},
        )))


def test_chaos_multiple_adapters_isolated() -> None:
    reg = {
        "a": BindingComponent(name="a", allowed_operations=frozenset({"op"}), execute=_echo),
        "b": BindingComponent(name="b", allowed_operations=frozenset({"op"}), execute=_echo),
    }
    binding = InMemoryOutboundBinding(reg)
    for name in ("a", "b"):
        asyncio.run(binding.invoke(BindingInvocation(
            binding_name=name, operation="op", data=b"", metadata={},
        )))


def test_chaos_concurrent_invocations_safe() -> None:
    reg = {"x": BindingComponent(name="x", allowed_operations=frozenset({"op"}), execute=_echo)}
    binding = InMemoryOutboundBinding(reg)

    async def fire() -> bytes:
        out, _ = await binding.invoke(BindingInvocation(
            binding_name="x", operation="op", data=b"x", metadata={},
        ))
        return out

    async def run_all() -> list[bytes]:
        return await asyncio.gather(*(fire() for _ in range(100)))

    results = asyncio.run(run_all())
    assert all(r == b"x" for r in results)
    assert binding.invocations == 100


def test_chaos_timeout_applies_even_under_adapter_pause() -> None:
    async def pause(_req: BindingInvocation) -> tuple[bytes, Mapping[str, str]]:
        await asyncio.sleep(10)
        return b"", {}

    reg = {"p": BindingComponent(name="p", allowed_operations=frozenset({"op"}), execute=pause)}
    binding = InMemoryOutboundBinding(reg, default_timeout_s=0.02)
    with pytest.raises(BindingDeadlineExceededError):
        asyncio.run(binding.invoke(BindingInvocation(
            binding_name="p", operation="op", data=b"", metadata={},
        )))


def test_chaos_secret_variants_in_metadata_all_caught() -> None:
    reg = {"x": BindingComponent(name="x", allowed_operations=frozenset({"op"}), execute=_echo)}
    binding = InMemoryOutboundBinding(reg)
    # Use a credential-like string that matches the detector (sk-ant-*).
    for md in (
        {"token": "sk-ant-ABCDEFGHIJKLMNOPQRSTUVWX"},
        {"password": "anything"},
        {"API_KEY": "whatever"},
    ):
        with pytest.raises(OutboundBindingError):
            asyncio.run(binding.invoke(BindingInvocation(
                binding_name="x", operation="op", data=b"", metadata=md,
            )))
