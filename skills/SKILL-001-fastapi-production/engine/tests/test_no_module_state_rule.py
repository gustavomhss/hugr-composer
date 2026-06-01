"""B0.12 — ``no_module_state_in_templates`` regression suite.

Maps 1:1 to the rule body in
``engine/audit/contract_rules/r_no_module_state.py``.

Each test exercises one branch of the rule's classifier — the goal is
"explicit reds and explicit greens" so a future refactor that loosens
the AST walk turns one of these tests red instead of silently passing.

Convention: the rule's public helper is
``find_module_state(src: str) -> list[(name, lineno, col, mutations)]``.
Tests pass synthetic Python sources directly — NO disk fixture files —
so the test runs identically inside CI, inside a sandbox, and inside
``pytest --collect-only`` without depending on the catalog scan.

Catalog-scan integration is covered by ``test_b0_12_catalog_scan_runs``
at the bottom: it just asserts the rule callback is callable and the
return shape is ``(bool, str)`` — content is asserted by
``contract_check`` itself.
"""

from __future__ import annotations

import textwrap

import pytest

from engine.audit.contract_rules._common import SKILL_ROOT
from engine.audit.contract_rules.r_no_module_state import (
    _r_no_module_state_in_templates,
    _tool_key_for,
    find_module_state,
)


def _src(body: str) -> str:
    """Dedent + strip trailing newline so test bodies read naturally."""
    return textwrap.dedent(body).lstrip("\n")


# ----------------------------------------------------------------------
# REDS — these should trigger the rule
# ----------------------------------------------------------------------


def test_red_dict_literal_subscript_assign() -> None:
    """``_STORE = {}`` with ``_STORE[k] = v`` in a function → flagged."""
    hits = find_module_state(
        _src("""
        from __future__ import annotations

        _STORE: dict[str, int] = {}

        def remember(k: str, v: int) -> None:
            _STORE[k] = v
    """)
    )
    assert len(hits) == 1
    name, lineno, _col, muts = hits[0]
    assert name == "_STORE"
    assert lineno == 3
    assert muts == [6]


def test_red_list_append() -> None:
    """``_QUEUE = []`` with ``_QUEUE.append(...)`` → flagged."""
    hits = find_module_state(
        _src("""
        _QUEUE: list[int] = []

        def push(x: int) -> None:
            _QUEUE.append(x)
    """)
    )
    assert len(hits) == 1
    assert hits[0][0] == "_QUEUE"


def test_red_set_add() -> None:
    """``_SEEN = set()`` with ``_SEEN.add(x)`` → flagged."""
    hits = find_module_state(
        _src("""
        _SEEN = set()

        def saw(x):
            _SEEN.add(x)
    """)
    )
    assert len(hits) == 1
    assert hits[0][0] == "_SEEN"


def test_red_defaultdict_update() -> None:
    """``defaultdict(list)`` with ``.update()`` → flagged."""
    hits = find_module_state(
        _src("""
        from collections import defaultdict
        _BUCKETS = defaultdict(list)

        def merge(more):
            _BUCKETS.update(more)
    """)
    )
    assert len(hits) == 1
    assert hits[0][0] == "_BUCKETS"


def test_red_dict_call_with_pop() -> None:
    """``_HOTS = dict()`` with ``.pop(k)`` → flagged."""
    hits = find_module_state(
        _src("""
        _HOTS = dict()

        def cool(k):
            _HOTS.pop(k, None)
    """)
    )
    assert len(hits) == 1
    assert hits[0][0] == "_HOTS"


def test_red_global_reassign_inside_function() -> None:
    """Reassign from inside a function (``global X; X = ...``) → flagged."""
    hits = find_module_state(
        _src("""
        _CACHE = {}

        def reset():
            global _CACHE
            _CACHE = {}
    """)
    )
    assert len(hits) == 1
    assert hits[0][0] == "_CACHE"


def test_red_aug_assign_subscript() -> None:
    """``_TOT[k] += 1`` → flagged."""
    hits = find_module_state(
        _src("""
        _TOT = {}

        def tick(k):
            _TOT[k] = _TOT.get(k, 0) + 1
    """)
    )
    assert len(hits) == 1
    assert hits[0][0] == "_TOT"


