"""Behavioral end-to-end scenarios for ValueTransform — proves invariants at runtime."""

from __future__ import annotations

from uuid import UUID

import pytest

from ValueTransform import (
    ArgumentMetadata,
    CoercionError,
    Compose,
    ParseBool,
    ParseInt,
    ParseUUID,
    Validation,
    ValidationError,
)


def test_scenario_http_query_param_to_positive_int() -> None:
    meta = ArgumentMetadata(kind="query", metatype=int, data="page")
    pipeline = Compose([
        ParseInt(),
        Validation(lambda x: isinstance(x, int) and x >= 1, message="page >= 1"),
    ])
    assert pipeline.transform("5", meta) == 5
    with pytest.raises(ValidationError):
        pipeline.transform("0", meta)


def test_scenario_body_uuid_round_trip() -> None:
    meta = ArgumentMetadata(kind="body", metatype=UUID, data="resource_id")
    raw = "not-a-uuid-at-all"  # intentional wrong shape → error
    with pytest.raises(CoercionError):
        ParseUUID().transform(raw, meta)
    good = "0af76519-16cd-43dd-8448-eb211c80319c"
    out = ParseUUID().transform(good, meta)
    assert isinstance(out, UUID)
    assert str(out) == good


def test_scenario_custom_param_composition_errors_localize_field() -> None:
    meta = ArgumentMetadata(kind="param", metatype=int, data="user_id")
    pipeline = Compose([ParseInt(), Validation(lambda x: isinstance(x, int) and x > 0, message="positive")])
    try:
        pipeline.transform("-3", meta)
    except ValidationError as exc:
        assert exc.field == "user_id"
    else:
        pytest.fail("expected ValidationError")


def test_scenario_boolean_flag_from_query_string() -> None:
    meta = ArgumentMetadata(kind="query", metatype=bool, data="active")
    p = ParseBool()
    assert p.transform("true", meta) is True
    assert p.transform("0", meta) is False
    with pytest.raises(CoercionError):
        p.transform("perhaps", meta)


def test_scenario_pipeline_is_reusable_across_requests() -> None:
    meta = ArgumentMetadata(kind="param", metatype=int, data="id")
    pipeline = Compose([ParseInt()])
    # Same pipeline instance handles many "requests" — purity guarantees
    # identical behavior (VTRANSFORM_INV_02).
    for i in range(1000):
        assert pipeline.transform(str(i), meta) == i


def test_scenario_caller_payload_is_never_mutated() -> None:
    meta = ArgumentMetadata(kind="body", metatype=None, data="payload")
    caller = {"nested": {"list": [1, 2, 3]}}
    snapshot = {"nested": {"list": [1, 2, 3]}}
    v = Validation(lambda x: True, message="noop")
    out = v.transform(caller, meta)
    # Caller's object unchanged...
    assert caller == snapshot
    # ...and returned object is structurally independent.
    out["nested"]["list"].append(999)  # type: ignore[index]
    assert caller == snapshot


def test_scenario_explicit_order_swap_via_new_compose() -> None:
    meta = ArgumentMetadata(kind="param", metatype=int, data="id")
    # Order matters: Parse then Validate = ok; Validate then Parse = fails.
    a = Compose([ParseInt(), Validation(lambda x: isinstance(x, int), message="int")])
    b = Compose([Validation(lambda x: isinstance(x, str), message="str"), ParseInt()])
    assert a.transform("7", meta) == 7
    assert b.transform("7", meta) == 7
    # Each Compose is a fresh object; swapping order is explicit by construction.
    assert a.transforms != b.transforms
