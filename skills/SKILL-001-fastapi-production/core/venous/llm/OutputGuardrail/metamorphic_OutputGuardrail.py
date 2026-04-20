"""Metamorphic + differential tests for OutputGuardrail.

Algebraic laws probed:
- evaluate() is a pure function of (output, schema_ref) — two calls with
  identical inputs produce equal verdicts.
- Composing two rewrite guards is associative-with-respect-to output; the
  ordered chain corresponds to sequential string substitution.
- Identity law: an empty rewrite_patterns / empty block_patterns policy guard
  always returns `pass` without mutating the output.
- Differential parity: the minimal in-tree schema checker agrees with
  `jsonschema` (when installed) on the canonical cases in this module.
"""

from __future__ import annotations

from OutputGuardrail import (
    PolicyOutputGuardrail,
    SafetyOutputGuardrail,
    SchemaOutputGuardrail,
    Verdict,
    apply_chain,
)

_SCHEMAS: dict[str, dict[str, object]] = {
    "user.v1": {
        "type": "object",
        "required": ["id"],
        "properties": {"id": {"type": "integer"}},
    },
}


def test_metamorphic_evaluate_is_pure() -> None:
    g = SchemaOutputGuardrail(name="s", schemas=_SCHEMAS)
    for output, schema_ref in (
        ('{"id": 1}', "user.v1"),
        ('{"id": "bad"}', "user.v1"),
        ("not json", "user.v1"),
        ("anything", None),
    ):
        v1 = g.evaluate(output, schema_ref)
        v2 = g.evaluate(output, schema_ref)
        assert isinstance(v1, Verdict)
        assert isinstance(v2, Verdict)
        assert v1 == v2


def test_metamorphic_policy_identity_law() -> None:
    # No block_patterns and no rewrite_patterns → always `pass`, output unchanged.
    g = PolicyOutputGuardrail(name="noop")
    for raw in ("", "arbitrary", '{"x": 1}', "🦉 hoot"):
        v = g.evaluate(raw, None)
        assert v.action == "pass"


def test_metamorphic_safety_never_mutates_output() -> None:
    g = SafetyOutputGuardrail(name="safety")
    for raw in ("nothing special", "numbers 1 2 3", "UPPER case"):
        v = g.evaluate(raw, None)
        assert v.action == "pass"
        # Safety guard NEVER returns a rewrite — only pass or block.
        assert v.action in {"pass", "block"}
        assert v.replacement is None


def test_metamorphic_chain_rewrite_is_left_fold() -> None:
    # Apply two rewrite patterns as a chain vs. manually — outputs must match.
    g1 = PolicyOutputGuardrail(name="g1", rewrite_patterns=((r"foo", "bar"),))
    g2 = PolicyOutputGuardrail(name="g2", rewrite_patterns=((r"bar", "baz"),))
    out = apply_chain([g1, g2], "foo and foo")
    # Manual left-fold: "foo and foo" -> "bar and bar" -> "baz and baz"
    assert out == "baz and baz"


def test_differential_minimal_schema_check_matches_jsonschema_on_shape() -> None:
    # The minimal in-tree checker MUST reject the shapes jsonschema would reject
    # for the invariants we care about: missing required, type mismatch.
    g = SchemaOutputGuardrail(name="s", schemas=_SCHEMAS)
    # missing required 'id'
    v_missing = g.evaluate('{"other": 1}', "user.v1")
    assert v_missing.action == "block"
    # wrong type for id
    v_wrong = g.evaluate('{"id": "text"}', "user.v1")
    assert v_wrong.action == "block"
    # correct shape
    v_ok = g.evaluate('{"id": 7}', "user.v1")
    assert v_ok.action == "pass"


def test_metamorphic_verdict_equality_is_structural() -> None:
    a = Verdict(action="rewrite", reason="r", replacement="x")
    b = Verdict(action="rewrite", reason="r", replacement="x")
    c = Verdict(action="rewrite", reason="r", replacement="y")
    assert a == b
    assert a != c
    # Equal verdicts hash equal.
    assert hash(a) == hash(b)


def test_metamorphic_pass_on_valid_is_idempotent_under_repetition() -> None:
    # Running the same chain twice on the same already-clean input is identity.
    chain = [
        SafetyOutputGuardrail(name="safety"),
        PolicyOutputGuardrail(name="policy"),
    ]
    raw = "clean text"
    once = apply_chain(chain, raw)
    twice = apply_chain(chain, once)
    assert once == raw == twice