def test_red_del_subscript() -> None:
    """``del _STORE[k]`` → flagged."""
    hits = find_module_state(
        _src("""
        _STORE = {}

        def drop(k):
            del _STORE[k]
    """)
    )
    assert len(hits) == 1
    assert hits[0][0] == "_STORE"


def test_red_weakvaluedictionary_mutation() -> None:
    """``WeakValueDictionary`` with subscript-store → flagged."""
    hits = find_module_state(
        _src("""
        from weakref import WeakValueDictionary

        _CACHE = WeakValueDictionary()

        def stash(k, v):
            _CACHE[k] = v
    """)
    )
    assert len(hits) == 1
    assert hits[0][0] == "_CACHE"


def test_red_multiple_offenders_all_reported() -> None:
    """When several module-level mutables are mutated, all surface."""
    hits = find_module_state(
        _src("""
        _A = {}
        _B: list[int] = []
        _C = set()

        def go(k, v, x, y):
            _A[k] = v
            _B.append(x)
            _C.add(y)
    """)
    )
    assert {h[0] for h in hits} == {"_A", "_B", "_C"}


# ----------------------------------------------------------------------
# GREENS — these should NOT trigger the rule
# ----------------------------------------------------------------------


def test_green_read_only_constant_dict() -> None:
    """A dict literal NEVER mutated is a constant — allowed."""
    hits = find_module_state(
        _src("""
        _CONFIG = {"timeout": 30, "retries": 3}

        def get_timeout():
            return _CONFIG["timeout"]

        def get_retries():
            return _CONFIG["retries"]
    """)
    )
    assert hits == []


def test_green_read_only_constant_set() -> None:
    """Read-only set used for ``in`` checks — allowed (matches edge case)."""
    hits = find_module_state(
        _src("""
        _FROZEN_PATHS = {"/healthz", "/metrics"}

        def is_health(path):
            return path in _FROZEN_PATHS
    """)
    )
    assert hits == []


def test_green_frozenset_initializer() -> None:
    """``frozenset(...)`` is explicitly immutable — allowed."""
    hits = find_module_state(
        _src("""
        _ALG = frozenset({"ES256", "RS256"})

        def is_allowed(alg):
            return alg in _ALG
    """)
    )
    assert hits == []


def test_green_tuple_initializer() -> None:
    """``tuple(...)`` is immutable — allowed."""
    hits = find_module_state(
        _src("""
        _ITEMS = tuple(["a", "b", "c"])

        def has(x):
            return x in _ITEMS
    """)
    )
    assert hits == []


def test_green_mapping_proxy_type() -> None:
    """``MappingProxyType`` is a read-only view — allowed."""
    hits = find_module_state(
        _src("""
        from types import MappingProxyType

        _RO = MappingProxyType({"a": 1})

        def get(k):
            return _RO[k]
    """)
    )
    assert hits == []


def test_green_threading_lock() -> None:
    """``threading.Lock()`` is allowed (process-internal coordination)."""
    hits = find_module_state(
        _src("""
        import threading

        _LOCK = threading.Lock()

        def critical():
            with _LOCK:
                pass
    """)
    )
    assert hits == []


def test_green_bare_lock_call() -> None:
    """``Lock()`` from-imported is also allowed."""
    hits = find_module_state(
        _src("""
        from threading import Lock, RLock, Event, Semaphore, Condition
        from queue import Queue

        _LOCK = Lock()
        _RLOCK = RLock()
        _EVT = Event()
        _SEM = Semaphore(4)
        _COND = Condition()
        _Q = Queue()
    """)
    )
    assert hits == []


def test_green_contextvar() -> None:
    """``ContextVar`` is per-context — allowed."""
    hits = find_module_state(
        _src("""
        from contextvars import ContextVar

        _TENANT: ContextVar[str | None] = ContextVar("tenant", default=None)

        def get_tenant():
            return _TENANT.get()

        def set_tenant(t):
            _TENANT.set(t)
    """)
    )
    assert hits == []


def test_green_lru_cache_decorator() -> None:
    """``@functools.lru_cache`` targets a function — not module state."""
    hits = find_module_state(
        _src("""
        import functools

        @functools.lru_cache(maxsize=256)
        def expensive(x):
            return x * 2
    """)
    )
    assert hits == []


