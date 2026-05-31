"""B0.13 honesty test for ``extend/realtime/add_webhook_receiver``.

Closes the B0.13 ``_WAIVED_TOOLS`` entry for this tool. The tool's
``ToolResult(notes=…)`` carries the claim-bearing line::

    "Shipped primitives: SignatureVerifier, IdempotentConsumer
     (+ Inbox/Outbox siblings), AuditEvent."

The matched B0.13 claim token is ``"idempotent"``. The honest
reading: the emitted glue MUST wire the
``WebhookReceiverAdapter.install`` entry point AND that adapter MUST
construct an idempotent-consumer instance backed by an
``InboxDeduplicator`` (the primitive that actually enforces
exactly-once *effect* on at-least-once delivery — Kleppmann Ch. 11).

A glue that imported a different adapter, or constructed a consumer
without an inbox, would silently drop the dedup guarantee and the
"idempotent" word in the notes line would be structurally false.

Pair test path: ``engine/tests/test_<tool>_notes_invariants.py`` —
matches ``_PAIR_TEST_PATTERNS[0]``.

What we actually assert
=======================

1. ``test_webhook_receiver_glue_idempotent_install_wires_adapter`` —
   the emitted ``glue.py.tmpl`` MUST import ``install`` from
   ``core.venous._adapters.fastapi.WebhookReceiverAdapter`` AND
   ``install_webhook_receiver(app)`` MUST call it. Without this hop
   the adapter exists in the catalog but never runs.

2. ``test_webhook_receiver_adapter_idempotent_consumer_is_wired_with_inbox``
   — ``WebhookReceiverAdapter.install`` MUST construct the
   consumer with ``inbox=InMemoryInboxDeduplicator(...)``. The
   ``InboxDeduplicator`` is the primitive that records seen event
   ids; constructing the consumer without it (``inbox=None``) raises
   IDC-INV-02 at consumer construction, but a future edit that
   dropped the kwarg silently would defeat the idempotent claim at
   the wiring layer — pin the call shape.

3. ``test_webhook_receiver_adapter_idempotent_consumer_subclasses_base``
   — the consumer wired in ``install`` MUST be a subclass of
   ``BaseIdempotentConsumer`` (the primitive that implements the
   cached-retry semantic per IDC-INV-01). A plain dict + lookup
   would pass the import test but not the invariant — anchor the
   inheritance.

4. ``test_b0_13_waiver_removed`` — the waiver entry MUST be gone
   from ``_WAIVED_TOOLS``.

Bypass surface declared
=======================

* AST-only inspection of the glue template + the adapter source
  (``core/venous/_adapters/fastapi/WebhookReceiverAdapter.py``) — no
  FastAPI app boot, no Redis. The adapter ships as a copied source
  file (not a template), so it's read directly off disk.
* The ``BaseIdempotentConsumer`` semantic itself is asserted by the
  primitive's own test suite under
  ``core/venous/events/IdempotentConsumer/``. This test verifies the
  *wiring* — that the webhook adapter actually uses the
  idempotent-consumer primitive and not a placeholder.
* The "audit-event" + "signature-verifier" siblings named in the
  notes line are NOT verified by this test; they would each anchor a
  separate claim (``tamper-evident`` / ``signed`` respectively) and
  the rule only matches ``idempotent`` here. If a future audit
  expands the claim tokens (e.g. adds ``tamper-evident``), this test
  file must grow to anchor them.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent.parent
sys.path.insert(0, str(SKILL_ROOT))

TOOL_DIR = SKILL_ROOT / "adapt" / "extend" / "realtime" / "add_webhook_receiver"
GLUE_TMPL = TOOL_DIR / "templates" / "glue.py.tmpl"
ADAPTER_PY = (
    SKILL_ROOT
    / "core"
    / "venous"
    / "_adapters"
    / "fastapi"
    / "WebhookReceiverAdapter.py"
)


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


def _find_func(
    tree: ast.AST, name: str
) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            return node
    raise AssertionError(f"def {name}(...) not found")


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
# B0.13 — paired evidence for ``idempotent``.
# ---------------------------------------------------------------------------


def test_webhook_receiver_glue_idempotent_install_wires_adapter() -> None:
    """The emitted ``glue.py.tmpl`` MUST import ``install`` from
    ``core.venous._adapters.fastapi.WebhookReceiverAdapter`` and call
    it inside ``install_webhook_receiver(app)``. Without this hop
    the adapter (and its idempotent consumer) never runs.
    """
    tree = _parse(GLUE_TMPL)

    imports = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    adapter_imports = [
        i
        for i in imports
        if (i.module or "").endswith("WebhookReceiverAdapter")
        and any(a.name == "install" for a in i.names)
    ]
    assert adapter_imports, (
        "glue.py.tmpl MUST import `install` from "
        "`core.venous._adapters.fastapi.WebhookReceiverAdapter`."
    )

    install_fn = _find_func(tree, "install_webhook_receiver")
    delegates = [
        c
        for c in _calls(install_fn)
        if _attr_chain(c) == "install" or _attr_chain(c).endswith(".install")
    ]
    assert delegates, (
        "install_webhook_receiver(app) MUST call the adapter's "
        "`install(...)`; without it the idempotent consumer is never "
        "wired and the `idempotent` claim is structurally false."
    )


def test_webhook_receiver_adapter_idempotent_consumer_is_wired_with_inbox() -> None:
    """``WebhookReceiverAdapter.install`` MUST construct the consumer
    with ``inbox=InMemoryInboxDeduplicator(...)``. The inbox is the
    primitive that records seen X-Event-Ids; without it redeliveries
    re-run the handler and the "idempotent" claim is false.
    """
    tree = _parse(ADAPTER_PY)
    install_fn = _find_func(tree, "install")

    found = False
    for call in _calls(install_fn):
        # Look for a Call whose `inbox=` kwarg is itself a Call to
        # something ending in InMemoryInboxDeduplicator.
        for kw in call.keywords:
            if kw.arg != "inbox":
                continue
            v = kw.value
            if (
                isinstance(v, ast.Call)
                and _attr_chain(v).endswith("InMemoryInboxDeduplicator")
            ):
                found = True
    assert found, (
        "WebhookReceiverAdapter.install MUST pass "
        "`inbox=InMemoryInboxDeduplicator(...)` to the consumer "
        "constructor; without the inbox the consumer cannot dedupe "
        "redeliveries and the `idempotent` claim is structurally false."
    )


def test_webhook_receiver_adapter_idempotent_consumer_subclasses_base() -> None:
    """The consumer wired in ``install`` MUST inherit from
    ``BaseIdempotentConsumer`` — the primitive that implements the
    cached-retry semantic (IDC-INV-01). A plain dict + lookup would
    pass the inbox-wiring test but not the invariant; anchor the
    inheritance.
    """
    tree = _parse(ADAPTER_PY)

    # Find class def(s) inheriting from BaseIdempotentConsumer.
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        and any(
            (isinstance(b, ast.Name) and b.id == "BaseIdempotentConsumer")
            or (isinstance(b, ast.Attribute) and b.attr == "BaseIdempotentConsumer")
            for b in node.bases
        )
    ]
    assert matches, (
        "WebhookReceiverAdapter.py MUST define at least one consumer "
        "class that inherits from `BaseIdempotentConsumer` (the "
        "primitive enforcing IDC-INV-01 cached-retry). Without the "
        "inheritance the `idempotent` claim is structurally false."
    )

    # And that class MUST be the one wired into install() — verify the
    # adapter's install() instantiates it.
    consumer_class_names = {cls.name for cls in matches}
    install_fn = _find_func(tree, "install")
    instantiated = False
    for call in _calls(install_fn):
        # `_EchoAuditConsumer(...)` — Name call.
        if isinstance(call.func, ast.Name) and call.func.id in consumer_class_names:
            instantiated = True
        if isinstance(call.func, ast.Attribute) and call.func.attr in consumer_class_names:
            instantiated = True
    assert instantiated, (
        "WebhookReceiverAdapter.install MUST instantiate a "
        "BaseIdempotentConsumer subclass — defining one without "
        "instantiating it leaves the dedup primitive unwired."
    )


def test_b0_13_waiver_removed() -> None:
    """The B0.13 waiver entry for ``add_webhook_receiver`` MUST be gone."""
    from engine.audit.contract_rules.r_notes_match_behaviour import (
        _WAIVED_TOOLS,
    )

    assert "extend/realtime/add_webhook_receiver" not in _WAIVED_TOOLS, (
        "B0.13 waiver entry for add_webhook_receiver was NOT removed; "
        "the pair test is inert while the rule still skips the tool."
    )
