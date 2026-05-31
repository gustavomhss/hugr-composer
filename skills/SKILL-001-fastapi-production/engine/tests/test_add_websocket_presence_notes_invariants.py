"""B0.13 honesty test for ``extend/realtime/add_websocket_presence``.

Closes the B0.13 ``_WAIVED_TOOLS`` entry for this tool. The tool's
``ToolResult(notes=…)`` carries the claim-bearing line::

    "Fan-out via Redis pub/sub — multi-worker safe."

The matched B0.13 claim token is ``"fan-out"``. The honest reading:
the emitted ``PresenceManager`` MUST publish online/offline events
to a Redis pub/sub channel on every transition (the "fan-out" half)
AND MUST store the presence/device state in Redis (not in
per-process memory — the "multi-worker safe" half).

Unlike ``add_websocket_chat``, this tool intentionally does NOT ship
an in-tool subscriber: presence events fan out to *downstream*
consumers (notification services, analytics pipelines, the chat
tool's own presence overlay) that subscribe externally. The claim
is therefore *publish-fan-out* — that other workers' state queries
through Redis see consistent presence — NOT in-tool consumption.

Pair test path: ``engine/tests/test_<tool>_notes_invariants.py`` —
matches ``_PAIR_TEST_PATTERNS[0]``.

What we actually assert
=======================

1. ``test_presence_fan_out_publishes_on_mark_online`` —
   ``mark_online`` MUST call ``self._publish_event(..., "online",
   ...)`` on first-device transitions. Without this, no peer ever
   learns the user came online and the fan-out claim is false.

2. ``test_presence_fan_out_publishes_on_mark_offline`` —
   ``mark_offline`` MUST call ``self._publish_event(..., "offline",
   ...)`` when the last device disconnects. Without this, peers
   never learn the user went offline and the fan-out is one-sided.

3. ``test_presence_fan_out_publish_event_calls_redis_publish`` —
   ``_publish_event`` MUST call ``redis.publish(channel, payload)``.
   A future edit that wrote to a local dict or to a SQL audit table
   would pass the symbol-presence test but break cross-worker
   visibility — pin the Redis call.

4. ``test_presence_multi_worker_safe_state_lives_in_redis`` —
   ``mark_online`` MUST persist the device/presence keys via
   ``redis.sadd`` + ``redis.set`` (the "multi-worker safe" half:
   state must live in shared Redis, not per-process memory). A
   future refactor to in-process dicts would silently break the
   multi-worker claim.

5. ``test_b0_13_waiver_removed`` — the waiver entry MUST be gone
   from ``_WAIVED_TOOLS``.

Bypass surface declared
=======================

* AST-only inspection of ``presence_manager.py.tmpl`` — no Redis,
  no app boot.
* This tool intentionally has no in-tool ``subscribe_loop``;
  asserting one would be wrong (the audit waiver comment said "same
  as add_websocket_chat for presence" but the actual surfaces
  differ — chat needs in-tool subscribers to forward to room
  sockets, presence emits events for *external* downstream
  consumers). The honesty test reflects the actual ship.
* If a future audit adds an "exactly-once" or "ordered" sub-claim
  to the notes line, this test file must grow to anchor it; the
  current ``fan-out`` semantic is at-least-once-fire-and-forget by
  design (Redis pub/sub).
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent.parent
sys.path.insert(0, str(SKILL_ROOT))

TOOL_DIR = SKILL_ROOT / "adapt" / "extend" / "realtime" / "add_websocket_presence"
MANAGER_TMPL = TOOL_DIR / "templates" / "presence_manager.py.tmpl"


# ---------------------------------------------------------------------------
# Placeholder cleanup — the template uses ``${heartbeat_ttl}`` etc. at
# module level which would crash ast.parse otherwise.
# ---------------------------------------------------------------------------

_PLACEHOLDER_BRACED_RE = re.compile(r"\$\{[^}]+\}")
_PLACEHOLDER_BARE_RE = re.compile(r"(?<![A-Za-z0-9_])\$[A-Za-z_][A-Za-z0-9_]*")


def _clean(src: str) -> str:
    src = _PLACEHOLDER_BRACED_RE.sub("60", src)
    src = _PLACEHOLDER_BARE_RE.sub("60", src)
    return src


def _parse(path: Path) -> ast.Module:
    return ast.parse(_clean(path.read_text(encoding="utf-8")))


def _find_class(tree: ast.Module, name: str) -> ast.ClassDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"class {name} not found")


def _find_method(
    cls: ast.ClassDef, name: str
) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for node in ast.walk(cls):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            return node
    raise AssertionError(f"method {name} not found on class {cls.name}")


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
# B0.13 — paired evidence for ``fan-out``.
# ---------------------------------------------------------------------------


def test_presence_fan_out_publishes_on_mark_online() -> None:
    """``mark_online`` MUST call ``self._publish_event(..., "online",
    ...)`` on first-device transitions. Without this, no peer ever
    learns the user came online and the fan-out claim is false.
    """
    tree = _parse(MANAGER_TMPL)
    cls = _find_class(tree, "PresenceManager")
    fn = _find_method(cls, "mark_online")

    found = False
    for call in _calls(fn):
        if not _attr_chain(call).endswith("_publish_event"):
            continue
        for arg in call.args:
            if isinstance(arg, ast.Constant) and arg.value == "online":
                found = True
    assert found, (
        "PresenceManager.mark_online MUST call `self._publish_event("
        "redis, user_id, 'online', device)` on first-device "
        "transitions; without it the fan-out half of the claim is "
        "structurally false."
    )


def test_presence_fan_out_publishes_on_mark_offline() -> None:
    """``mark_offline`` MUST call ``self._publish_event(..., "offline",
    ...)`` when the last device disconnects. Without this, peers
    never learn the user went offline and fan-out is one-sided.
    """
    tree = _parse(MANAGER_TMPL)
    cls = _find_class(tree, "PresenceManager")
    fn = _find_method(cls, "mark_offline")

    found = False
    for call in _calls(fn):
        if not _attr_chain(call).endswith("_publish_event"):
            continue
        for arg in call.args:
            if isinstance(arg, ast.Constant) and arg.value == "offline":
                found = True
    assert found, (
        "PresenceManager.mark_offline MUST call `self._publish_event("
        "redis, user_id, 'offline', device)` when the last device "
        "disconnects; without it offline events never fan out."
    )


def test_presence_fan_out_publish_event_calls_redis_publish() -> None:
    """``_publish_event`` MUST call ``redis.publish(channel, payload)``.
    A future edit that wrote to a local dict or a SQL audit table
    would pass the symbol-presence test but break cross-worker
    visibility.
    """
    tree = _parse(MANAGER_TMPL)
    cls = _find_class(tree, "PresenceManager")
    fn = _find_method(cls, "_publish_event")

    publishes = [
        c for c in _calls(fn) if _attr_chain(c) == "redis.publish"
    ]
    assert publishes, (
        "PresenceManager._publish_event MUST call `redis.publish("
        "channel, payload)`; without it the `fan-out via Redis "
        "pub/sub` claim is structurally false."
    )


def test_presence_multi_worker_safe_state_lives_in_redis() -> None:
    """The "multi-worker safe" half requires presence/device state
    to live in shared Redis (not per-process memory). ``mark_online``
    MUST persist the device set via ``redis.sadd`` AND the presence
    key via ``redis.set``. In-process dicts would silently break
    cross-worker visibility.
    """
    tree = _parse(MANAGER_TMPL)
    cls = _find_class(tree, "PresenceManager")
    fn = _find_method(cls, "mark_online")

    chains = {_attr_chain(c) for c in _calls(fn)}
    assert "redis.sadd" in chains, (
        "PresenceManager.mark_online MUST persist devices via "
        "`redis.sadd(...)`; in-process state would break the "
        "`multi-worker safe` claim."
    )
    assert "redis.set" in chains, (
        "PresenceManager.mark_online MUST persist the presence key "
        "via `redis.set(...)`; in-process state would break the "
        "`multi-worker safe` claim."
    )


def test_b0_13_waiver_removed() -> None:
    """The B0.13 waiver entry for ``add_websocket_presence`` MUST be gone."""
    from engine.audit.contract_rules.r_notes_match_behaviour import (
        _WAIVED_TOOLS,
    )

    assert "extend/realtime/add_websocket_presence" not in _WAIVED_TOOLS, (
        "B0.13 waiver entry for add_websocket_presence was NOT "
        "removed; the pair test is inert while the rule still skips "
        "the tool."
    )
