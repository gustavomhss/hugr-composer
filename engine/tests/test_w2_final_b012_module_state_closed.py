"""Regression tests for W2 FINAL — close all 4 remaining B0.12 waivers.

Closes the last four ``r_no_module_state`` waivers in one PR using the
proven class-instance wrap pattern (PRs #99, #100, #102, #105, #107).
This test module pins (for each tool):

1. The module-level state container is now a CLASS INSTANCE (not a bare
   ``dict`` / ``list``). The B0.12 AST rule allow-lists class-instance
   singletons; a regression to a bare-dict initialiser would re-open
   the per-worker silent-state class of bug.
2. The tool's ``__init__.py`` ships ``_SINGLE_PROCESS_OK: bool = True``
   AND a ``warnings=`` entry whose body contains the substring
   ``"single-process"`` (case-insensitive) so agents see the
   multi-worker trade-off at compose time.
3. The waiver entry has been removed from
   ``r_no_module_state._WAIVED_TOOLS`` — the structural fix is
   meaningless if the rule still skips the template.

Tools closed (per task brief):

* ``evolve/add_event_driven``        — ``_HANDLERS`` in ``consumer.py.tmpl``
* ``evolve/add_i18n``                — ``_CATALOGS`` in ``babel_translator.py.tmpl``
* ``extend/crud_data/add_data_export``        — ``_MODEL_REGISTRY`` in ``model_registry.py.tmpl``
* ``extend/infrastructure/add_scheduled_tasks`` — ``_JOBS`` in ``cron_jobs.py.tmpl``
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent.parent
sys.path.insert(0, str(SKILL_ROOT))

ADAPT_ROOT = SKILL_ROOT / "adapt"

# ---------------------------------------------------------------------------
# Per-tool fixtures: (tool_key, template_path, container_symbol, init_path)
# ---------------------------------------------------------------------------

TOOLS = {
    "evolve/add_event_driven": {
        "tool_dir": ADAPT_ROOT / "evolve" / "add_event_driven",
        "template": "templates/consumer.py.tmpl",
        "symbol": "_HANDLERS",
    },
    "evolve/add_i18n": {
        "tool_dir": ADAPT_ROOT / "evolve" / "add_i18n",
        "template": "templates/babel_translator.py.tmpl",
        "symbol": "_CATALOGS",
    },
    "extend/crud_data/add_data_export": {
        "tool_dir": ADAPT_ROOT / "extend" / "crud_data" / "add_data_export",
        "template": "templates/model_registry.py.tmpl",
        "symbol": "_MODEL_REGISTRY",
    },
    "extend/infrastructure/add_scheduled_tasks": {
        "tool_dir": ADAPT_ROOT / "extend" / "infrastructure" / "add_scheduled_tasks",
        "template": "templates/cron_jobs.py.tmpl",
        "symbol": "_JOBS",
    },
}


# ---------------------------------------------------------------------------
# Placeholder cleanup — same shape as r_no_module_state uses, so the
# template can be parsed here.
# ---------------------------------------------------------------------------

_PLACEHOLDER_BRACED_RE = re.compile(r"\$\{[^}]+\}")
_PLACEHOLDER_BARE_RE = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*")


def _clean(src: str) -> str:
    src = _PLACEHOLDER_BRACED_RE.sub("PLACEHOLDER", src)
    src = _PLACEHOLDER_BARE_RE.sub("PLACEHOLDER", src)
    return src


# ---------------------------------------------------------------------------
# 1. Each container is a class instance, not a bare dict/list.
#
# We rely on AST inspection rather than exec() because several of these
# templates pull in third-party / project-internal modules (gettext on a
# missing locale dir, ``events.idempotency`` from the emitted project,
# ``sqlalchemy.orm.DeclarativeBase``, ``apscheduler``) that aren't on
# sys.path at engine-test time. The structural assertion is what
# B0.12 actually cares about.
# ---------------------------------------------------------------------------

import ast


def _find_module_top_assignment(tree: ast.Module, name: str) -> ast.Assign | ast.AnnAssign | None:
    """Return the module-top Assign / AnnAssign whose target is *name*."""
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            for tgt in stmt.targets:
                if isinstance(tgt, ast.Name) and tgt.id == name:
                    return stmt
        elif isinstance(stmt, ast.AnnAssign):
            if isinstance(stmt.target, ast.Name) and stmt.target.id == name:
                return stmt
    return None


def _rhs_class_name(stmt: ast.Assign | ast.AnnAssign) -> str | None:
    """If RHS is ``SomeClass()`` (no args / kwargs), return ``"SomeClass"``."""
    value = stmt.value
    if value is None or not isinstance(value, ast.Call):
        return None
    func = value.func
    if isinstance(func, ast.Name):
        return func.id
    return None


def test_event_driven_handlers_is_class_instance() -> None:
    """B0.12: ``_HANDLERS`` must be a class instance, not a bare dict."""
    info = TOOLS["evolve/add_event_driven"]
    tmpl = info["tool_dir"] / info["template"]
    src = _clean(tmpl.read_text(encoding="utf-8"))
    tree = ast.parse(src)
    stmt = _find_module_top_assignment(tree, info["symbol"])
    assert stmt is not None, f"{info['symbol']} must be declared at module top"
    # Reject bare-dict initialiser (the original B0.12 offender shape).
    assert not isinstance(stmt.value, ast.Dict), (
        "_HANDLERS must NOT be a bare dict literal — per-worker split is "
        "the whole reason B0.12 exists. Use a class wrapper "
        "(_HandlerRegistry)."
    )
    cls = _rhs_class_name(stmt)
    assert cls is not None, "_HANDLERS RHS must be a class instantiation"
    assert cls.startswith("_") and "Handler" in cls, (
        f"_HANDLERS must wrap a Handler-style class, got {cls!r}"
    )
    # The class itself must be defined in the same module.
    class_defs = {n.name for n in tree.body if isinstance(n, ast.ClassDef)}
    assert cls in class_defs, f"{cls} must be defined in the same template"


def test_i18n_catalogs_is_class_instance() -> None:
    """B0.12: ``_CATALOGS`` must be a class instance, not a bare dict."""
    info = TOOLS["evolve/add_i18n"]
    tmpl = info["tool_dir"] / info["template"]
    src = _clean(tmpl.read_text(encoding="utf-8"))
    tree = ast.parse(src)
    stmt = _find_module_top_assignment(tree, info["symbol"])
    assert stmt is not None
    assert not isinstance(stmt.value, ast.Dict), (
        "_CATALOGS must NOT be a bare dict — hot-reload visibility "
        "cross-worker is the whole reason B0.12 exists."
    )
    cls = _rhs_class_name(stmt)
    assert cls is not None
    assert cls.startswith("_") and "Catalog" in cls, (
        f"_CATALOGS must wrap a Catalog-style class, got {cls!r}"
    )
    class_defs = {n.name for n in tree.body if isinstance(n, ast.ClassDef)}
    assert cls in class_defs


def test_data_export_model_registry_is_class_instance() -> None:
    """B0.12: ``_MODEL_REGISTRY`` must be a class instance, not a bare dict."""
    info = TOOLS["extend/crud_data/add_data_export"]
    tmpl = info["tool_dir"] / info["template"]
    src = _clean(tmpl.read_text(encoding="utf-8"))
    tree = ast.parse(src)
    stmt = _find_module_top_assignment(tree, info["symbol"])
    assert stmt is not None
    assert not isinstance(stmt.value, ast.Dict), (
        "_MODEL_REGISTRY must NOT be a bare dict — the ARQ export "
        "worker reads it across process boundaries."
    )
    cls = _rhs_class_name(stmt)
    assert cls is not None
    assert cls.startswith("_") and "Registry" in cls, (
        f"_MODEL_REGISTRY must wrap a Registry-style class, got {cls!r}"
    )
    class_defs = {n.name for n in tree.body if isinstance(n, ast.ClassDef)}
    assert cls in class_defs


def test_scheduled_tasks_jobs_is_class_instance() -> None:
    """B0.12: ``_JOBS`` must be a class instance, not a bare list."""
    info = TOOLS["extend/infrastructure/add_scheduled_tasks"]
    tmpl = info["tool_dir"] / info["template"]
    src = _clean(tmpl.read_text(encoding="utf-8"))
    tree = ast.parse(src)
    stmt = _find_module_top_assignment(tree, info["symbol"])
    assert stmt is not None
    assert not isinstance(stmt.value, ast.List), (
        "_JOBS must NOT be a bare list — per-worker registry split "
        "was the documented R6-S5-F5 finding."
    )
    cls = _rhs_class_name(stmt)
    assert cls is not None
    assert cls.startswith("_") and "Jobs" in cls, (
        f"_JOBS must wrap a Jobs-style class, got {cls!r}"
    )
    class_defs = {n.name for n in tree.body if isinstance(n, ast.ClassDef)}
    assert cls in class_defs


# ---------------------------------------------------------------------------
# 2. Each tool's __init__.py ships the B0.12 disclosure signals.
# ---------------------------------------------------------------------------


def _assert_disclosure(tool_key: str) -> None:
    init = TOOLS[tool_key]["tool_dir"] / "__init__.py"
    src = init.read_text(encoding="utf-8")
    assert "_SINGLE_PROCESS_OK: bool = True" in src, (
        f"{tool_key}: _SINGLE_PROCESS_OK = True must be declared at "
        "module top — the B0.12 bypass requires it."
    )
    assert re.search(r"single[- ]process", src, re.IGNORECASE), (
        f"{tool_key}: warnings= must contain the substring 'single-process' "
        "(case-insensitive) so agents see the multi-worker trade-off."
    )
    assert "warnings=" in src, (
        f"{tool_key}: ToolResult must return a warnings= entry, not just notes=."
    )


def test_event_driven_ships_single_process_disclosure() -> None:
    _assert_disclosure("evolve/add_event_driven")


def test_i18n_ships_single_process_disclosure() -> None:
    _assert_disclosure("evolve/add_i18n")


def test_data_export_ships_single_process_disclosure() -> None:
    _assert_disclosure("extend/crud_data/add_data_export")


def test_scheduled_tasks_ships_single_process_disclosure() -> None:
    _assert_disclosure("extend/infrastructure/add_scheduled_tasks")


# ---------------------------------------------------------------------------
# 3. All 4 waiver entries are removed from _WAIVED_TOOLS.
# ---------------------------------------------------------------------------


def test_all_four_waivers_removed_from_rule() -> None:
    """All 4 waivers MUST be gone from ``r_no_module_state._WAIVED_TOOLS``."""
    from engine.audit.contract_rules.r_no_module_state import _WAIVED_TOOLS

    for key in TOOLS:
        assert key not in _WAIVED_TOOLS, (
            f"B0.12 waiver entry for {key} was NOT removed; the structural "
            "fix is meaningless if the rule still skips the template."
        )


def test_waiver_set_is_now_empty() -> None:
    """Post-W2 cascade: the waiver set is now fully drained for B0.12.

    This is the strongest signal that the W2 cascade is done. If a new
    template later re-introduces a bare-dict initialiser, the rule
    rejects it; if a reviewer is tempted to add it back here as a
    waiver, this assertion fails and forces them to either fix the
    template or explicitly drop this regression test (and own that
    decision).
    """
    from engine.audit.contract_rules.r_no_module_state import _WAIVED_TOOLS

    assert _WAIVED_TOOLS == frozenset(), (
        f"Expected an empty B0.12 waiver set after W2 close-out; "
        f"still contains: {sorted(_WAIVED_TOOLS)}"
    )


# ---------------------------------------------------------------------------
# 4. End-to-end: the AST rule itself returns no offenders for these 4
#    templates (defence-in-depth — wires the structural fix to the
#    actual rule callback, not just the symptoms above).
# ---------------------------------------------------------------------------


def test_rule_finds_no_module_state_in_closed_templates() -> None:
    """``find_module_state`` must return [] for every closed template.

    This is the direct equivalent of what ``r_no_module_state`` does in
    contract_check: scan the template, return offender list. Empty list
    = the structural fix worked.
    """
    from engine.audit.contract_rules.r_no_module_state import find_module_state

    for tool_key, info in TOOLS.items():
        tmpl = info["tool_dir"] / info["template"]
        offenders = find_module_state(tmpl.read_text(encoding="utf-8"))
        assert offenders == [], (
            f"{tool_key}: find_module_state still reports offenders for "
            f"{tmpl.relative_to(SKILL_ROOT)}: {offenders!r}. The wrap "
            "is incomplete — at least one symbol is still a bare "
            "mutable container."
        )
