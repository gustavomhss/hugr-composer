"""Chaos / fault-injection for PromptTemplate.

Game-day scenarios: oversize payloads, injection attempts, race on registry,
Unicode normalization edge cases, pathological placeholder shapes.
"""

from __future__ import annotations

import threading

import pytest

from PromptTemplate import (
    FrozenPromptTemplate,
    PromptRegistry,
    PromptTemplateInvariantError,
)


def test_chaos_oversize_value_rejected() -> None:
    tpl = FrozenPromptTemplate(name="o", version=1, target_model="m",
                                text="V={{v}}", variables=("v",))
    with pytest.raises(PromptTemplateInvariantError):
        tpl.render({"v": "x" * 300_001})


def test_chaos_nullbyte_in_value_survives_literally() -> None:
    tpl = FrozenPromptTemplate(name="n", version=1, target_model="m",
                                text="{{x}}", variables=("x",))
    out = tpl.render({"x": "a\x00b"})
    assert out == "a\x00b"  # passthrough, no crash


def test_chaos_extra_values_rejected() -> None:
    tpl = FrozenPromptTemplate(name="e", version=1, target_model="m",
                                text="{{a}}", variables=("a",))
    with pytest.raises(PromptTemplateInvariantError):
        tpl.render({"a": "1", "b": "2"})


def test_chaos_concurrent_registry_one_winner() -> None:
    reg = PromptRegistry()
    errs: list[BaseException] = []
    wins = 0

    def _try(i: int) -> None:
        try:
            reg.register(FrozenPromptTemplate(
                name="c", version=1, target_model="m",
                text=f"v{i} {{{{x}}}}", variables=("x",)))
        except PromptTemplateInvariantError as e:
            errs.append(e)

    threads = [threading.Thread(target=_try, args=(i,)) for i in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # Exactly one winner; the other 15 must fail.
    registered = reg.resolve("c", 1)
    _ = registered.fingerprint()
    assert len(errs) >= 15


def test_chaos_placeholder_in_value_not_reexpanded() -> None:
    tpl = FrozenPromptTemplate(name="p", version=1, target_model="m",
                                text="{{msg}}", variables=("msg",))
    out = tpl.render({"msg": "{{secret}} and {{auth}}"})
    assert out == "{{secret}} and {{auth}}"  # verbatim, no injection


def test_chaos_unicode_values_preserved() -> None:
    tpl = FrozenPromptTemplate(name="u", version=1, target_model="m",
                                text="{{s}}", variables=("s",))
    for v in ("日本語", "🔥💧", "straße", "\u202e"):
        assert tpl.render({"s": v}) == v


def test_chaos_non_str_value_rejected() -> None:
    tpl = FrozenPromptTemplate(name="t", version=1, target_model="m",
                                text="{{x}}", variables=("x",))
    for bad in (123, None, True, [1, 2], {"k": "v"}):
        with pytest.raises(PromptTemplateInvariantError):
            tpl.render({"x": bad})  # type: ignore[dict-item] — PROMPT-INV-05 chaos probe.


def test_chaos_mutation_attempt_raises() -> None:
    tpl = FrozenPromptTemplate(name="m", version=1, target_model="m",
                                text="{{x}}", variables=("x",))
    for attr in ("_name", "_version", "_text", "_target_model", "_variables"):
        with pytest.raises(PromptTemplateInvariantError):
            setattr(tpl, attr, "hijacked")
