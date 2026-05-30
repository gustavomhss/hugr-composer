"""B0.13 — ``notes_match_emitted_behaviour`` regression suite.

Maps 1:1 to the rule body in
``engine/audit/contract_rules/r_notes_match_behaviour.py``.

Four red / green axes:

1. **Red** — synthetic tool with a claim-token in notes, no escape
   phrase, no pair test → rule flags it.
2. **Green (waived)** — same offender, tool key in ``_WAIVED_TOOLS``
   → rule skips.
3. **Green (paired test exists)** — same offender + pair test file
   under ``engine/tests/test_<tool>_notes_invariants.py`` with a
   ``def test_*`` referencing the claim → rule passes.
4. **Green (escape phrase)** — same notes content with one of the
   four escape phrases injected → rule passes.

Plus axis-coverage tests on ``extract_notes_strings``,
``find_claim_tokens``, ``_note_has_escape``, and the indirect
``ToolResult(notes=_NAME)`` ↦ module-constant resolution.

Convention: all reds/greens use synthetic in-memory sources first; the
catalog-scan integration test points the rule at a ``tmp_path`` tree
so the live catalog is never mutated.

Run::

    PYTHONPATH=. pytest engine/tests/test_notes_match_behaviour_rule.py -v
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent.parent
sys.path.insert(0, str(SKILL_ROOT))

from engine.audit.contract_rules import r_notes_match_behaviour as M  # noqa: E402


def _src(body: str) -> str:
    return textwrap.dedent(body).lstrip("\n")


# ---------------------------------------------------------------------------
# extract_notes_strings — both direct-list and indirect-constant shapes
# ---------------------------------------------------------------------------


def test_extract_direct_list_literal() -> None:
    """``ToolResult(notes=["…"])`` is collected."""
    src = _src('''
        from adapt.contracts import ToolResult

        def go():
            return ToolResult(status="success", notes=["a signed payload"])
    ''')
    out = M.extract_notes_strings(src)
    assert [n for _, n in out] == ["a signed payload"]


def test_extract_indirect_module_constant() -> None:
    """``ToolResult(notes=_NOTES)`` follows the module-level constant."""
    src = _src('''
        from adapt.contracts import ToolResult

        _NOTES = [
            "claim 1: idempotent retries",
            "claim 2: verified webhook",
        ]

        def go():
            return ToolResult(status="success", notes=_NOTES)
    ''')
    out = M.extract_notes_strings(src)
    assert {n for _, n in out} == {
        "claim 1: idempotent retries",
        "claim 2: verified webhook",
    }


def test_extract_ignores_warnings_kwarg() -> None:
    """``warnings=`` strings are the disclosure surface — never scanned."""
    src = _src('''
        from adapt.contracts import ToolResult

        def go():
            return ToolResult(
                status="success",
                notes=["clean note"],
                warnings=["this is signed but not actually verified"],
            )
    ''')
    out = M.extract_notes_strings(src)
    assert [n for _, n in out] == ["clean note"]


def test_extract_ignores_next_steps_kwarg() -> None:
    """``next_steps=`` is operator TODOs — not claims, not scanned."""
    src = _src('''
        from adapt.contracts import ToolResult

        def go():
            return ToolResult(
                status="success",
                notes=["ok"],
                next_steps=["run signed deploy script"],
            )
    ''')
    out = M.extract_notes_strings(src)
    assert [n for _, n in out] == ["ok"]


def test_extract_unparseable_source_returns_empty() -> None:
    """Unparseable __init__.py returns [] — does not crash."""
    assert M.extract_notes_strings("def broken(:\n  pass") == []


# ---------------------------------------------------------------------------
# find_claim_tokens + _note_has_escape — classifier units
# ---------------------------------------------------------------------------


def test_claim_token_case_insensitive() -> None:
    """Token matching is case-insensitive."""
    assert "idempotent" in M.find_claim_tokens("Idempotent dedup applied.")
    assert "signed" in M.find_claim_tokens("SIGNED request enforced.")


def test_claim_token_multiword() -> None:
    """Multi-word tokens like ``"never trusts"`` match as substring."""
    note = "MIME validation uses magic bytes — never trusts Content-Type header."
    assert "never trusts" in M.find_claim_tokens(note)


def test_no_claim_returns_empty() -> None:
    """A note with no claim token returns []."""
    assert M.find_claim_tokens("plain prose with no marketing.") == []


def test_escape_only_when() -> None:
    assert M._note_has_escape("idempotent only when DEDUP_ENABLED=true")


def test_escape_requires_manual() -> None:
    assert M._note_has_escape("signed payload (requires manual key rotation)")


def test_escape_see_next_steps() -> None:
    assert M._note_has_escape("verified — see next_steps for opt-in flag")


def test_escape_unicode_warning_sigil() -> None:
    assert M._note_has_escape("⚠ append-only ledger not enforced at DB level")


def test_no_escape_when_phrase_absent() -> None:
    assert not M._note_has_escape("signed and idempotent — production ready")


# ---------------------------------------------------------------------------
# _claim_covered_by_test — fuzzy pair-test matcher
# ---------------------------------------------------------------------------


def test_claim_covered_by_test_name() -> None:
    """Function name containing the claim counts."""
    src = "def test_signed_token_passes_verification():\n    assert True\n"
    assert M._claim_covered_by_test(src, "signed")


def test_claim_covered_by_test_docstring() -> None:
    """Docstring containing the claim counts."""
    src = _src('''
        def test_token_path():
            """Asserts the token is signed and never replay-able."""
            assert True
    ''')
    assert M._claim_covered_by_test(src, "signed")


def test_claim_covered_handles_hyphenated_tokens() -> None:
    """``"append-only"`` matches a function named ``test_append_only_*``."""
    src = "def test_append_only_ledger_rejects_update():\n    assert True\n"
    assert M._claim_covered_by_test(src, "append-only")


def test_claim_not_covered_when_function_unrelated() -> None:
    src = "def test_unrelated_thing():\n    assert True\n"
    assert not M._claim_covered_by_test(src, "signed")


def test_claim_covered_falls_back_to_regex_on_syntax_error() -> None:
    """Broken test source still scans for matching function names."""
    broken = "def test_signed_path(:\n   pass\n"  # SyntaxError on purpose
    assert M._claim_covered_by_test(broken, "signed")


# ---------------------------------------------------------------------------
# Catalog-scan reds / greens with a synthetic adapt tree
# ---------------------------------------------------------------------------


def _make_tool(
    tmp_adapt: Path,
    tool_key: str,
    *,
    init_body: str,
) -> Path:
    """Write a synthetic tool ``__init__.py`` under ``tmp_adapt`` and
    return its path."""
    tool_dir = tmp_adapt.joinpath(*tool_key.split("/"))
    tool_dir.mkdir(parents=True, exist_ok=True)
    init = tool_dir / "__init__.py"
    init.write_text(_src(init_body), encoding="utf-8")
    return init


def _point_rule_at(
    monkeypatch: pytest.MonkeyPatch,
    *,
    adapt_root: Path,
    tests_root: Path,
    waived: frozenset[str] = frozenset(),
) -> None:
    monkeypatch.setattr(M, "ADAPT_ROOT", adapt_root)
    monkeypatch.setattr(M, "TESTS_ROOT", tests_root)
    monkeypatch.setattr(M, "_WAIVED_TOOLS", waived)


CLAIM_INIT = '''
    from adapt.contracts import ToolResult

    _NOTES_SUCCESS = [
        "Webhook is signed and verified on every replay.",
    ]

    def add_thing(inp):
        return ToolResult(status="success", notes=_NOTES_SUCCESS)
'''

CLAIM_INIT_WITH_ESCAPE = '''
    from adapt.contracts import ToolResult

    _NOTES_SUCCESS = [
        "Webhook signed only when WEBHOOK_SIGNING_ENABLED=true.",
    ]

    def add_thing(inp):
        return ToolResult(status="success", notes=_NOTES_SUCCESS)
'''

CLEAN_INIT = '''
    from adapt.contracts import ToolResult

    def add_thing(inp):
        return ToolResult(status="success", notes=["plain factual statement"])
'''


def test_catalog_red_unmatched_claim(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Synthetic offender + empty tests dir + empty waiver → REJECT."""
    adapt_root = tmp_path / "adapt"
    tests_root = tmp_path / "tests"
    tests_root.mkdir()
    _make_tool(adapt_root, "extend/sample/add_thing", init_body=CLAIM_INIT)
    _point_rule_at(monkeypatch, adapt_root=adapt_root, tests_root=tests_root)

    ok, msg = M._r_notes_match_emitted_behaviour()
    assert not ok
    assert "extend/sample/add_thing" in msg or "add_thing" in msg
    assert "signed" in msg or "verified" in msg


