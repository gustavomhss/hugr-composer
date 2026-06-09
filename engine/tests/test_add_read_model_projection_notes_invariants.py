"""B0.13 honesty test for ``extend/crud_data/add_read_model_projection``.

The tool's ``ToolResult(notes=…)`` carries the line::

    "Apply is at-least-once + idempotent: an event whose seq is <=
    last_applied is dropped, giving effectively-once (NOT exactly-once)."

B0.13's scanner matches the ``"idempotent"`` claim token in that string and
demands paired evidence — an engine-level test asserting the claim holds
against the shipped behaviour.

The honest reading: the read model is built on the registered
``MaterializedView`` primitive, whose ``apply`` DROPS any event whose ``seq``
is ``<= last_applied_seq``. That dedupe is the structural backing for the word
"idempotent": replaying the same source feed twice applies it once. The
adapter's ``rebuild_from_store`` assigns a strictly-increasing ``seq`` over a
replay, so a second identical replay (seq restarts at 1) lands entirely
``<= last_applied`` and is dropped — re-replay is a no-op.

Pair test path: ``engine/tests/test_<tool>_notes_invariants.py``.

What we actually assert
=======================

1. ``test_materialized_view_apply_is_idempotent_on_replayed_seq`` — the
   MaterializedView ``apply`` drops a re-delivered event (same seq); the row
   is written exactly once. Without this, the "idempotent" word is false.

2. ``test_rebuild_from_store_is_idempotent_on_second_replay`` — the adapter's
   ``rebuild_from_store`` returns ``0`` events applied on a second identical
   replay, proving effectively-once at the wiring level.

Bypass surface declared
=======================

* Test function names contain ``idempotent`` so the fuzzy matcher binds them
  to the ``idempotent`` claim token.
* These import the shipped in-repo primitive + adapter directly (no template
  placeholder cleanup needed — the tool copies these files verbatim).
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent.parent
sys.path.insert(0, str(SKILL_ROOT))


def _build_view():
    from core.venous._adapters.fastapi.MaterializedViewAdapter import make_view

    view = make_view("orders")

    @view.on("created")
    def _on_created(rows, event):  # noqa: ANN001, ANN202
        rows[event["aggregate_id"]] = {"id": event["aggregate_id"], "status": "created"}

    return view


def test_materialized_view_apply_is_idempotent_on_replayed_seq() -> None:
    """An event re-delivered with the same seq is DROPPED (idempotent apply).

    The MaterializedView keeps a monotonic ``last_applied_seq``; a seq that is
    ``<= last_applied`` is a duplicate and never re-applies the handler. This
    is the structural backing for the "idempotent" word in the tool's notes.
    """
    view = _build_view()
    event = {"type": "created", "aggregate_id": "ord-1", "seq": 1, "schema_version": 1}
    view.apply(event)
    assert view.applied_event_count == 1
    # Re-deliver the SAME seq → dropped (at-least-once delivery, idempotent apply).
    view.apply(event)
    assert view.applied_event_count == 1, "duplicate seq must NOT re-apply (idempotent)"
    rows = list(view.query(None))
    assert rows == [{"id": "ord-1", "status": "created"}]


def test_rebuild_from_store_is_idempotent_on_second_replay() -> None:
    """A second identical replay applies ZERO new events (effectively-once).

    ``rebuild_from_store`` numbers events with a strictly-increasing seq over a
    replay; replaying the same store again restarts seq at 1, so every event is
    ``<= last_applied`` and the view drops it — proving the idempotent claim at
    the adapter wiring level.
    """
    from core.venous._adapters.fastapi.MaterializedViewAdapter import rebuild_from_store

    class _FakeStore:
        def load(self, aggregate_id):  # noqa: ANN001, ANN202
            return [{"type": "created"}] if aggregate_id == "ord-1" else []

    view = _build_view()
    store = _FakeStore()
    assert rebuild_from_store(view, store, ["ord-1"]) == 1
    assert rebuild_from_store(view, store, ["ord-1"]) == 0, (
        "second identical replay must apply nothing (idempotent / effectively-once)"
    )


if __name__ == "__main__":
    test_materialized_view_apply_is_idempotent_on_replayed_seq()
    test_rebuild_from_store_is_idempotent_on_second_replay()
    print("PASS")
