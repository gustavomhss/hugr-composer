"""Structural tests for the refactored TOOL-079 ``add_event_sourcing``.

CONTRACT §B1.3 refactor: copies EventSourcedStore + DomainEvent primitives
and the FastAPI EventSourcedStoreAdapter into the project, then writes a
≤ 20-line ``app/event_store.py`` caller.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from adapt.contracts import ToolInput
from adapt.extend.crud_data.add_event_sourcing import MCP_TOOL, add_event_sourcing
from tests.common.fixture_factory import create_fixture_project


def _all_py_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _assert_parse(root: Path) -> None:
    for f in _all_py_files(root):
        try:
            ast.parse(f.read_text())
        except SyntaxError as exc:  # pragma: no cover
            raise AssertionError(f"SyntaxError in {f}: {exc}") from exc


def test_success_status() -> None:
    project_dir = create_fixture_project(name="es_t01")
    r = add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    assert r.status == "success", r.error


def test_idempotent() -> None:
    project_dir = create_fixture_project(name="es_t02")
    assert add_event_sourcing(ToolInput(project_dir=str(project_dir))).status == "success"
    r2 = add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op"
    assert not r2.files_created


def test_dry_run_writes_nothing() -> None:
    project_dir = create_fixture_project(name="es_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    r = add_event_sourcing(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert r.status == "success"
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after


def test_primitives_copied_into_project() -> None:
    project_dir = create_fixture_project(name="es_t04")
    add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    ess = project_dir / "core" / "venous" / "events" / "EventSourcedStore" / "EventSourcedStore.py"
    de = project_dir / "core" / "venous" / "events" / "DomainEvent" / "DomainEvent.py"
    assert ess.exists()
    assert de.exists()


def test_adapter_copied_into_project() -> None:
    project_dir = create_fixture_project(name="es_t05")
    add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    adapter = (
        project_dir / "core" / "venous" / "_adapters" / "fastapi" / "EventSourcedStoreAdapter.py"
    )
    assert adapter.exists()
    assert "def install(" in adapter.read_text()


def test_manifest_records_provenance() -> None:
    project_dir = create_fixture_project(name="es_t06")
    add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    manifest = json.loads((project_dir / ".venous_manifest.json").read_text())
    primitives = {p["qualified_name"] for p in manifest["primitives"]}
    adapters = {a["qualified_name"] for a in manifest["adapters"]}
    assert "core.venous.events.EventSourcedStore" in primitives
    assert "core.venous.events.DomainEvent" in primitives
    assert "core.venous._adapters.fastapi.EventSourcedStoreAdapter" in adapters


def test_glue_imports_adapter() -> None:
    project_dir = create_fixture_project(name="es_t07")
    add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    glue = project_dir / "app" / "event_store.py"
    assert glue.exists()
    body = glue.read_text()
    assert "from core.venous._adapters.fastapi.EventSourcedStoreAdapter import install" in body
    assert "def install_event_store" in body


def test_glue_superuser_gates_event_routes() -> None:
    """R5-O2-D6: the /events router must be auth-gated, not anonymous.

    The glue must hand the adapter a superuser auth dependency so reading or
    appending another aggregate's raw event stream over HTTP requires auth.
    """
    project_dir = create_fixture_project(name="es_auth_gate")
    add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    glue = (project_dir / "app" / "event_store.py").read_text()
    assert "from app.api.deps import get_current_superuser" in glue, (
        "glue must import the superuser auth dependency"
    )
    assert "auth_dependency=get_current_superuser" in glue, (
        "install() must receive the superuser auth dependency (R5-O2-D6)"
    )


def test_durable_store_emitted_and_opt_in_wired() -> None:
    """R5-O2-D7: a durable SQL-backed event store ships and is opt-in via config.

    Emits app/event_store_store.py (SqlEventSourcedStore), adds the
    EVENT_STORE_DURABLE config flag (default False = in-memory, no regression),
    and the glue builds the durable store only when that flag is set.
    """
    project_dir = create_fixture_project(name="es_durable_wire")
    add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    store = project_dir / "app" / "event_store_store.py"
    assert store.exists(), "durable store app/event_store_store.py not emitted"
    store_src = store.read_text()
    assert "class SqlEventSourcedStore" in store_src
    assert "with_for_update" in store_src, "append must serialize the tail (with_for_update)"
    assert "ConcurrencyError" in store_src, "durable append must enforce optimistic concurrency"
    config = (project_dir / "app" / "core" / "config.py").read_text()
    assert "EVENT_STORE_DURABLE: bool = False" in config, "durable must default OFF (no regression)"
    glue = (project_dir / "app" / "event_store.py").read_text()
    assert "EVENT_STORE_DURABLE" in glue and "build_durable_event_store" in glue, (
        "glue must build the durable store only when EVENT_STORE_DURABLE is set"
    )


def test_durable_store_persists_and_enforces_concurrency() -> None:
    """R5-O2-D7: the emitted durable store persists events + enforces ESS-INV-01.

    Runs the emitted SqlEventSourcedStore against a real on-disk SQLite DB:
    appends survive a fresh instance (durability) and a stale expected_version
    raises ConcurrencyError without writing.
    """
    import sys
    import tempfile

    from sqlalchemy import create_engine

    project_dir = create_fixture_project(name="es_durable_run")
    add_event_sourcing(ToolInput(project_dir=str(project_dir)))

    _orig = sys.path.copy()
    sys.path.insert(0, str(project_dir))
    for m in [k for k in sys.modules if k in ("app", "core") or k.startswith(("app.", "core."))]:
        del sys.modules[m]
    try:
        from app.event_store_store import SqlEventSourcedStore

        from core.venous.events.EventSourcedStore.EventSourcedStore import ConcurrencyError

        d = tempfile.mkdtemp()
        url = f"sqlite:///{d}/events.db"
        st = SqlEventSourcedStore(create_engine(url))
        assert st.append("agg-1", 0, [{"t": "created"}, {"t": "updated"}]) == 2
        assert [e["t"] for e in st.load("agg-1")] == ["created", "updated"]

        # Optimistic concurrency: a stale expected_version raises, writes nothing.
        try:
            st.append("agg-1", 0, [{"t": "stale"}])
            raise AssertionError("stale append must raise ConcurrencyError")
        except ConcurrencyError as exc:
            assert exc.actual_version == 2
        assert len(list(st.load("agg-1"))) == 2, "rejected append must not write events"

        # Durability: a NEW instance over the same DB sees the prior events.
        st2 = SqlEventSourcedStore(create_engine(url), create=False)
        assert len(list(st2.load("agg-1"))) == 2
        assert st2.append("agg-1", 2, [{"t": "third"}]) == 3
    finally:
        sys.path[:] = _orig


def _build_durable_store(project_dir: Path, db_name: str) -> tuple[Any, Any]:
    """Import the emitted SqlEventSourcedStore over a fresh on-disk SQLite DB."""
    import tempfile

    from sqlalchemy import create_engine

    sys.path.insert(0, str(project_dir))
    for m in [k for k in sys.modules if k in ("app", "core") or k.startswith(("app.", "core."))]:
        del sys.modules[m]
    from app.event_store_store import SqlEventSourcedStore

    from core.venous.events.EventSourcedStore.EventSourcedStore import (
        ConcurrencyError,
        EventSourcedStoreInvariantError,
    )

    d = tempfile.mkdtemp()
    url = f"sqlite:///{d}/{db_name}.db"
    store = SqlEventSourcedStore(create_engine(url))
    errs = SimpleNamespace(
        ConcurrencyError=ConcurrencyError,
        EventSourcedStoreInvariantError=EventSourcedStoreInvariantError,
    )
    return store, errs


def test_durable_store_ports_in_memory_invariants() -> None:
    """R8-J3-1: durable append/snapshot enforce the SAME guards as the reference.

    Red pre-fix: the SQL store skipped empty-id, bool-version, snapshot-ahead,
    and snapshot-rewind guards (ESS-INV-01/03) on the durable path only.
    """
    project_dir = create_fixture_project(name="es_r8j3_inv")
    add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    _orig = sys.path.copy()
    try:
        st, errs = _build_durable_store(project_dir, "inv")
        inv = errs.EventSourcedStoreInvariantError

        # (a) empty aggregate_id rejected.
        try:
            st.append("", 0, [{"t": "x"}])
            raise AssertionError("empty aggregate_id must be rejected")
        except inv:
            pass

        # (b) bool passed as expected_version rejected (bool is an int subclass).
        try:
            st.append("agg-b", True, [{"t": "x"}])
            raise AssertionError("bool expected_version must be rejected")
        except inv:
            pass

        # (c) snapshot whose version out-runs the event log rejected.
        st.append("agg-s", 0, [{"t": "one"}])  # tail = 1
        try:
            st.snapshot("agg-s", 5, {"v": 5})
            raise AssertionError("snapshot ahead of log must be rejected")
        except inv:
            pass

        # (d) snapshot rewind rejected.
        st.append("agg-s", 1, [{"t": "two"}])  # tail = 2
        st.snapshot("agg-s", 2, {"v": 2})
        try:
            st.snapshot("agg-s", 1, {"v": 1})
            raise AssertionError("snapshot rewind must be rejected")
        except inv:
            pass
    finally:
        sys.path[:] = _orig


def test_durable_concurrent_append_collision_maps_to_concurrency_error() -> None:
    """R8-J3-2: a UNIQUE(aggregate_id, version) collision becomes ConcurrencyError.

    Red pre-fix: SQLAlchemy's IntegrityError escaped raw (→ HTTP 500) instead of
    the ConcurrencyError the adapter maps to 409. We reproduce the race window
    deterministically by subclassing the store to return a STALE tail of 0 (as
    if a racer committed version 1 between our optimistic read and our INSERT),
    so the optimistic check passes and the INSERT collides on the UNIQUE
    (aggregate_id, version) backstop.
    """
    from sqlalchemy import create_engine, insert

    project_dir = create_fixture_project(name="es_r8j3_race")
    add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    _orig = sys.path.copy()
    sys.path.insert(0, str(project_dir))
    for m in [k for k in sys.modules if k in ("app", "core") or k.startswith(("app.", "core."))]:
        del sys.modules[m]
    try:
        import tempfile

        from app.event_store_store import SqlEventSourcedStore, event_store_events

        from core.venous.events.EventSourcedStore.EventSourcedStore import ConcurrencyError

        class _StaleTailStore(SqlEventSourcedStore):
            def _locked_tail(self, conn: Any, key: str) -> int:  # noqa: ARG002
                return 0  # pretend the racer's version-1 row is not yet visible

        d = tempfile.mkdtemp()
        engine = create_engine(f"sqlite:///{d}/race.db")
        st = _StaleTailStore(engine)
        # A racer already committed version 1 for this aggregate.
        with engine.begin() as conn:
            conn.execute(
                insert(event_store_events).values(
                    aggregate_id="agg-r", version=1, event={"t": "racer"}
                )
            )
        try:
            st.append("agg-r", 0, [{"t": "ours"}])
            raise AssertionError("collision must raise ConcurrencyError, not IntegrityError")
        except ConcurrencyError as exc:
            assert exc.aggregate_id == "agg-r"
    finally:
        sys.path[:] = _orig


def test_glue_body_under_20_loc() -> None:
    project_dir = create_fixture_project(name="es_t08")
    add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    glue = project_dir / "app" / "event_store.py"
    tree = ast.parse(glue.read_text())
    body_lines = 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.body[0].lineno
            end = node.end_lineno or start
            body_lines += end - start + 1
    assert body_lines <= 20, f"glue body is {body_lines} LoC; budget 20"


def test_all_py_parse_after_two_runs() -> None:
    project_dir = create_fixture_project(name="es_t09")
    add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_mcp_tool_lists_imported_primitives() -> None:
    assert MCP_TOOL["entry"] == "add_event_sourcing"
    assert "core.venous.events.EventSourcedStore" in MCP_TOOL["imports_primitives"]
    assert "core.venous._adapters.fastapi.EventSourcedStoreAdapter" in MCP_TOOL["imports_adapters"]


def test_execution_time_recorded() -> None:
    project_dir = create_fixture_project(name="es_t10")
    r = add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    assert r.execution_time_ms > 0


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for fn in tests:
        try:
            fn()
            passed += 1
            print(f"  PASS  {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  FAIL  {fn.__name__}: {exc}")
    print(f"\n{passed}/{passed + failed} passed")
    sys.exit(0 if not failed else 1)
