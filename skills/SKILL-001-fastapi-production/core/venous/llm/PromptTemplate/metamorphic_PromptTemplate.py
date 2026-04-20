"""Metamorphic + differential tests for PromptTemplate.

Algebraic laws:
- Rendering is idempotent: render(v) == render(v) for any fixed v.
- Fingerprint is a pure function of (name, version, target_model, text, variables).
- Rendering different values MUST produce outputs whose difference corresponds
  exactly to the value difference (no stray substitutions).
- Registry: register; register(same) is idempotent; register(conflict) raises.
"""

from __future__ import annotations

import pytest

from PromptTemplate import (
    FrozenPromptTemplate,
    PromptRegistry,
    PromptTemplateInvariantError,
)


def _tpl(text: str, variables: tuple[str, ...]) -> FrozenPromptTemplate:
    return FrozenPromptTemplate(name="m", version=1, target_model="mm",
                                 text=text, variables=variables)


def test_metamorphic_render_is_pure_function_of_values() -> None:
    tpl = _tpl("A {{x}} B {{y}}", ("x", "y"))
    samples = [{"x": "1", "y": "2"}, {"x": "!", "y": "?"}, {"x": "", "y": ""}]
    for s in samples:
        assert tpl.render(s) == tpl.render(s)


def test_metamorphic_fingerprint_stable_across_constructions() -> None:
    fps = [
        FrozenPromptTemplate(name="n", version=1, target_model="m",
                             text="x {{a}}", variables=("a",)).fingerprint()
        for _ in range(20)
    ]
    assert len(set(fps)) == 1


def test_metamorphic_variable_order_in_declaration_irrelevant_to_fp() -> None:
    # Fingerprint canonicalizes declared-variable set via sort — (a,b) and (b,a) same fp.
    a = FrozenPromptTemplate(name="n", version=1, target_model="m",
                             text="{{a}} {{b}}", variables=("a", "b"))
    b = FrozenPromptTemplate(name="n", version=1, target_model="m",
                             text="{{a}} {{b}}", variables=("b", "a"))
    assert a.fingerprint() == b.fingerprint()


def test_differential_changing_text_changes_fingerprint() -> None:
    a = FrozenPromptTemplate(name="n", version=1, target_model="m",
                             text="A {{x}}", variables=("x",))
    b = FrozenPromptTemplate(name="n", version=1, target_model="m",
                             text="B {{x}}", variables=("x",))
    assert a.fingerprint() != b.fingerprint()


def test_metamorphic_registry_idempotent_identical_register() -> None:
    reg = PromptRegistry()
    for _ in range(5):
        reg.register(FrozenPromptTemplate(name="g", version=1, target_model="m",
                                           text="t {{x}}", variables=("x",)))
    assert reg.versions("g") == (1,)


def test_metamorphic_render_output_length_tracks_value_length() -> None:
    tpl = _tpl("V={{v}}", ("v",))
    for size in (0, 1, 10, 100, 1000):
        out = tpl.render({"v": "x" * size})
        assert len(out) == len("V=") + size


def test_metamorphic_no_recursive_expansion() -> None:
    tpl = _tpl("{{a}}", ("a",))
    # Value containing another placeholder MUST survive literally.
    out = tpl.render({"a": "{{b}}"})
    assert out == "{{b}}"


def test_metamorphic_registry_rejects_mutation() -> None:
    reg = PromptRegistry()
    reg.register(FrozenPromptTemplate(name="g", version=1, target_model="m",
                                       text="v1 {{x}}", variables=("x",)))
    with pytest.raises(PromptTemplateInvariantError):
        reg.register(FrozenPromptTemplate(name="g", version=1, target_model="m",
                                           text="v2 {{x}}", variables=("x",)))
