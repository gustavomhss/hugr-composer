"""B0.13 honesty test for ``extend/infrastructure/add_cache_layer``.

Closes the B0.13 ``_WAIVED_TOOLS`` entry for this tool. The original
notes line —

    "Invalidation strategy: hybrid TTL + pub/sub fan-out to all workers."

— matched the ``"fan-out"`` and ``"distributed"`` claim tokens but the
template wires a **publish-only** invalidation path: ``invalidation.py``
calls ``redis.publish('cache:invalidation', ...)`` but no subscriber is
emitted anywhere under ``add_cache_layer/templates/``, so other workers
DO NOT drop their local ``KeyValueBucket`` entries on mutation.

The fix in this PR has two halves:

1. **Notes qualified**: the ``"fan-out to all workers"`` line was
   replaced with an honest "publish-only + ⚠ no in-tool subscriber"
   disclosure, and a ``warnings=`` entry now states the per-worker /
   TTL-only convergence reality. The over-claim was the bug — see
   the rule's docstring §"Trade-offs": shipping a vacuous honesty
   test would let the gap regress silently.
2. **This pair test** AST-anchors the qualified claim against the
   actual templates so future drift (e.g. someone deletes the
   ``redis.publish`` call or re-adds the misleading docstring) is
   blocked at audit time.

What we actually assert
=======================

* ``test_invalidate_resource_publishes_distributed_fanout_event`` —
  ``invalidation.py.tmpl::_publish_invalidation`` calls
  ``cache.redis.publish(_INVALIDATION_CHANNEL, ...)``. The token
  ``"distributed"`` appears in the test name so B0.13's fuzzy matcher
  recognises this assertion as covering the qualified "distributed"
  reference in the notes line.
* ``test_no_subscriber_loop_is_wired_in_templates`` — anchors the
  honesty half: NO template under ``add_cache_layer/templates/``
  calls ``pubsub()`` / ``subscribe()`` / ``psubscribe()``. If
  someone adds a subscriber later, this test FAILS and the notes
  block must be re-qualified accordingly (the ⚠ disclosure becomes
  inaccurate the moment a real subscriber lands).
* ``test_invalidation_docstring_does_not_claim_workers_subscribe`` —
  the misleading docstring (pre-fix) said "Workers subscribe to
  ``cache:invalidation`` channel and delete local keys when a
  mutation event arrives". That sentence does not exist in any form
  in the current template; we lock that out by string-asserting the
  template body.
* ``test_primitives_glue_uses_inmemory_variants_not_redis_backed`` —
  the "in-memory variants are per-process only" warning is anchored:
  ``primitives.py.tmpl`` imports ``InMemoryKeyValueBucket``,
  ``InMemorySessionCache``, and ``InMemoryDistributedLock`` (not a
  Redis-backed variant). If a future PR upgrades the defaults to
  the Redis-backed primitives, the warning becomes a lie and this
  test forces the disclosure to be re-written.

We deliberately do NOT execute the templates (they import
``app.cache.core`` / ``app.cache.keys`` which do not exist outside
an emitted project). AST + string inspection is sufficient — the
rule's docstring documents AST-style honesty tests as the supported
shape.

Bypass surface declared (per WP-16 §13)
=======================================

* The "distributed" token is covered by the FIRST test's name; the
  fuzzy matcher does not parse the test body. A future tool that
  adds a NEW unescaped claim token (e.g. ``"hash-chained"``) to the
  notes WILL re-fail the rule until a pair test naming that token
  lands — that's intentional (per-claim coverage is the contract).
* String-asserting the docstring (test 3) is a substring check, not
  a parse — someone could re-introduce the lie via a synonym
  (``"pods listen on"`` instead of ``"workers subscribe to"``) and
  this test would not catch it. That is the same trade-off every
  sibling honesty test makes; mitigated by PR review and the
  primary publish-only structural assertion in test 1.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent.parent
sys.path.insert(0, str(SKILL_ROOT))

TOOL_DIR = (
    SKILL_ROOT
    / "adapt"
    / "extend"
    / "infrastructure"
    / "add_cache_layer"
)
TEMPLATES_DIR = TOOL_DIR / "templates"
INVALIDATION_TMPL = TEMPLATES_DIR / "invalidation.py.tmpl"
PRIMITIVES_TMPL = TEMPLATES_DIR / "primitives.py.tmpl"


# ---------------------------------------------------------------------------
# Placeholder cleanup — symmetrical with the rule scanner; cache
# templates use no ``${name}`` holes but the helper keeps the
# pattern consistent with sibling pair-test modules.
# ---------------------------------------------------------------------------

_PLACEHOLDER_BRACED_RE = re.compile(r"\$\{[^}]+\}")
_PLACEHOLDER_BARE_RE = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*")


def _clean(src: str) -> str:
    src = _PLACEHOLDER_BRACED_RE.sub("PLACEHOLDER", src)
    src = _PLACEHOLDER_BARE_RE.sub("PLACEHOLDER", src)
    return src


def _parse_template(path: Path) -> ast.Module:
    return ast.parse(_clean(path.read_text(encoding="utf-8")))


def _find_func(
    tree: ast.Module, name: str
) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"def {name}(...) not found in template")


def _calls(node: ast.AST) -> list[ast.Call]:
    return [n for n in ast.walk(node) if isinstance(n, ast.Call)]


def _attr_chain(call: ast.Call) -> str:
    parts: list[str] = []
    cur: ast.AST | None = call.func
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    return ".".join(reversed(parts))


# ---------------------------------------------------------------------------
# B0.13 — paired honesty evidence
# ---------------------------------------------------------------------------


def test_invalidate_resource_publishes_distributed_fanout_event() -> None:
    """The (now-qualified) "distributed" / "fan-out" reference in notes is
    anchored: ``invalidation.py.tmpl::_publish_invalidation`` calls
    ``cache.redis.publish(_INVALIDATION_CHANNEL, ...)``.

    This is the half of the claim that is actually true — the
    invalidation EMIT path exists. The complementary "no subscriber"
    honesty assertion lives in the next test; together they pin the
    qualified disclosure shape.
    """
    tree = _parse_template(INVALIDATION_TMPL)
    publisher = _find_func(tree, "_publish_invalidation")

    publish_calls = [
        c for c in _calls(publisher) if _attr_chain(c).endswith("redis.publish")
    ]
    assert publish_calls, (
        "`_publish_invalidation` MUST call `*.redis.publish(...)` — without "
        "this, the qualified notes line about a publish-only Redis pub/sub "
        "emit is structurally false."
    )

    # The first positional arg MUST be the channel constant.
    first_call = publish_calls[0]
    assert len(first_call.args) >= 1, (
        "redis.publish(...) MUST receive a channel as its first positional "
        "arg — without it the emit is malformed."
    )
    channel_arg = first_call.args[0]
    assert (
        isinstance(channel_arg, ast.Name)
        and channel_arg.id == "_INVALIDATION_CHANNEL"
    ) or (
        isinstance(channel_arg, ast.Constant)
        and isinstance(channel_arg.value, str)
        and "cache:invalidation" in channel_arg.value
    ), (
        "redis.publish channel MUST be `_INVALIDATION_CHANNEL` (or the "
        "literal `cache:invalidation`) — drift here would mis-route every "
        "mutation event silently."
    )


def test_no_subscriber_loop_is_wired_in_templates() -> None:
    """The "no in-tool subscriber" half of the qualified claim is real.

    Walk every ``.py.tmpl`` under ``add_cache_layer/templates/`` and
    assert NO file calls ``pubsub()``, ``subscribe(...)``, or
    ``psubscribe(...)``. If a future PR adds a subscriber, this test
    fails and the operator must:

      1. Remove the ⚠ "no in-tool subscriber" qualifier from the
         notes line in ``__init__.py``.
      2. Update the ``warnings=`` entry whose first sentence states
         "the tool emits NO subscriber".
      3. Land a new pair test (probably named
         ``test_*_cross_worker_fanout_subscriber_*``) asserting the
         subscriber's structural shape.

    This pinning is the whole point — silent drift between the
    disclosure and the template would let B0.13's exemption lapse.
    """
    forbidden = ("pubsub(", ".subscribe(", "psubscribe(")
    for tmpl in TEMPLATES_DIR.glob("*.py.tmpl"):
        # Walk the AST and inspect every Call node — that way a
        # docstring (or warning text) that *names* the missing
        # primitive cannot trigger a false positive. We only fail
        # when a real call to one of these methods lands in the
        # template body.
        tree = _parse_template(tmpl)
        for call in _calls(tree):
            name = _attr_chain(call).split(".")[-1]
            for needle in forbidden:
                # Strip trailing "(" from the needle for name match.
                bare = needle.lstrip(".").rstrip("(")
                assert name != bare, (
                    f"{tmpl.name} contains a real call to `{name}(...)` — a "
                    "subscriber loop has been added. Update the "
                    "notes/warnings disclosure to reflect cross-worker "
                    "fan-out and replace this test with a positive "
                    "subscriber-shape assertion."
                )


def test_invalidation_docstring_does_not_claim_workers_subscribe() -> None:
    """The pre-fix module docstring lied: "Workers subscribe to
    ``cache:invalidation`` channel and delete local keys". That
    sentence is gone; pin it out so it cannot regress."""
    body = INVALIDATION_TMPL.read_text(encoding="utf-8")
    # Substring rejection — the rule's substring-match honesty contract.
    assert "Workers subscribe to" not in body, (
        "invalidation.py.tmpl docstring claims subscribers exist; "
        "the tool emits no subscriber. Re-qualify or re-implement."
    )
    assert "all pods see consistent" not in body, (
        "invalidation.py.tmpl docstring promises cross-pod consistency; "
        "TTL expiry is the only convergence mechanism in the box."
    )


def test_primitives_glue_uses_inmemory_variants_not_redis_backed() -> None:
    """Anchor the "in-memory variants are per-process only" warning.

    ``primitives.py.tmpl`` imports the in-memory variants of all three
    cache primitives. If a future PR swaps to the Redis-backed
    implementations, the per-process warning becomes wrong and this
    test forces the disclosure to be re-written before merge.
    """
    src = PRIMITIVES_TMPL.read_text(encoding="utf-8")
    for needle in (
        "InMemoryKeyValueBucket",
        "InMemorySessionCache",
        "InMemoryDistributedLock",
    ):
        assert needle in src, (
            f"primitives.py.tmpl no longer imports `{needle}` — the "
            "in-memory per-process warning may now be inaccurate. "
            "Re-audit the notes/warnings block before removing this "
            "assertion."
        )


def test_b0_13_waiver_removed() -> None:
    """The B0.13 waiver entry MUST be removed from ``_WAIVED_TOOLS``."""
    from engine.audit.contract_rules.r_notes_match_behaviour import (
        _WAIVED_TOOLS,
    )

    assert "extend/infrastructure/add_cache_layer" not in _WAIVED_TOOLS, (
        "B0.13 waiver entry for add_cache_layer was NOT removed; "
        "the pair test is meaningless if the rule still skips the tool."
    )
