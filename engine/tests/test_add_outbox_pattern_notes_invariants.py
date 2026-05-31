"""B0.13 honesty test for ``extend/infrastructure/add_outbox_pattern``.

Closes the B0.13 ``_WAIVED_TOOLS`` entry for this tool. The tool's
``ToolResult(notes=…)`` carries the in-line WARNING line::

    "WARNING: AT-LEAST-ONCE delivery — downstream consumers must
    be idempotent."

B0.13's scanner matches the ``"idempotent"`` claim token in that
string and (because the warning is in ``notes=`` rather than
``warnings=``) still demands paired evidence — the rule's bypass
mechanism deliberately does NOT special-case the word "WARNING"
inside a notes line.

The honest reading is: the tool DOES ship a producer-side dedup
mechanism (the ``idempotency_key`` column with a UNIQUE constraint
in both model and migration). When a caller supplies the same key
twice, the second INSERT fails at the DB level and the duplicate
event never lands in the outbox table — that's the structural
backing for the "idempotent" word in the warning.

The downstream consumer responsibility ("consumers must be
idempotent") is the *operator contract* the warning discloses;
this honesty test asserts the *producer-side primitive* that
makes consumer idempotency achievable.

Pair test path: ``engine/tests/test_<tool>_notes_invariants.py``.

What we actually assert
=======================

1. ``test_outbox_event_model_has_idempotent_unique_key`` — the
   emitted ``OutboxEvent`` model declares ``idempotency_key`` with
   ``unique=True``. Without the column-level constraint the
   "idempotent" word in the warning is structurally false (a
   duplicate emit would silently land twice).

2. ``test_outbox_migration_enforces_idempotent_unique_constraint``
   — the Alembic migration declares
   ``sa.UniqueConstraint("idempotency_key")`` on the
   ``outbox_events`` table. The model attribute alone is not load-
   bearing; the DDL must carry the constraint too or production
   never enforces it.

3. ``test_outbox_service_emit_threads_idempotency_key`` — the
   ``OutboxService.emit`` method accepts ``idempotency_key`` and
   passes it into the ``OutboxEvent(...)`` row construction.
   Without this hop the model/migration constraint exists but the
   public emit surface can't reach it.

4. ``test_b0_13_waiver_removed`` — the waiver entry MUST be gone
   from ``_WAIVED_TOOLS``.

Bypass surface declared
=======================

* The test function names contain ``idempotent`` so the fuzzy
  matcher binds them to the ``idempotent`` claim. The waiver
  comment in ``r_notes_match_behaviour.py`` previously said the
  warning "survives the in-line WARNING because the warning is
  also in notes (not warnings=)" — moving the warning to
  ``warnings=`` would also close the gap, but the producer-side
  unique constraint exists and IS the load-bearing backing, so
  closing via paired test is the correct (and stricter) shape.
* AST-only inspection of the templates; no DB exec. The migration
  template carries ``${rev_id}`` / ``${down_rev}`` placeholders
  that the cleanup helper rewrites to identifiers so ``ast.parse``
  succeeds.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent.parent
sys.path.insert(0, str(SKILL_ROOT))

TOOL_DIR = SKILL_ROOT / "adapt" / "extend" / "infrastructure" / "add_outbox_pattern"
MODEL_TMPL = TOOL_DIR / "templates" / "outbox_model.py.tmpl"
MIGRATION_TMPL = TOOL_DIR / "templates" / "migration.py.tmpl"
SERVICE_TMPL = TOOL_DIR / "templates" / "outbox_service.py.tmpl"


# ---------------------------------------------------------------------------
# Placeholder cleanup — migration.py.tmpl carries ${rev_id} / ${down_rev}.
# Rewrite to a bare quoted-string-safe identifier so ast.parse accepts it.
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
# B0.13 — paired evidence for the ``idempotent`` claim.
# ---------------------------------------------------------------------------


def test_outbox_event_model_has_idempotent_unique_key() -> None:
    """Notes warn that consumers must be idempotent — the producer
    backs that with an ``idempotency_key`` column declared
    ``unique=True`` on the ``OutboxEvent`` model. Without the column
    constraint, a duplicate emit with the same key would silently
    land twice and the word `idempotent` in the warning would be
    aspirational.
    """
    tree = _parse(MODEL_TMPL)
    model_cls = _find_class(tree, "OutboxEvent")

    # Find the `idempotency_key: Mapped[...] = mapped_column(...)`
    # assignment.
    idem_col_call: ast.Call | None = None
    for stmt in model_cls.body:
        if isinstance(stmt, ast.AnnAssign):
            target = stmt.target
            if isinstance(target, ast.Name) and target.id == "idempotency_key":
                if isinstance(stmt.value, ast.Call):
                    idem_col_call = stmt.value
    assert idem_col_call is not None, (
        "OutboxEvent MUST declare an `idempotency_key` column; without "
        "it the `idempotent` claim has no producer-side enforcement."
    )

    unique_kwargs = [
        kw
        for kw in idem_col_call.keywords
        if kw.arg == "unique"
        and isinstance(kw.value, ast.Constant)
        and kw.value.value is True
    ]
    assert unique_kwargs, (
        "OutboxEvent.idempotency_key MUST be declared with "
        "`unique=True`; a non-unique column accepts duplicates and "
        "the `idempotent` claim in the warning is structurally false."
    )


def test_outbox_migration_enforces_idempotent_unique_constraint() -> None:
    """The Alembic migration MUST declare
    ``sa.UniqueConstraint("idempotency_key")`` on ``outbox_events``.
    Model-level ``unique=True`` is a hint; production enforcement
    lives in the DDL. Without the migration constraint, deploys
    that bypass the ORM (psql, raw INSERT) can write duplicate
    `idempotency_key` rows and break the consumer-side dedup
    contract.
    """
    tree = _parse(MIGRATION_TMPL)
    upgrade_fn = _find_func(tree, "upgrade")

    unique_calls = [
        c
        for c in _calls(upgrade_fn)
        if _attr_chain(c).endswith("UniqueConstraint")
    ]
    found = False
    for call in unique_calls:
        for arg in call.args:
            if isinstance(arg, ast.Constant) and arg.value == "idempotency_key":
                found = True
                break
    assert found, (
        "migration.py.tmpl upgrade() MUST include "
        "`sa.UniqueConstraint(\"idempotency_key\")` on outbox_events; "
        "without DDL-level enforcement the `idempotent` claim only "
        "holds when callers go through SQLAlchemy."
    )


def test_outbox_service_emit_threads_idempotent_key_to_row() -> None:
    """``OutboxService.emit`` MUST accept ``idempotency_key`` and pass
    it into the ``OutboxEvent(...)`` row construction. Without this
    hop the model/migration constraint exists but the public emit
    surface can't reach it.
    """
    tree = _parse(SERVICE_TMPL)
    cls = _find_class(tree, "OutboxService")
    emit_fn = _find_func(cls, "emit")

    # `idempotency_key` is in the kw-only args.
    kw_arg_names = {a.arg for a in emit_fn.args.kwonlyargs} | {
        a.arg for a in emit_fn.args.args
    }
    assert "idempotency_key" in kw_arg_names, (
        "OutboxService.emit MUST accept an `idempotency_key` parameter "
        "for callers to use the unique-constraint dedup path."
    )

    # And the OutboxEvent(...) call passes it through.
    threaded = False
    for call in _calls(emit_fn):
        if _attr_chain(call).endswith("OutboxEvent"):
            for kw in call.keywords:
                if kw.arg == "idempotency_key":
                    threaded = True
    assert threaded, (
        "OutboxService.emit MUST pass `idempotency_key` into the "
        "`OutboxEvent(...)` row construction; otherwise the unique "
        "constraint never fires and the `idempotent` claim is inert."
    )


def test_b0_13_waiver_removed() -> None:
    """The B0.13 waiver entry for ``add_outbox_pattern`` MUST be gone."""
    from engine.audit.contract_rules.r_notes_match_behaviour import (
        _WAIVED_TOOLS,
    )

    assert "extend/infrastructure/add_outbox_pattern" not in _WAIVED_TOOLS, (
        "B0.13 waiver entry for add_outbox_pattern was NOT removed; "
        "the pair test is inert while the rule still skips the tool."
    )