def test_green_mutation_inside_class_only() -> None:
    """Dict declared inside a class body is class-state — not module-state.

    The rule's candidate scan only collects ``tree.body``-level
    assignments, so an inner-class ``self._cache = {}`` style declaration
    isn't even a candidate.
    """
    hits = find_module_state(
        _src("""
        class Store:
            _data: dict[str, int] = {}

            def put(self, k, v):
                self._data[k] = v
    """)
    )
    assert hits == []


def test_green_mutation_inside_function_only() -> None:
    """A dict CREATED inside a function never escapes module scope."""
    hits = find_module_state(
        _src("""
        def build():
            local = {}
            local["a"] = 1
            return local
    """)
    )
    assert hits == []


def test_green_dunder_skipped() -> None:
    """``__all__ = [...]`` is module-loader scaffolding, not user state."""
    hits = find_module_state(
        _src("""
        __all__ = ["foo", "bar"]

        def foo():
            __all__.append("baz")  # pathological, but skipped by rule

        def bar():
            return None
    """)
    )
    assert hits == []


def test_green_annotated_no_initializer() -> None:
    """Bare type declaration without initializer — allowed."""
    hits = find_module_state(
        _src("""
        x: dict[str, int]
    """)
    )
    assert hits == []


# ----------------------------------------------------------------------
# Waiver behaviour
# ----------------------------------------------------------------------


