"""Chaos / fault-injection tests for InputValidator."""

from __future__ import annotations

import threading
from collections.abc import Mapping

import pytest

from InputValidator import (
    MAX_COLLECTION_SIZE,
    MAX_DEPTH,
    SchemaField,
    SchemaModel,
    SchemaValidator,
    ValidationError,
    list_of,
)


class Item(SchemaModel):
    __fields__: Mapping[str, SchemaField] = {
        "id": SchemaField(type_=str, pattern=r"[A-Za-z0-9_\-]+", max_length=32),
    }


class Bag(SchemaModel):
    __fields__: Mapping[str, SchemaField] = {
        "items": SchemaField(type_=list_of(Item), max_length=16),
    }


def _v() -> SchemaValidator:
    return SchemaValidator()


def test_chaos_oversize_collection_rejected_before_iterating_all() -> None:
    # Build a list WAY larger than the hard limit. The validator MUST reject
    # without iterating every element (size check is O(1) on len()).
    giant = [{"id": f"i{n}"} for n in range(MAX_COLLECTION_SIZE + 10)]
    with pytest.raises(ValidationError) as err:
        _v().parse({"items": giant}, Bag)
    assert err.value.reason in ("collection_size_exceeded", "list_max_length_exceeded")


def test_chaos_billion_laughs_like_depth_bomb() -> None:
    # Build depth > MAX_DEPTH; the validator MUST refuse before blowing the stack.
    payload: dict[str, object] = {"leaf": 1}
    for _ in range(MAX_DEPTH * 4):
        payload = {"child": payload}

    inner = type("Inner", (SchemaModel,), {"__fields__": {"leaf": SchemaField(type_=int)}})
    # Construct a nested schema deeper than the depth limit.
    layer: type[SchemaModel] = inner
    for _ in range(MAX_DEPTH * 4):
        layer = type("L", (SchemaModel,), {"__fields__": {"child": SchemaField(type_=layer)}})
    with pytest.raises(ValidationError):
        _v().parse(payload, layer)


def test_chaos_null_byte_injection() -> None:
    with pytest.raises(ValidationError):
        _v().parse({"items": [{"id": "ok\x00evil"}]}, Bag)


def test_chaos_bidi_rtl_override_injection() -> None:
    # U+202E (Right-to-Left Override) in a benign-looking value.
    with pytest.raises(ValidationError):
        _v().parse({"items": [{"id": "file\u202egpj.exe"}]}, Bag)


def test_chaos_sql_injection_rejected_by_pattern() -> None:
    with pytest.raises(ValidationError):
        _v().parse({"items": [{"id": "1' OR '1'='1"}]}, Bag)


def test_chaos_ldap_injection_rejected_by_pattern() -> None:
    with pytest.raises(ValidationError):
        _v().parse({"items": [{"id": "*)(uid=*))(|(uid=*"}]}, Bag)


def test_chaos_shell_injection_rejected_by_pattern() -> None:
    with pytest.raises(ValidationError):
        _v().parse({"items": [{"id": "; rm -rf /"}]}, Bag)


def test_chaos_nosql_operator_injection_rejected() -> None:
    # Mongo-style $ne / $gt payload → pattern forbids $, rejected.
    with pytest.raises(ValidationError):
        _v().parse({"items": [{"id": "$ne"}]}, Bag)


def test_chaos_concurrent_parse_no_state_leak() -> None:
    v = _v()
    outcomes: list[str] = []
    lock = threading.Lock()

    def worker(i: int) -> None:
        if i % 2 == 0:
            item = v.parse({"items": [{"id": f"ok-{i}"}]}, Bag)
            with lock:
                outcomes.append(item.items[0].id if hasattr(item, "items") else "missing")
        else:
            try:
                v.parse({"items": [{"id": "bad space"}]}, Bag)
            except ValidationError:
                with lock:
                    outcomes.append("rejected")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(outcomes) == 40
    # Every odd index rejected, every even index accepted.
    accepted = [o for o in outcomes if o.startswith("ok-")]
    rejected = [o for o in outcomes if o == "rejected"]
    assert len(accepted) == 20
    assert len(rejected) == 20


def test_chaos_nonfinite_float_rejected() -> None:
    class F(SchemaModel):
        __fields__: Mapping[str, SchemaField] = {"x": SchemaField(type_=float)}

    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValidationError):
            _v().parse({"x": bad}, F)


def test_chaos_type_confusion_bool_as_int_rejected() -> None:
    class N(SchemaModel):
        __fields__: Mapping[str, SchemaField] = {"n": SchemaField(type_=int)}

    # Python: isinstance(True, int) is True — a naive validator would accept
    # True as `1`. The primitive MUST reject.
    with pytest.raises(ValidationError):
        _v().parse({"n": True}, N)


def test_chaos_very_long_coerce_string_rejected() -> None:
    class N(SchemaModel):
        __fields__: Mapping[str, SchemaField] = {
            "n": SchemaField(type_=int, allow_coerce=True),
        }

    with pytest.raises(ValidationError):
        _v().parse({"n": "1" * 100}, N)
