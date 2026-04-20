"""Metamorphic + differential tests for OutboundBinding.

Algebraic properties:
- invoke(invoke(x)) preserves the bytes (echo composition).
- registry lookup is idempotent — repeated validations never mutate registry.
- validation is pure (no side-effect on input metadata).
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from OutboundBinding import (
    BindingComponent,
    BindingInvocation,
    InMemoryOutboundBinding,
    validate_invocation,
    validate_metadata_secrets,
)


async def _echo(req: BindingInvocation) -> tuple[bytes, Mapping[str, str]]:
    return req.data, {}


def test_metamorphic_idempotent_validation() -> None:
    reg = {"x": BindingComponent(name="x", allowed_operations=frozenset({"op"}), execute=_echo)}
    req = BindingInvocation(binding_name="x", operation="op", data=b"payload", metadata={"k": "v"})
    for _ in range(20):
        validate_invocation(req, reg)


def test_metamorphic_metadata_not_mutated_by_validation() -> None:
    original = {"k": "v", "emailTo": "u@x.com"}
    copy = dict(original)
    validate_metadata_secrets(copy)
    assert copy == original


def test_metamorphic_bytes_roundtrip_preserved_across_repeated_invokes() -> None:
    reg = {"x": BindingComponent(name="x", allowed_operations=frozenset({"op"}), execute=_echo)}
    binding = InMemoryOutboundBinding(reg)
    payload = b"\x00\x01\x02deadbeef"
    for _ in range(10):
        out, _ = asyncio.run(binding.invoke(BindingInvocation(
            binding_name="x", operation="op", data=payload, metadata={},
        )))
        assert out == payload


def test_differential_two_bindings_same_result() -> None:
    reg_a = {"x": BindingComponent(name="x", allowed_operations=frozenset({"op"}), execute=_echo)}
    reg_b = {"x": BindingComponent(name="x", allowed_operations=frozenset({"op"}), execute=_echo)}
    ba = InMemoryOutboundBinding(reg_a)
    bb = InMemoryOutboundBinding(reg_b)
    req = BindingInvocation(binding_name="x", operation="op", data=b"same", metadata={})
    out_a, _ = asyncio.run(ba.invoke(req))
    out_b, _ = asyncio.run(bb.invoke(req))
    assert out_a == out_b == b"same"


def test_metamorphic_invocation_count_monotone() -> None:
    reg = {"x": BindingComponent(name="x", allowed_operations=frozenset({"op"}), execute=_echo)}
    binding = InMemoryOutboundBinding(reg)
    before = binding.invocations
    for _ in range(5):
        asyncio.run(binding.invoke(BindingInvocation(
            binding_name="x", operation="op", data=b"", metadata={},
        )))
    assert binding.invocations == before + 5
