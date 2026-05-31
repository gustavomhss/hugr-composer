"""Pair honesty test for B0.13 — ``extend/auth_access/add_feature_flags``.

Closes the Wave-0.5 waiver for ``add_feature_flags`` in
``r_notes_match_behaviour._WAIVED_TOOLS``. The original waiver was filed
because the tool's notes claimed "in-process LRU cache with Redis pubsub
invalidation (< 1s fan-out)" while:

* **R5-S2-F7** — ``_patch_main`` emits the
  ``start_invalidation_listener`` call as a commented-out stub, so no
  worker actually subscribes to ``feature_flags:invalidate`` on boot.
* **R5-S2-F8** — even with the listener wired, the per-worker cache
  has a 60s TTL; until expiry, a kill-switch flip is invisible to a
  worker that already cached the flag (read-after-write race).

The fix was to (a) tone the notes down to the per-worker reality and
(b) move the gap into ``warnings=`` so agents see the disclosure at
compose time. This test asserts the disclosure shape so neither side
of the pair can silently drift back to the over-claim.

The other two waivers (`add_feature_flags` in
``r_write_schemas_strict._WAIVED_TOOLS`` — B0.14, and the regression
on the schemas template) are validated in the same file because they
ship in the same PR and share fixture setup.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent.parent
sys.path.insert(0, str(SKILL_ROOT))

TOOL_DIR = (
    SKILL_ROOT
    / "adapt"
    / "extend"
    / "auth_access"
    / "add_feature_flags"
)
TOOL_INIT = TOOL_DIR / "__init__.py"
SCHEMAS_TMPL = TOOL_DIR / "templates" / "schemas.py.tmpl"


# ---------------------------------------------------------------------------
# Placeholder cleanup — same shape as the rule files use, so .py.tmpl
# files can be exec'd directly into a fresh namespace.
# ---------------------------------------------------------------------------

_PLACEHOLDER_BRACED_RE = re.compile(r"\$\{[^}]+\}")
_PLACEHOLDER_BARE_RE = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*")


def _clean(src: str) -> str:
    src = _PLACEHOLDER_BRACED_RE.sub("PLACEHOLDER", src)
    src = _PLACEHOLDER_BARE_RE.sub("PLACEHOLDER", src)
    return src


def _exec_template(path: Path) -> dict:
    """Compile + exec a ``.py.tmpl`` (placeholders stripped) into a fresh ns.

    Because the template uses ``from __future__ import annotations`` every
    annotation is a string at class-creation time; Pydantic needs the
    surrounding namespace to resolve forward refs (TargetingRule,
    Variant, Literal, _ScalarValue, …). We rebuild every BaseModel
    subclass in the namespace with the namespace itself as the type ns
    so tests can instantiate freely.
    """
    src = _clean(path.read_text(encoding="utf-8"))
    ns: dict = {"__name__": f"under_test_{path.stem}"}
    exec(compile(src, str(path), "exec"), ns)  # noqa: S102 — exec is the test
    try:
        from pydantic import BaseModel
    except ImportError:
        return ns
    for value in list(ns.values()):
        if (
            isinstance(value, type)
            and issubclass(value, BaseModel)
            and value is not BaseModel
        ):
            try:
                value.model_rebuild(_types_namespace=ns)
            except Exception:  # noqa: BLE001 — rebuild may be unnecessary
                pass
    return ns


# ---------------------------------------------------------------------------
# B0.13 — notes are honest about the per-worker cache + the gap is in
# warnings=, NOT in the success-prose notes block.
# ---------------------------------------------------------------------------


def _all_blocks(src: str, kwarg: str) -> list[str]:
    """Return every ``<kwarg>=[ ... ]`` literal in the file as joined text.

    AST-based so embedded ``[...]`` inside a string literal (e.g. a
    next_steps line that includes ``dependencies=[Depends(...)]``)
    doesn't terminate the match early. Walks every ``ToolResult(...)``
    call and concatenates the string elements of the matching keyword's
    List value. Only string constants are collected — non-string
    elements (None, expressions) are skipped silently."""
    import ast as _ast

    out: list[str] = []
    try:
        tree = _ast.parse(src)
    except SyntaxError:
        return out
    for node in _ast.walk(tree):
        if not isinstance(node, _ast.Call):
            continue
        callee = node.func
        name = (
            callee.id if isinstance(callee, _ast.Name)
            else (callee.attr if isinstance(callee, _ast.Attribute) else "")
        )
        if name != "ToolResult":
            continue
        for kw in node.keywords:
            if kw.arg != kwarg:
                continue
            if not isinstance(kw.value, _ast.List):
                continue
            chunk: list[str] = []
            for el in kw.value.elts:
                if isinstance(el, _ast.Constant) and isinstance(el.value, str):
                    chunk.append(el.value)
            if chunk:
                out.append("\n".join(chunk))
    return out


def test_b0_13_notes_do_not_overclaim_fan_out() -> None:
    """B0.13 (R5-S2-F7): the misleading "Redis pubsub invalidation
    (< 1s fan-out)" sentence MUST NOT appear in ANY of the notes
    blocks (success / dry_run / error). The tool's invalidation
    listener is shipped commented-out — claiming cross-worker fan-out
    is the exact over-claim the rule blocks.
    """
    src = TOOL_INIT.read_text(encoding="utf-8")
    notes_blocks = _all_blocks(src, "notes")
    assert notes_blocks, "Expected at least one notes=[...] literal"
    notes_text = "\n".join(notes_blocks).lower()
    # Strict literal check: the rule's claim-token list flags "fan-out"
    # (with hyphen). The pre-fix notes also said "distributed" in the
    # add_cache_layer family — exclude it here too as a belt-and-braces.
    assert "fan-out" not in notes_text, (
        "notes still claim 'fan-out' — invalidation listener is "
        "commented-out (R5-S2-F7); see warnings= for the honest "
        "disclosure path."
    )
    assert "distributed" not in notes_text, (
        "notes still claim 'distributed' — single-node cache shape "
        "(R5-S2-F7+F8) requires the per-worker disclosure instead."
    )
    assert "< 1s" not in notes_text and "<1s" not in notes_text, (
        "notes still ship the '< 1s fan-out' latency claim with no "
        "paired benchmark — the SLA is not enforced anywhere."
    )


def test_b0_13_warnings_disclose_listener_gap() -> None:
    """B0.13 (R5-S2-F7): the gap MUST be disclosed via ``warnings=`` so
    composing agents see it. ``warnings=`` is the rule's documented
    disclosure surface (the scanner does NOT inspect it, by design)."""
    src = TOOL_INIT.read_text(encoding="utf-8")
    warnings_blocks = _all_blocks(src, "warnings")
    assert warnings_blocks, (
        "Expected a warnings=[...] block in the success ToolResult; "
        "B0.13 requires the disclosure to be machine-readable, not "
        "buried in prose."
    )
    text = "\n".join(warnings_blocks).lower()
    # Listener gap (R5-S2-F7)
    assert "start_invalidation_listener" in text or "invalidation listener" in text, (
        "warnings= must name the start_invalidation_listener gap "
        "explicitly so operators can find the commented stub in main.py."
    )
    # TTL race (R5-S2-F8)
    assert "ttl" in text or "60s" in text or "kill-switch" in text, (
        "warnings= must disclose the per-worker TTL race that causes "
        "kill-switch lag (R5-S2-F8)."
    )


def test_b0_13_next_steps_provide_repair_path() -> None:
    """The next_steps block should give operators a concrete path from
    the per-worker default to the cross-worker shape — otherwise the
    disclosure is true but useless."""
    src = TOOL_INIT.read_text(encoding="utf-8")
    next_blocks = _all_blocks(src, "next_steps")
    assert next_blocks, "Expected at least one next_steps=[...] literal"
    text = "\n".join(next_blocks).lower()
    # Must reference all three pieces of the manual wiring:
    #   1. Redis itself
    #   2. The start_invalidation_listener uncomment
    #   3. publish_invalidation calls in CRUD
    assert "redis" in text, "next_steps must reference Redis provisioning"
    assert "start_invalidation_listener" in text or "lifespan" in text, (
        "next_steps must point operators at the lifespan stub to uncomment"
    )
    assert "publish_invalidation" in text, (
        "next_steps must name publish_invalidation as the CRUD-side hook"
    )


def test_b0_13_waiver_removed() -> None:
    """The waiver entry MUST be removed from ``_WAIVED_TOOLS`` —
    otherwise the rule keeps skipping the template even after the fix."""
    from engine.audit.contract_rules.r_notes_match_behaviour import (
        _WAIVED_TOOLS,
    )

    assert "extend/auth_access/add_feature_flags" not in _WAIVED_TOOLS, (
        "B0.13 waiver entry for add_feature_flags was NOT removed; "
        "the disclosure fix is meaningless if the rule still skips the "
        "tool's notes."
    )


# ---------------------------------------------------------------------------
# B0.14 — FeatureFlagCreate + FeatureFlagUpdate reject unknown keys, and
# the typed sub-models replace the legacy ``list[dict[str, Any]]`` surface.
# ---------------------------------------------------------------------------


def test_b0_14_feature_flag_create_rejects_unknown_keys() -> None:
    """B0.14 (Pattern P5 / R6-O3-P9): the write schema MUST reject
    unknown keys. Pre-fix the schema lacked ``extra="forbid"`` so any
    extra key (e.g. ``id``, ``updated_by``) was silently accepted into
    the ORM via mass-assignment."""
    from pydantic import ValidationError

    ns = _exec_template(SCHEMAS_TMPL)
    FeatureFlagCreate = ns.get("FeatureFlagCreate")
    assert FeatureFlagCreate is not None

    # Sanity: minimal valid payload accepted.
    ok = FeatureFlagCreate(key="my_flag")
    assert ok.key == "my_flag"

    # Core assertion: unknown key MUST raise.
    with pytest.raises(ValidationError):
        FeatureFlagCreate(
            key="my_flag",
            updated_by="00000000-0000-0000-0000-000000000000",  # smuggled
        )


def test_b0_14_feature_flag_update_rejects_unknown_keys() -> None:
    """Same as above but for the partial-update shape (separate class,
    not inheriting from FeatureFlagBase, so the test catches a fix that
    only landed on Create)."""
    from pydantic import ValidationError

    ns = _exec_template(SCHEMAS_TMPL)
    FeatureFlagUpdate = ns.get("FeatureFlagUpdate")
    assert FeatureFlagUpdate is not None

    # Sanity: empty payload accepted (all fields optional).
    FeatureFlagUpdate()

    # Core assertion: unknown key MUST raise.
    with pytest.raises(ValidationError):
        FeatureFlagUpdate(id="00000000-0000-0000-0000-000000000000")


def test_b0_14_targeting_rule_is_typed_submodel() -> None:
    """R6-O3-P9: ``targeting_rules`` must be ``list[TargetingRule]`` —
    not ``list[dict[str, Any]]``. The typed sub-model itself carries
    ``extra="forbid"`` so a rule with a typo'd key (e.g.
    ``attr=`` instead of ``attribute=``) raises at the boundary."""
    from pydantic import ValidationError

    ns = _exec_template(SCHEMAS_TMPL)
    TargetingRule = ns.get("TargetingRule")
    FeatureFlagCreate = ns.get("FeatureFlagCreate")
    assert TargetingRule is not None
    assert FeatureFlagCreate is not None

    # Valid rule — the four keys the evaluator actually reads.
    rule = TargetingRule(
        attribute="user_id",
        operator="equals",
        value="abc",
        return_value=True,
    )
    assert rule.attribute == "user_id"

    # Typo key on the sub-model must raise.
    with pytest.raises(ValidationError):
        TargetingRule(attr="user_id", operator="equals", value="abc")

    # Unknown operator must raise (Literal bound).
    with pytest.raises(ValidationError):
        TargetingRule(attribute="user_id", operator="regex", value="abc")

    # And the Create wrapper accepts a list of properly-shaped rules.
    flag = FeatureFlagCreate(
        key="my_flag",
        targeting_rules=[
            {"attribute": "user_id", "operator": "in",
             "value": ["a", "b"], "return_value": True}
        ],
    )
    assert len(flag.targeting_rules) == 1
    assert flag.targeting_rules[0].attribute == "user_id"


def test_b0_14_variant_is_typed_submodel() -> None:
    """R6-O3-P9: ``variants`` must be ``list[Variant]`` with bounded
    ``name`` (str) + ``weight`` (int 0..100). Smuggling a key the
    evaluator ignores (or a negative weight) must raise."""
    from pydantic import ValidationError

    ns = _exec_template(SCHEMAS_TMPL)
    Variant = ns.get("Variant")
    assert Variant is not None

    Variant(name="control", weight=50)

    # Unknown key must raise (extra=forbid on the sub-model).
    with pytest.raises(ValidationError):
        Variant(name="control", weight=50, payload={"x": 1})

    # Out-of-range weight must raise (ge/le bounds).
    with pytest.raises(ValidationError):
        Variant(name="control", weight=150)
    with pytest.raises(ValidationError):
        Variant(name="control", weight=-1)


def test_b0_14_waiver_removed() -> None:
    """The waiver entry MUST be removed from ``_WAIVED_TOOLS``."""
    from engine.audit.contract_rules.r_write_schemas_strict import (
        _WAIVED_TOOLS,
    )

    assert "add_feature_flags" not in _WAIVED_TOOLS, (
        "B0.14 waiver entry for add_feature_flags was NOT removed; "
        "the schema fix is meaningless if the rule still skips the "
        "template."
    )
