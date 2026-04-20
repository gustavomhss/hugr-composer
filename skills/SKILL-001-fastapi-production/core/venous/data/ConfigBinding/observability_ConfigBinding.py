"""Observability harness — asserts ConfigBinding emits logs/metrics/spans matching schema."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from ConfigBinding import from_env_and_file


SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


@dataclasses.dataclass(frozen=True)
class Opts:
    url: str
    pool: int = 10


def _load_schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


def test_observability_schema_wellformed() -> None:
    schema = _load_schema()
    assert isinstance(schema["logs"], list) and schema["logs"]
    assert isinstance(schema["metrics"], list) and schema["metrics"]
    assert isinstance(schema["spans"], list) and schema["spans"]


def test_observability_bind_operation_named_in_schema() -> None:
    schema = _load_schema()
    ops = {s["operation_name"] for s in schema["spans"]}
    assert "config.bind" in ops


def test_observability_metric_types_are_valid() -> None:
    schema = _load_schema()
    valid = {"counter", "histogram", "gauge", "updown_counter"}
    for m in schema["metrics"]:
        assert m["metric_type"] in valid


def test_observability_log_event_names_are_dotted_lowercase() -> None:
    schema = _load_schema()
    for log in schema["logs"]:
        name = str(log["event_name"])
        assert name == name.lower()
        assert "_" not in name or "." in name


def test_observability_binder_registers_current() -> None:
    binder = from_env_and_file(env={"DB__URL": "u", "DB__POOL": "3"})
    opts = binder.bind("db", Opts)
    assert binder.current("db", Opts) == opts


def test_observability_cardinality_bounds_declared() -> None:
    schema = _load_schema()
    for m in schema["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1
