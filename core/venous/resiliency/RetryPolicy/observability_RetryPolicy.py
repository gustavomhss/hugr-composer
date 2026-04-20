"""Observability harness — asserts RetryPolicy's emitted schema is well-formed."""

from __future__ import annotations

import asyncio
import json
import random
from pathlib import Path

from RetryPolicy import ExponentialBackoffRetryPolicy, RetryBudget

SCHEMA_PATH = Path(__file__).parent / "observability_schema.json"


def _load_schema() -> dict[str, list[dict[str, object]]]:
    return json.loads(SCHEMA_PATH.read_text())


async def _no_sleep(_s: float) -> None:
    return None


def test_observability_schema_wellformed() -> None:
    schema = _load_schema()
    assert schema["logs"] and schema["metrics"] and schema["spans"]


def test_observability_metric_types_are_valid() -> None:
    schema = _load_schema()
    valid = {"counter", "histogram", "gauge", "updown_counter"}
    for m in schema["metrics"]:
        assert m["metric_type"] in valid


def test_observability_log_event_names_dotted_lowercase() -> None:
    schema = _load_schema()
    for log in schema["logs"]:
        name = str(log["event_name"])
        assert name == name.lower()
        assert "." in name


def test_observability_cardinality_bounds_declared() -> None:
    schema = _load_schema()
    for m in schema["metrics"]:
        assert isinstance(m["cardinality_bound"], int)
        assert m["cardinality_bound"] >= 1


def test_observability_spans_present() -> None:
    schema = _load_schema()
    ops = {s["operation_name"] for s in schema["spans"]}
    assert "retry.execute" in ops


def test_observability_execute_records_attempts() -> None:
    p = ExponentialBackoffRetryPolicy(
        max_attempts=3,
        initial_interval_ms=1,
        multiplier=2.0,
        max_interval_ms=10,
        jitter=0.0,
        budget_ratio=1.0,
        requires_idempotency=False,
        rng=random.Random(0),
        sleep_fn=_no_sleep,
        budget=RetryBudget(budget_ratio=1.0, min_floor=100),
    )

    calls = {"n": 0}

    async def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 2:
            raise TimeoutError("t")
        return "ok"

    result = asyncio.run(p.execute(flaky))
    assert result == "ok"
    # attempts_log carries structured entries — matches required attributes.
    log = p.attempts_log
    assert len(log) == 2
    assert log[0]["outcome"] == "error:retryable"
    assert log[1]["outcome"] == "success"
