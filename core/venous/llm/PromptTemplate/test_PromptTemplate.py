"""Unit tests for PromptTemplate — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import threading

import pytest
from PromptTemplate import (
    FrozenPromptTemplate,
    PromptRegistry,
    PromptTemplateInvariantError,
    validate_name,
    validate_variables,
    validate_version,
)


def _make(version: int = 1, text: str = "Hello {{name}}!") -> FrozenPromptTemplate:
    return FrozenPromptTemplate(
        name="greet",
        version=version,
        target_model="claude-sonnet-4-6",
        text=text,
        variables=("name",),
    )


# ---------------------------------------------------------------------------
# PROMPT_INV_01 — render determinism
# ---------------------------------------------------------------------------
def test_inv_render_determinism_confirms() -> None:
    tpl = _make()
    out1 = tpl.render({"name": "Ada"})
    out2 = tpl.render({"name": "Ada"})
    assert out1 == out2 == "Hello Ada!"


def test_inv_render_determinism_prevents() -> None:
    tpl1 = FrozenPromptTemplate(name="g", version=1, target_model="m",
                                 text="a {{x}}", variables=("x",))
    tpl2 = FrozenPromptTemplate(name="g", version=2, target_model="m",
                                 text="b {{x}}", variables=("x",))
    # Different versions MUST produce different rendered outputs when text differs.
    assert tpl1.render({"x": "1"}) != tpl2.render({"x": "1"})


def test_inv_render_determinism_under_failure() -> None:
    tpl = _make()
    # Even under concurrent calls, output for identical values is identical.
    results: list[str] = []

    def _call() -> None:
        results.append(tpl.render({"name": "Ada"}))

    threads = [threading.Thread(target=_call) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert all(r == "Hello Ada!" for r in results)


# ---------------------------------------------------------------------------
# PROMPT_INV_02 — immutability & version bump
# ---------------------------------------------------------------------------
def test_inv_immutable_confirms() -> None:
    tpl = _make()
    with pytest.raises(PromptTemplateInvariantError):
        tpl._text = "hijacked"  # type: ignore[misc] — PROMPT-INV-02: prove override raises.
    with pytest.raises(PromptTemplateInvariantError):
        tpl._version = 99  # type: ignore[misc] — PROMPT-INV-02: version cannot mutate.


def test_inv_immutable_prevents() -> None:
    reg = PromptRegistry()
    t1 = _make(version=1, text="v1 {{name}}")
    t2 = _make(version=1, text="v2 {{name}}")  # same (name, version), different text
    reg.register(t1)
    with pytest.raises(PromptTemplateInvariantError):
        reg.register(t2)


def test_inv_immutable_under_failure() -> None:
    reg = PromptRegistry()
    # Concurrent registration of conflicting (name, version) MUST raise exactly once.
    errs: list[BaseException] = []

    def _reg(text: str) -> None:
        try:
            reg.register(_make(version=7, text=text))
        except PromptTemplateInvariantError as e:
            errs.append(e)

    threads = [threading.Thread(target=_reg, args=(f"t{i} {{{{name}}}}",)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # At most one registration wins; others see invariant error.
    assert len(errs) >= 7


# ---------------------------------------------------------------------------
# PROMPT_INV_03 — missing variable raises, no silent empty
# ---------------------------------------------------------------------------
def test_inv_missing_variable_confirms() -> None:
    tpl2 = FrozenPromptTemplate(name="x", version=1, target_model="m",
                                 text="A {{a}} B {{b}}", variables=("a", "b"))
    with pytest.raises(PromptTemplateInvariantError):
        tpl2.render({"a": "only"})


def test_inv_missing_variable_prevents() -> None:
    tpl = _make()
    with pytest.raises(PromptTemplateInvariantError):
        tpl.render({})  # empty values MUST raise, not produce "Hello !"


def test_inv_missing_variable_under_failure() -> None:
    tpl = _make()
    # An empty-string VALUE is legal; the error is about MISSING keys only.
    out = tpl.render({"name": ""})
    assert out == "Hello !"  # explicit empty string passes through


# ---------------------------------------------------------------------------
# PROMPT_INV_04 — fingerprint sensitivity
# ---------------------------------------------------------------------------
def test_inv_fingerprint_covers_all_confirms() -> None:
    a = FrozenPromptTemplate(name="n", version=1, target_model="m1",
                             text="t {{x}}", variables=("x",))
    b = FrozenPromptTemplate(name="n", version=1, target_model="m2",
                             text="t {{x}}", variables=("x",))
    assert a.fingerprint() != b.fingerprint()  # target_model drift detected


def test_inv_fingerprint_covers_all_prevents() -> None:
    a = FrozenPromptTemplate(name="n", version=1, target_model="m",
                             text="t {{x}}", variables=("x",))
    b = FrozenPromptTemplate(name="n", version=1, target_model="m",
                             text="t {{y}}", variables=("y",))
    assert a.fingerprint() != b.fingerprint()  # variable-rename detected


def test_inv_fingerprint_covers_all_under_failure() -> None:
    a = FrozenPromptTemplate(name="n", version=1, target_model="m",
                             text="t {{x}}", variables=("x",))
    b = FrozenPromptTemplate(name="n", version=1, target_model="m",
                             text="t {{x}}", variables=("x",))
    assert a.fingerprint() == b.fingerprint()  # identical inputs, identical fp
    assert a.fingerprint().startswith("sha256:")


# ---------------------------------------------------------------------------
# PROMPT_INV_05 — no injection via values
# ---------------------------------------------------------------------------
def test_inv_no_injection_confirms() -> None:
    tpl = _make()
    # A value that contains {{other}} MUST be treated as literal data.
    out = tpl.render({"name": "{{injected}} DROP TABLE"})
    assert out == "Hello {{injected}} DROP TABLE!"
    # The literal {{injected}} in the output is opaque text, never re-expanded.


def test_inv_no_injection_prevents() -> None:
    tpl = _make()
    # Extra values — even benign ones — are rejected.
    with pytest.raises(PromptTemplateInvariantError):
        tpl.render({"name": "ok", "extra": "smuggle"})


def test_inv_no_injection_under_failure() -> None:
    tpl = _make()
    # Non-string values are rejected (no implicit coercion smuggles).
    with pytest.raises(PromptTemplateInvariantError):
        tpl.render({"name": 123})  # type: ignore[dict-item] — PROMPT-INV-05: non-str value.
    with pytest.raises(PromptTemplateInvariantError):
        tpl.render({"name": None})  # type: ignore[dict-item] — PROMPT-INV-05: None rejected.


# ---------------------------------------------------------------------------
# Validator-level tests
# ---------------------------------------------------------------------------
def test_validators_reject_bad_inputs() -> None:
    with pytest.raises(PromptTemplateInvariantError):
        validate_name("")
    with pytest.raises(PromptTemplateInvariantError):
        validate_version(0)
    with pytest.raises(PromptTemplateInvariantError):
        validate_version(True)  # bool masquerading as int — PROMPT-INV-02.
    with pytest.raises(PromptTemplateInvariantError):
        validate_variables(("1bad",))
    with pytest.raises(PromptTemplateInvariantError):
        validate_variables(("dup", "dup"))