def test_catalog_green_waived_tool(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Same offender BUT tool key in waiver → PASS."""
    adapt_root = tmp_path / "adapt"
    tests_root = tmp_path / "tests"
    tests_root.mkdir()
    _make_tool(adapt_root, "extend/sample/add_thing", init_body=CLAIM_INIT)
    _point_rule_at(
        monkeypatch,
        adapt_root=adapt_root,
        tests_root=tests_root,
        waived=frozenset({"extend/sample/add_thing"}),
    )

    ok, msg = M._r_notes_match_emitted_behaviour()
    assert ok, msg


def test_catalog_green_paired_test_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Same offender + pair test asserting the claim → PASS."""
    adapt_root = tmp_path / "adapt"
    tests_root = tmp_path / "tests"
    tests_root.mkdir()
    _make_tool(adapt_root, "extend/sample/add_thing", init_body=CLAIM_INIT)
    (tests_root / "test_add_thing_notes_invariants.py").write_text(
        _src('''
            def test_signed_webhook_payload_is_verified_on_replay():
                """Asserts the signed claim against template content."""
                assert True
        '''),
        encoding="utf-8",
    )
    _point_rule_at(monkeypatch, adapt_root=adapt_root, tests_root=tests_root)

    ok, msg = M._r_notes_match_emitted_behaviour()
    assert ok, msg


def test_catalog_green_emitted_test_filename_also_counts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``test_<tool>_emitted.py`` is the second accepted pair name."""
    adapt_root = tmp_path / "adapt"
    tests_root = tmp_path / "tests"
    tests_root.mkdir()
    _make_tool(adapt_root, "extend/sample/add_thing", init_body=CLAIM_INIT)
    (tests_root / "test_add_thing_emitted.py").write_text(
        _src('''
            def test_signed_payload_round_trip():
                assert True

            def test_verified_replay_path():
                assert True
        '''),
        encoding="utf-8",
    )
    _point_rule_at(monkeypatch, adapt_root=adapt_root, tests_root=tests_root)

    ok, msg = M._r_notes_match_emitted_behaviour()
    assert ok, msg


def test_catalog_green_escape_phrase_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Claim token + escape phrase in same note → PASS without pair test."""
    adapt_root = tmp_path / "adapt"
    tests_root = tmp_path / "tests"
    tests_root.mkdir()
    _make_tool(adapt_root, "extend/sample/add_thing", init_body=CLAIM_INIT_WITH_ESCAPE)
    _point_rule_at(monkeypatch, adapt_root=adapt_root, tests_root=tests_root)

    ok, msg = M._r_notes_match_emitted_behaviour()
    assert ok, msg


def test_catalog_green_no_claim_tokens(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Notes with no claim tokens never require pair tests."""
    adapt_root = tmp_path / "adapt"
    tests_root = tmp_path / "tests"
    tests_root.mkdir()
    _make_tool(adapt_root, "extend/sample/add_thing", init_body=CLEAN_INIT)
    _point_rule_at(monkeypatch, adapt_root=adapt_root, tests_root=tests_root)

    ok, msg = M._r_notes_match_emitted_behaviour()
    assert ok, msg


def test_catalog_red_pair_test_exists_but_does_not_cover_claim(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A pair test file with unrelated functions → still REJECT."""
    adapt_root = tmp_path / "adapt"
    tests_root = tmp_path / "tests"
    tests_root.mkdir()
    _make_tool(adapt_root, "extend/sample/add_thing", init_body=CLAIM_INIT)
    (tests_root / "test_add_thing_notes_invariants.py").write_text(
        "def test_something_else():\n    assert True\n",
        encoding="utf-8",
    )
    _point_rule_at(monkeypatch, adapt_root=adapt_root, tests_root=tests_root)

    ok, msg = M._r_notes_match_emitted_behaviour()
    assert not ok
    assert "signed" in msg or "verified" in msg


def test_catalog_red_includes_lineno(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Rejection message cites the offending notes line number."""
    adapt_root = tmp_path / "adapt"
    tests_root = tmp_path / "tests"
    tests_root.mkdir()
    init = _make_tool(adapt_root, "extend/sample/add_thing", init_body=CLAIM_INIT)
    _point_rule_at(monkeypatch, adapt_root=adapt_root, tests_root=tests_root)

    ok, msg = M._r_notes_match_emitted_behaviour()
    assert not ok
    # Path basename should appear in the message.
    assert init.name in msg


# ---------------------------------------------------------------------------
# Tool-key resolution edge cases
# ---------------------------------------------------------------------------


def test_tool_key_for_init_three_segment(tmp_path: Path) -> None:
    adapt = tmp_path / "adapt"
    p = adapt / "extend" / "auth_access" / "add_dpop_tokens" / "__init__.py"
    p.parent.mkdir(parents=True)
    p.write_text("", encoding="utf-8")
    assert (
        M._tool_key_for_init(p, adapt)
        == "extend/auth_access/add_dpop_tokens"
    )


def test_tool_key_for_init_two_segment_verify(tmp_path: Path) -> None:
    """``verify/<tool>/__init__.py`` resolves to two-segment key."""
    adapt = tmp_path / "adapt"
    p = adapt / "verify" / "security_scan" / "__init__.py"
    p.parent.mkdir(parents=True)
    p.write_text("", encoding="utf-8")
    assert M._tool_key_for_init(p, adapt) == "verify/security_scan"


def test_tool_key_for_init_skips_category_init(tmp_path: Path) -> None:
    """Category-level inits (depth < 2 after stripping __init__.py)
    return ``""`` so the scanner skips them."""
    adapt = tmp_path / "adapt"
    p = adapt / "extend" / "__init__.py"
    p.parent.mkdir(parents=True)
    p.write_text("", encoding="utf-8")
    assert M._tool_key_for_init(p, adapt) == ""


# ---------------------------------------------------------------------------
# Integration with the live registry
# ---------------------------------------------------------------------------


def test_b0_13_registered_in_rules_list() -> None:
    """B0.13 appears exactly once in the canonical RULES list."""
    from engine.audit.contract_rules import RULES

    matches = [r for r in RULES if r.item == "B0.13"]
    assert len(matches) == 1
    rule = matches[0]
    assert rule.phase == 0
    assert "notes" in rule.description.lower()
    assert callable(rule.check)


def test_b0_13_callback_against_live_catalog_passes() -> None:
    """The live catalog must satisfy B0.13 with the shipped waiver list."""
    ok, msg = M._r_notes_match_emitted_behaviour()
    assert ok, f"B0.13 unexpectedly red on the live catalog: {msg}"


def test_waiver_list_does_not_drift_unilaterally() -> None:
    """Sanity guard: the shipped waiver set is non-empty (Wave-0.5
    grandfathering) AND every entry is a valid path under ``adapt/``.

    Catches accidental waiver typos (wrong slashes, wrong bundle name)
    that would silently bypass the rule.
    """
    assert len(M._WAIVED_TOOLS) > 0
    for tool_key in M._WAIVED_TOOLS:
        candidate = M.ADAPT_ROOT.joinpath(*tool_key.split("/")) / "__init__.py"
        assert candidate.exists(), f"waiver points at missing tool: {tool_key}"
