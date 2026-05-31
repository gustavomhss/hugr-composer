"""B0.13 honesty test for ``extend/realtime/add_websocket_chat``.

Closes the B0.13 ``_WAIVED_TOOLS`` entry for this tool. The tool's
``ToolResult(notes=…)`` carries the claim-bearing line::

    "WS /ws/chat/{room_id}?token=<JWT> — Redis fan-out, multi-worker safe."

The matched B0.13 claim token is ``"fan-out"``. The honest reading:
the emitted ``WebSocketManager.broadcast`` MUST publish each
message to Redis (the only mechanism that makes it visible to other
workers' subscribe loops) AND ``WebSocketManager.subscribe_loop``
MUST subscribe to the same channel and forward messages to its
local ``WebSocket``. Without BOTH halves the fan-out is one-way (a
worker can publish but its peers never receive) and "multi-worker
safe" is structurally false.

Pair test path: ``engine/tests/test_<tool>_notes_invariants.py`` —
matches ``_PAIR_TEST_PATTERNS[0]``.

What we actually assert
=======================

1. ``test_chat_fan_out_broadcast_calls_redis_publish`` —
   ``WebSocketManager.broadcast`` MUST call ``redis.publish(...)``.
   This is the publish half of the fan-out. A future edit that wrote
   to a process-local set (``self._local[room].add(...)``) would
   pass the symbol-presence test but break the cross-worker claim.

2. ``test_chat_fan_out_subscribe_loop_calls_redis_pubsub_subscribe`` —
   ``WebSocketManager.subscribe_loop`` MUST call
   ``redis.pubsub()`` AND ``pubsub.subscribe(...)``. Without these
   the worker never sees messages other workers published and
   "multi-worker safe" is structurally false.

3. ``test_chat_fan_out_subscribe_loop_forwards_to_websocket`` — the
   subscribe loop MUST call ``ws.send_text(...)`` (or ``send_json``)
   on incoming Redis messages. Without the forward, messages arrive
   in the worker but never reach the connected client — "fan-out" is
   half-real.

4. ``test_chat_fan_out_endpoint_spawns_subscribe_loop`` — the chat
   endpoint MUST create the subscribe task per accepted socket
   (``asyncio.create_task(manager.subscribe_loop(...))``). Without
   this, the loop method exists but is never run — the
   "multi-worker safe" half collapses.

5. ``test_b0_13_waiver_removed`` — the waiver entry MUST be gone
   from ``_WAIVED_TOOLS``.

Bypass surface declared
=======================

* AST-only inspection of two templates. No app boot, no Redis.
* "Multi-worker safe" is asserted via the structural shape (publish +
  subscribe through Redis); ordering / delivery guarantees of Redis
  pub/sub are out of scope (and notes line 56-57 already discloses
  "WebSocket fan-out does not guarantee delivery — Redis pub/sub is
  fire-and-forget" in the module/function docstrings).
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent.parent
sys.path.insert(0, str(SKILL_ROOT))

TOOL_DIR = SKILL_ROOT / "adapt" / "extend" / "realtime" / "add_websocket_chat"
MANAGER_TMPL = TOOL_DIR / "templates" / "connection_manager.py.tmpl"
ENDPOINT_TMPL = TOOL_DIR / "templates" / "chat_endpoint.py.tmpl"


# ---------------------------------------------------------------------------
# Placeholder cleanup — parity with sibling pair-test modules.
# ---------------------------------------------------------------------------

_PLACEHOLDER_BRACED_RE = re.compile(r"\$\{[^}]+\}")
_PLACEHOLDER_BARE_RE = re.compile(r"(?<![A-Za-z0-9_])\$[A-Za-z_][A-Za-z0-9_]*")


def _clean(src: str) -> str:
    src = _PLACEHOLDER_BRACED_RE.sub("PLACEHOLDER", src)
    src = _PLACEHOLDER_BARE_RE.sub("PLACEHOLDER", src)
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


def test_chat_fan_out_broadcast_calls_redis_publish() -> None:
    """``WebSocketManager.broadcast`` MUST call ``redis.publish(...)``.
    This is the publish half of the fan-out; writing to a local
    in-process set would break the cross-worker claim.
    """
    tree = _parse(MANAGER_TMPL)
    cls = _find_class(tree, "WebSocketManager")
    broadcast = _find_method(cls, "broadcast")

    publishes = [
        c for c in _calls(broadcast) if _attr_chain(c).endswith("publish")
    ]
    # Must be on `redis.publish` specifically (not e.g. self.publish).
    publishes_via_redis = [
        c for c in publishes if _attr_chain(c) == "redis.publish"
    ]
    assert publishes_via_redis, (
        "WebSocketManager.broadcast MUST call `redis.publish(channel, "
        "payload)` — this is the publish half of the Redis fan-out. "
        "Without it, peers on other workers never see the message."
    )


def test_chat_fan_out_subscribe_loop_calls_redis_pubsub_subscribe() -> None:
    """``WebSocketManager.subscribe_loop`` MUST call ``redis.pubsub()``
    and ``pubsub.subscribe(channel)`` — without these the worker
    never sees messages published by its peers.
    """
    tree = _parse(MANAGER_TMPL)
    cls = _find_class(tree, "WebSocketManager")
    sub_loop = _find_method(cls, "subscribe_loop")

    has_pubsub = any(
        _attr_chain(c).endswith("pubsub") for c in _calls(sub_loop)
    )
    has_subscribe = any(
        _attr_chain(c).endswith("subscribe") for c in _calls(sub_loop)
    )
    assert has_pubsub and has_subscribe, (
        "WebSocketManager.subscribe_loop MUST call `redis.pubsub()` "
        "and `pubsub.subscribe(channel)` — without both the worker "
        "never receives messages from peers and `multi-worker safe` "
        "is false."
    )


def test_chat_fan_out_subscribe_loop_forwards_to_websocket() -> None:
    """The subscribe loop MUST forward incoming Redis messages to the
    connected WebSocket (``ws.send_text`` or ``ws.send_json``).
    Without the forward, messages arrive in the worker but never
    reach the client — fan-out is half-real.
    """
    tree = _parse(MANAGER_TMPL)
    cls = _find_class(tree, "WebSocketManager")
    sub_loop = _find_method(cls, "subscribe_loop")

    forwards = [
        c
        for c in _calls(sub_loop)
        if _attr_chain(c).endswith("send_text")
        or _attr_chain(c).endswith("send_json")
        or _attr_chain(c).endswith("send_bytes")
    ]
    assert forwards, (
        "subscribe_loop MUST call `ws.send_text(...)` (or send_json / "
        "send_bytes) on incoming pubsub messages; otherwise messages "
        "arrive in the worker but never reach the client."
    )


def test_chat_fan_out_endpoint_spawns_subscribe_loop() -> None:
    """The chat endpoint MUST spawn the subscribe loop per socket
    (``asyncio.create_task(manager.subscribe_loop(...))``). Without
    this, the loop method exists but is never run.
    """
    tree = _parse(ENDPOINT_TMPL)

    found = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _attr_chain(node) not in {
            "asyncio.create_task",
            "create_task",
        }:
            continue
        # The argument MUST be a Call whose chain ends with subscribe_loop.
        for arg in node.args:
            if (
                isinstance(arg, ast.Call)
                and _attr_chain(arg).endswith("subscribe_loop")
            ):
                found = True
    assert found, (
        "The chat endpoint MUST spawn `asyncio.create_task("
        "manager.subscribe_loop(...))` per accepted socket; otherwise "
        "the subscribe loop is defined but never started and the "
        "`fan-out` claim is half-real."
    )


def test_b0_13_waiver_removed() -> None:
    """The B0.13 waiver entry for ``add_websocket_chat`` MUST be gone."""
    from engine.audit.contract_rules.r_notes_match_behaviour import (
        _WAIVED_TOOLS,
    )

    assert "extend/realtime/add_websocket_chat" not in _WAIVED_TOOLS, (
        "B0.13 waiver entry for add_websocket_chat was NOT removed; "
        "the pair test is inert while the rule still skips the tool."
    )
