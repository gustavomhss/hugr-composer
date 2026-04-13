"""Tests for TOOL-046 add_event_driven.

Run with::

    PYTHONPATH=. pytest adapt/evolve/test_add_event_driven.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/evolve/test_add_event_driven.py
"""

from __future__ import annotations

import ast
import sys
import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.evolve.add_event_driven import add_event_driven


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project(tmp: Path) -> Path:
    """Create a minimal FastAPI project for testing.

    Args:
        tmp: Parent temp directory.

    Returns:
        Path to project root.
    """
    project = tmp / "event_proj"
    project.mkdir(parents=True, exist_ok=True)
    app_dir = project / "app"
    app_dir.mkdir()
    (app_dir / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n"
    )
    (app_dir / "models").mkdir()
    return project


def _assert_parse(path: Path) -> None:
    src = path.read_text()
    try:
        ast.parse(src)
    except SyntaxError as exc:
        raise AssertionError(f"SyntaxError in {path}: {exc}") from exc


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_success_status() -> None:
    """T-01: Tool returns status='success' on fresh project."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = add_event_driven(ToolInput(project_dir=str(project)))
        assert result.status == "success", f"Expected success: {result.error}"


def test_invalid_broker_returns_error() -> None:
    """T-02: Invalid broker must return status='error'."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = add_event_driven(ToolInput(project_dir=str(project)), broker="rabbit_mq")
        assert result.status == "error"
        assert "rabbit_mq" in result.error


def test_base_event_created() -> None:
    """T-03: events/base.py must be created with BaseEvent class."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_event_driven(ToolInput(project_dir=str(project)))
        base = project / "events" / "base.py"
        assert base.exists(), "events/base.py not created"
        assert "BaseEvent" in base.read_text()


def test_base_event_parses() -> None:
    """T-04: events/base.py must be valid Python."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_event_driven(ToolInput(project_dir=str(project)))
        _assert_parse(project / "events" / "base.py")


def test_outbox_model_created() -> None:
    """T-05: app/models/outbox_event.py must be created."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_event_driven(ToolInput(project_dir=str(project)), generate_producer=True)
        outbox = project / "app" / "models" / "outbox_event.py"
        assert outbox.exists(), "outbox_event.py not created"
        assert "OutboxEvent" in outbox.read_text()


def test_outbox_model_parses() -> None:
    """T-06: outbox_event.py must be valid Python."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_event_driven(ToolInput(project_dir=str(project)))
        _assert_parse(project / "app" / "models" / "outbox_event.py")


def test_outbox_worker_created() -> None:
    """T-07: events/outbox_worker.py must be created."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_event_driven(ToolInput(project_dir=str(project)), generate_producer=True)
        worker = project / "events" / "outbox_worker.py"
        assert worker.exists()


def test_outbox_worker_parses() -> None:
    """T-08: outbox_worker.py must be valid Python."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_event_driven(ToolInput(project_dir=str(project)))
        _assert_parse(project / "events" / "outbox_worker.py")


def test_consumer_created() -> None:
    """T-09: events/consumer.py must be created when generate_consumer=True."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_event_driven(ToolInput(project_dir=str(project)), generate_consumer=True)
        consumer = project / "events" / "consumer.py"
        assert consumer.exists()


def test_consumer_parses() -> None:
    """T-10: consumer.py must be valid Python."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_event_driven(ToolInput(project_dir=str(project)))
        _assert_parse(project / "events" / "consumer.py")


def test_retry_engine_created() -> None:
    """T-11: events/retry_engine.py must be created."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_event_driven(ToolInput(project_dir=str(project)))
        retry = project / "events" / "retry_engine.py"
        assert retry.exists()
        assert "retry_with_backoff" in retry.read_text()


def test_retry_engine_parses() -> None:
    """T-12: retry_engine.py must be valid Python."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_event_driven(ToolInput(project_dir=str(project)))
        _assert_parse(project / "events" / "retry_engine.py")


def test_idempotency_module_created() -> None:
    """T-13: events/idempotency.py must be created."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_event_driven(ToolInput(project_dir=str(project)))
        idempotency = project / "events" / "idempotency.py"
        assert idempotency.exists()
        assert "is_seen" in idempotency.read_text()


def test_idempotency_module_parses() -> None:
    """T-14: idempotency.py must be valid Python."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_event_driven(ToolInput(project_dir=str(project)))
        _assert_parse(project / "events" / "idempotency.py")


def test_dlq_module_created() -> None:
    """T-15: events/dlq.py must be created."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_event_driven(ToolInput(project_dir=str(project)))
        dlq = project / "events" / "dlq.py"
        assert dlq.exists()
        assert "send_to_dlq" in dlq.read_text()


def test_dlq_module_parses() -> None:
    """T-16: dlq.py must be valid Python."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_event_driven(ToolInput(project_dir=str(project)))
        _assert_parse(project / "events" / "dlq.py")


def test_event_schemas_created_for_each_event() -> None:
    """T-17: Per-event schema files must be created."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_event_driven(
            ToolInput(project_dir=str(project)),
            events=["OrderCreated", "UserDeleted"],
        )
        schemas_dir = project / "events" / "schemas"
        assert (schemas_dir / "order_created.py").exists()
        assert (schemas_dir / "user_deleted.py").exists()


def test_event_schema_parses() -> None:
    """T-18: Event schema files must be valid Python."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_event_driven(
            ToolInput(project_dir=str(project)),
            events=["OrderCreated"],
        )
        _assert_parse(project / "events" / "schemas" / "order_created.py")


def test_idempotency_returns_no_op() -> None:
    """T-19: Second run must return status='no_op'."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_event_driven(ToolInput(project_dir=str(project)))
        result2 = add_event_driven(ToolInput(project_dir=str(project)))
        assert result2.status == "no_op"


def test_dry_run_creates_no_files() -> None:
    """T-20: dry_run=True must not write any files."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = add_event_driven(
            ToolInput(project_dir=str(project), dry_run=True)
        )
        assert result.status == "success"
        assert result.files_created == []
        assert not (project / "events" / "base.py").exists()


def test_kafka_broker_accepted() -> None:
    """T-21: kafka broker must be accepted."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = add_event_driven(ToolInput(project_dir=str(project)), broker="kafka")
        assert result.status == "success"


def test_nats_broker_accepted() -> None:
    """T-22: nats broker must be accepted."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = add_event_driven(
            ToolInput(project_dir=str(project)), broker="nats"
        )
        # nats is also a valid broker; may succeed or return no_op
        assert result.status in ("success", "no_op")


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_functions = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for fn in test_functions:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {fn.__name__}: {exc}")
            failed += 1
    total = passed + failed
    print(f"\n{passed}/{total} passed", "OK" if failed == 0 else f"({failed} FAILED)")
    sys.exit(0 if failed == 0 else 1)