def test_waiver_skips_listed_tool(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """A tool in ``_WAIVED_TOOLS`` is exempt from the catalog scan.

    Strategy: point ADAPT_ROOT at a temp tree with one offending
    template under ``extend/_waived/synthetic_tool/templates/x.py.tmpl``,
    add that tool key to the waiver set, assert OK.
    """
    from engine.audit.contract_rules import r_no_module_state as mod

    tool_dir = tmp_path / "extend" / "_waived" / "synthetic_tool" / "templates"
    tool_dir.mkdir(parents=True)
    (tool_dir / "state.py.tmpl").write_text(
        _src("""
        _STORE = {}

        def remember(k, v):
            _STORE[k] = v
    """)
    )

    monkeypatch.setattr(mod, "ADAPT_ROOT", tmp_path)
    monkeypatch.setattr(
        mod,
        "_WAIVED_TOOLS",
        frozenset({"extend/_waived/synthetic_tool"}),
    )
    ok, msg = mod._r_no_module_state_in_templates()
    assert ok, msg


def test_unwaived_tool_fails(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Same offender WITHOUT the waiver → rule rejects."""
    from engine.audit.contract_rules import r_no_module_state as mod

    tool_dir = tmp_path / "extend" / "_unwaived" / "tool" / "templates"
    tool_dir.mkdir(parents=True)
    (tool_dir / "state.py.tmpl").write_text(
        _src("""
        _STORE = {}

        def remember(k, v):
            _STORE[k] = v
    """)
    )

    monkeypatch.setattr(mod, "ADAPT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_WAIVED_TOOLS", frozenset())
    ok, msg = mod._r_no_module_state_in_templates()
    assert not ok
    assert "_STORE" in msg
    assert "state.py.tmpl" in msg


# ----------------------------------------------------------------------
# Edge cases — keep these as canaries for the documented allow-list
# ----------------------------------------------------------------------


def test_edge_compose_fragment_skipped() -> None:
    """A non-parseable fragment is silently skipped (NOT crashed on)."""
    # Fragment shape: bare expression on its own line, looks like
    # placeholder leftover. Should return [] not raise.
    src = "sa.Column('id', sa.Integer)\nleftover_token\nsa.Column('x', sa.Text)\n"
    assert find_module_state(src) == []


def test_edge_placeholder_substitution() -> None:
    """``${var}`` / ``$var`` placeholders parse via substitution."""
    src = _src("""
        class ${EventName}V1:
            pass

        $registry_init

        _CACHE = {}
        def remember(k, v):
            _CACHE[k] = v
    """)
    hits = find_module_state(src)
    # The substitution preserves the mutable-state finding.
    assert any(h[0] == "_CACHE" for h in hits)


def test_edge_dict_comprehension_initializer() -> None:
    """``_X = {k: v for ...}`` is a fresh mutable dict — flagged if mutated."""
    hits = find_module_state(
        _src("""
        _X = {k: 0 for k in range(3)}

        def bump(k):
            _X[k] += 1
    """)
    )
    assert len(hits) == 1
    assert hits[0][0] == "_X"


# ----------------------------------------------------------------------
# Integration with the registry
# ----------------------------------------------------------------------


def test_b0_12_registered_in_rules_list() -> None:
    """B0.12 appears in the canonical RULES list with description + phase."""
    from engine.audit.contract_rules import RULES

    matches = [r for r in RULES if r.item == "B0.12"]
    assert len(matches) == 1, "B0.12 must appear exactly once in RULES"
    rule = matches[0]
    assert rule.phase == 0
    assert "module" in rule.description.lower()
    assert callable(rule.check)


def test_b0_12_callback_returns_bool_str_tuple() -> None:
    """Smoke test: the callback against the live catalog returns shape (bool, str).

    Content of the failure message is asserted by ``contract_check`` itself
    on every CI run; here we only guard the call shape.
    """
    result = _r_no_module_state_in_templates()
    assert isinstance(result, tuple)
    assert len(result) == 2
    ok, msg = result
    assert isinstance(ok, bool)
    assert isinstance(msg, str)


def test_tool_key_for_extracts_tool_dir() -> None:
    """Sanity: tool-key derivation maps template paths to waivable keys."""
    p = (
        SKILL_ROOT
        / "adapt"
        / "extend"
        / "auth_access"
        / "add_dpop_tokens"
        / "templates"
        / "dpop_core.py.tmpl"
    )
    assert _tool_key_for(p) == "extend/auth_access/add_dpop_tokens"


# ----------------------------------------------------------------------
# Round-7 O3-F14 (HIGH) — SimpleNamespace + dynamic `type(...)` evasions
# ----------------------------------------------------------------------


def test_red_simplenamespace_wrapper_mutated() -> None:
    """``_X = SimpleNamespace(d={})`` with ``_X.d[k] = v`` evaded the
    rule (SimpleNamespace wasn't in the mutable-call list). After the
    patch the wrapper is a mutable initializer AND attribute-subscript
    mutations on it are detected.
    """
    hits = find_module_state(
        _src("""
        from types import SimpleNamespace

        _X = SimpleNamespace(d={})

        def remember(k, v):
            _X.d[k] = v
    """)
    )
    assert len(hits) == 1, hits
    assert hits[0][0] == "_X"


def test_red_simplenamespace_attribute_assign_mutated() -> None:
    """``_X.attr = v`` on a SimpleNamespace candidate counts as mutation."""
    hits = find_module_state(
        _src("""
        from types import SimpleNamespace

        _X = SimpleNamespace(counter=0)

        def bump():
            _X.counter = _X.counter + 1
    """)
    )
    assert len(hits) == 1, hits
    assert hits[0][0] == "_X"


def test_red_dynamic_type_3arg_with_mutable_body() -> None:
    """``_X = type('X', (), {'d': {}})()`` evaded the rule because
    ``type`` isn't a known mutable callable. After the patch the
    3-arg ``type(...)`` whose body dict carries a mutable value is
    flagged.
    """
    hits = find_module_state(
        _src("""
        _X = type('X', (), {'d': {}})()

        def remember(k, v):
            _X.d[k] = v
    """)
    )
    assert len(hits) == 1, hits
    assert hits[0][0] == "_X"


def test_green_dynamic_type_3arg_empty_body() -> None:
    """A 3-arg ``type('X', (), {})`` with an empty body is dynamic-class
    creation (not state) — allowed even if reassigned.
    """
    hits = find_module_state(
        _src("""
        _Klass = type('X', (), {})

        def use():
            return _Klass()
    """)
    )
    assert hits == []


def test_green_simplenamespace_unmutated_constant() -> None:
    """``SimpleNamespace(...)`` that is NEVER mutated is a read-only
    constant — allowed (mirrors the dict-literal constant policy).
    """
    hits = find_module_state(
        _src("""
        from types import SimpleNamespace

        _CFG = SimpleNamespace(timeout=30, retries=3)

        def get_timeout():
            return _CFG.timeout
    """)
    )
    assert hits == []
