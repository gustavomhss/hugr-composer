"""`fastapi_realtime` — the realtime-domain tree dispatcher.

ONE MCP tool that routes to 5 slice tool(s) + 12 primitive(s) under the `realtime` domain. The Claude agent chooses granularity by `action`.

See `mcp_tools/tree/auth.py` — the canonical POC template this file mirrors.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any

SKILL_ROOT = Path(__file__).resolve().parents[2]
VENOUS_DIR = SKILL_ROOT / "core" / "venous" / "events"
ADAPTERS_FASTAPI = SKILL_ROOT / "core" / "venous" / "_adapters" / "fastapi"


# ---------------------------------------------------------------------------
# Tree declaration — single source of truth for the realtime domain surface
# ---------------------------------------------------------------------------

SLICES: dict[str, dict[str, Any]] = {
    "add_sse": {
        "mod": "add_sse",
        "pkg": "adapt.extend.realtime",
        "desc": "Add Server-Sent Events (SSE) endpoints for real-time push to browser clients",
    },
    "add_webhook_receiver": {
        "mod": "add_webhook_receiver",
        "pkg": "adapt.extend.realtime",
        "desc": "Copy SignatureVerifier+IdempotentConsumer+AuditEvent primitives and the WebhookReceiverAdapt...",
    },
    "add_webhook_sender": {
        "mod": "add_webhook_sender",
        "pkg": "adapt.extend.realtime",
        "desc": "Add outbound webhook delivery system with retry, signature, and delivery log",
    },
    "add_websocket_chat": {
        "mod": "add_websocket_chat",
        "pkg": "adapt.extend.realtime",
        "desc": "Add production-grade WebSocket chat with JWT auth, Redis pub/sub, rooms, and message history",
    },
    "add_websocket_presence": {
        "mod": "add_websocket_presence",
        "pkg": "adapt.extend.realtime",
        "desc": "Add production-grade WebSocket presence tracking with JWT auth, Redis pub/sub, heartbeat TTL...",
    },
}

PRIMITIVES: dict[str, str] = {
    "CausalReorderBuffer": "Buffer incoming events per (aggregate_id, sequence), drain in strict causal order, and emit...",
    "DeadLetterRoute": "Named destination where undeliverable or repeatedly failed messages are routed after the red...",
    "DomainEvent": "Record an immutable fact about something meaningful that happened in the domain and publish...",
    "EventEnvelope": "Frozen, validated dataclass that captures the CloudEvents 1.0.2 canonical shape and makes ro...",
    "EventSourcedStore": "Persist aggregate state as an ordered sequence of domain events and reconstruct current stat...",
    "EventStream": "Ordered, append-only log of events partitioned by key and replayable from any offset by any...",
    "IdempotentConsumer": "Apply a message's effect at most once per logical key while tolerating at-least-once deliver...",
    "InboxDeduplicator": "Record processed message identifiers in the consumer's database so redelivered messages are...",
    "SagaOrchestrator": "Coordinate a multi-step business transaction across services by driving each step and trigge...",
    "StreamSubject": "Shared type for hierarchical subject names and pattern matching so routing, filtering, and a...",
    "TopicBus": "Publish and subscribe facade over a broker topic that delivers CloudEvents at least once to...",
    "TransactionalOutbox": "Store outgoing messages in the same local transaction as the state change so a relay can pub...",
}

# Curated 'bundle' — 5 canonical realtime slices.
# Rationale: Full realtime stack: WebSocket chat+presence, SSE push, and webhook receiver+sender with verification and delivery guarantees.
BUNDLE_SLICES: tuple[str, ...] = (
    "add_websocket_chat",
    "add_websocket_presence",
    "add_sse",
    "add_webhook_receiver",
    "add_webhook_sender",
)


# ---------------------------------------------------------------------------
# Shared envelope (same shape as tier-1 meta tools)
# ---------------------------------------------------------------------------


def _envelope(*, ok: bool, what: str, result: Any, next_steps: list[str], t0: float) -> dict:
    return {
        "ok": ok,
        "what_happened": what,
        "result": result,
        "next_steps": next_steps[:5],
        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
    }


# ---------------------------------------------------------------------------
# Slice routing
# ---------------------------------------------------------------------------


def _call_slice(slice_name: str, **kwargs) -> dict:
    """Route to the underlying `<pkg>.<mod>` tool.

    Multi-bucket aware: each SLICES entry carries its own `pkg`
    because realtime tools span multiple adapt/ subtrees. Routes through
    the shared `dispatch_via_toolinput` helper (Codex 3 F-001).
    """
    from mcp_tools._tree_dispatch import dispatch_via_toolinput

    meta = SLICES[slice_name]
    return dispatch_via_toolinput(
        module_path=f"{meta['pkg']}.{meta['mod']}",
        entry_name=meta["mod"],
        slice_name=slice_name,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Primitive routing
# ---------------------------------------------------------------------------


def _is_non_empty(p: Path) -> bool:
    """Return True if *p* exists, is a directory, and has at least one child."""
    return p.is_dir() and any(p.iterdir())


def _copy_primitive(name: str, output_dir: str, *, force: bool = False) -> dict:
    """Copy core/venous/events/<Name>/ into <output_dir>/core/venous/events/<Name>/.

    Follows ADR 0002 (copy-in distribution). Skips _t0_report.json +
    _evidence/ (per .gitignore). Also copies the matching fastapi
    adapter under _adapters/fastapi/ if one exists.

    F-002 (Codex 3): default non-destructive. Pass ``force=True`` to
    overwrite an existing populated target.
    F-003 (Codex 3): target layout matches the generator + compose
    import path (``core/venous/<ns>/<Name>/<Name>.py``).
    """
    if name not in PRIMITIVES:
        raise ValueError(
            f"unknown primitive {name!r} in domain realtime. Available: {sorted(PRIMITIVES)}"
        )
    src = VENOUS_DIR / name
    if not src.is_dir():
        raise FileNotFoundError(f"primitive source missing: {src}")
    target = Path(output_dir) / "core" / "venous" / "events" / name
    warnings: list[str] = []
    if _is_non_empty(target) and not force:
        return {
            "primitive": name,
            "status": "skipped",
            "reason": (
                f"target exists and is non-empty: {target.relative_to(output_dir)}. "
                "Pass params={'force': True} to overwrite (destructive)."
            ),
            "files_created": [],
            "target": str(target.relative_to(output_dir)),
        }
    if target.exists() and force:
        warnings.append(
            f"force=True: removed existing {target.relative_to(output_dir)} "
            "before copy (user customisations lost)."
        )
        shutil.rmtree(target)
    shutil.copytree(
        src,
        target,
        ignore=shutil.ignore_patterns(
            "__pycache__",
            "_t0_report.json",
            "_evidence",
            "*.pyc",
        ),
    )
    files_created = sorted(str(p.relative_to(output_dir)) for p in target.rglob("*") if p.is_file())
    adapter_name = f"{name}Adapter.py"
    adapter_src = ADAPTERS_FASTAPI / adapter_name
    if adapter_src.exists():
        adapter_target = Path(output_dir) / "core" / "venous" / "_adapters" / "fastapi"
        adapter_target.mkdir(parents=True, exist_ok=True)
        shutil.copy(adapter_src, adapter_target / adapter_name)
        files_created.append(str((adapter_target / adapter_name).relative_to(output_dir)))
        test_src = ADAPTERS_FASTAPI / f"test_{adapter_name}"
        if test_src.exists():
            shutil.copy(test_src, adapter_target / f"test_{adapter_name}")
            files_created.append(
                str((adapter_target / f"test_{adapter_name}").relative_to(output_dir))
            )
    result = {
        "primitive": name,
        "status": "copied",
        "files_created": files_created,
        "target": str(target.relative_to(output_dir)),
    }
    if warnings:
        result["warnings"] = warnings
    return result


# ---------------------------------------------------------------------------
# Top-level dispatcher
# ---------------------------------------------------------------------------

MCP_TOOL = {
    "name": "fastapi_realtime",
    "description": (
        "Realtime domain dispatcher (HuGR tree pattern). ONE tool that routes to every realtime-related capability the kit ships. Choose granularity via `action`:\n  • 'list' → returns the full realtime tree + primitive catalog.\n  • 'bundle' → one-shot: installs 5 curated realtime slices (add_websocket_chat, add_websocket_presence, add_sse, add_webhook_receiver, add_webhook_sender).\n  • '<slice>' → install ONE slice (add_sse, add_webhook_receiver, add_webhook_sender, add_websocket_chat, add_websocket_presence).\n  • 'primitive' → copy ONE Lego block (CausalReorderBuffer, DeadLetterRoute, DomainEvent, EventEnvelope, EventSourcedStore, EventStream, IdempotentConsumer, InboxDeduplicator, SagaOrchestrator, StreamSubject, TopicBus, TransactionalOutbox).\nCall with action='list' if unsure. Every return carries `next_steps`."
    ),
    "tags": ["realtime", "domain", "dispatcher"],
    "annotations": {"readOnlyHint": False, "destructiveHint": False},
    "entry": "fastapi_realtime",
}


def fastapi_realtime(action: str, params: dict | None = None) -> dict:
    """See MCP_TOOL description.

    Signature note: `params` is a polymorphic dict whose expected keys
    depend on `action`. FastMCP doesn't support **kwargs in tool
    signatures, so a single `params` dict is the uniform contract.
    """
    t0 = time.perf_counter()
    params = params or {}

    if action == "list":
        return _envelope(
            ok=True,
            what="realtime domain tree (5 bundle + 5 slices + 12 primitives)",
            result={
                "domain": "realtime",
                "bundle": {
                    "description": (
                        "Install the curated production realtime stack: "
                        f"{len(BUNDLE_SLICES)} slices composed in order."
                    ),
                    "slices_installed": list(BUNDLE_SLICES),
                    "required_params": {"output_dir": "str"},
                },
                "slices": {
                    name: {"description": meta["desc"]} for name, meta in sorted(SLICES.items())
                },
                "primitives": {
                    name: {"purpose": purpose} for name, purpose in sorted(PRIMITIVES.items())
                },
                "usage_examples": [
                    "fastapi_realtime(action='bundle', params={'output_dir':'/tmp/my-app'})",
                    "fastapi_realtime(action='add_websocket_chat', params={'output_dir':'/tmp/my-app'})",
                    "fastapi_realtime(action='primitive', params={'name':'CausalReorderBuffer','output_dir':'/tmp/my-app'})",
                ],
            },
            next_steps=[
                "action='bundle' → install everything for a new project.",
                "action='<slice>' → install one slice for an existing project.",
                "action='primitive' + name=X → copy one Lego surgically.",
            ],
            t0=t0,
        )

    if action == "bundle":
        output_dir = params.get("output_dir")
        if not output_dir:
            return _envelope(
                ok=False,
                what="bundle requires output_dir",
                result={},
                next_steps=["Pass params={'output_dir':'/path/to/project'}."],
                t0=t0,
            )
        installed: list[dict] = []
        errors: list[str] = []
        for slice_name in BUNDLE_SLICES:
            try:
                res = _call_slice(slice_name, **{**params, "output_dir": output_dir})
                installed.append({"slice": slice_name, "result": res})
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{slice_name}: {exc}")
        ok = not errors
        return _envelope(
            ok=ok,
            what=f"bundle: {len(installed)}/{len(BUNDLE_SLICES)} slices installed"
            + (f"; {len(errors)} failure(s)" if errors else ""),
            result={"installed": installed, "errors": errors},
            next_steps=(
                [
                    "Bundle complete. Boot the app and exercise the new endpoints.",
                    "For remaining slices, call action=<slice> individually.",
                    "Call fastapi_meta_audit() to verify the contract.",
                ]
                if ok
                else ["Fix errors above. Retry failing slices individually via action=<slice>."]
            ),
            t0=t0,
        )

    if action == "primitive":
        name = params.get("name")
        output_dir = params.get("output_dir")
        force = bool(params.get("force", False))
        if not name or not output_dir:
            return _envelope(
                ok=False,
                what="primitive action requires name + output_dir",
                result={},
                next_steps=[
                    "Example: fastapi_realtime(action='primitive', params={'name':'X','output_dir':'/tmp/app'}).",
                    "Call fastapi_realtime(action='list') to see available primitive names.",
                ],
                t0=t0,
            )
        try:
            res = _copy_primitive(name, output_dir, force=force)
        except (ValueError, FileNotFoundError) as exc:
            return _envelope(
                ok=False,
                what=str(exc),
                result={},
                next_steps=["Call fastapi_realtime(action='list') for valid primitive names."],
                t0=t0,
            )
        skipped = res.get("status") == "skipped"
        return _envelope(
            ok=True,
            what=(
                f"primitive {name} skipped (target exists; pass force=True)"
                if skipped
                else f"primitive {name} copied into {output_dir}"
            ),
            result=res,
            next_steps=(
                [
                    res["reason"],
                    "Re-run with params={'force': True} to overwrite the existing target.",
                ]
                if skipped
                else [
                    f"Import in your handler: from core.venous.events.{name}.{name} import {name}",
                    f"Call fastapi_meta_describe(name='{name}') for Protocol + invariants.",
                ]
            ),
            t0=t0,
        )

    if action in SLICES:
        output_dir = params.get("output_dir")
        if not output_dir:
            return _envelope(
                ok=False,
                what=f"slice {action!r} requires output_dir in params",
                result={},
                next_steps=["Pass params={'output_dir':'/path/to/project', ...}."],
                t0=t0,
            )
        try:
            res = _call_slice(action, **params)
        except Exception as exc:  # noqa: BLE001
            return _envelope(
                ok=False,
                what=f"slice {action!r} failed: {exc}",
                result={},
                next_steps=[
                    f"Check params for {action!r}. "
                    f"Call fastapi_meta_describe(name='fastapi_{SLICES[action]['mod']}') for the schema."
                ],
                t0=t0,
            )
        return _envelope(
            ok=True,
            what=f"slice {action} installed",
            result=res if isinstance(res, dict) else {"raw": repr(res)[:500]},
            next_steps=[
                "Boot the emitted app + hit the new endpoints to verify.",
                "Additional features? call fastapi_realtime(action='list') for more slices.",
            ],
            t0=t0,
        )

    valid = ["list", "bundle", "primitive"] + sorted(SLICES)
    return _envelope(
        ok=False,
        what=f"unknown action {action!r}",
        result={"valid_actions": valid},
        next_steps=[
            "Call fastapi_realtime(action='list') to see the full tree.",
            f"Did you mean one of: {', '.join(valid[:5])}, ...?",
        ],
        t0=t0,
    )
