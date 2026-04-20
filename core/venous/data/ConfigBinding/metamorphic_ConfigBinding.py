"""Metamorphic + differential tests for ConfigBinding.

Algebraic properties:
- idempotency of bind() under a stable provider snapshot
- reload() is a fixed point over unchanged providers (equal values, distinct identity)
- precedence is associative: (env pinned, file) and (env pinned, file1, file2) agree
  on keys that env supplies
- coercion round-trips for str/int/float/bool literals
"""

from __future__ import annotations

import dataclasses

from ConfigBinding import (
    DotEnvProvider,
    EnvProvider,
    StrictConfigBinder,
    from_env_and_file,
)


@dataclasses.dataclass(frozen=True)
class Opts:
    url: str
    pool: int = 10
    ratio: float = 1.0
    on: bool = False


def test_metamorphic_bind_is_idempotent_under_stable_providers() -> None:
    binder = from_env_and_file(env={"X__URL": "u", "X__POOL": "3"})
    a = binder.bind("x", Opts)
    b = binder.bind("x", Opts)
    c = binder.bind("x", Opts)
    assert a == b == c


def test_metamorphic_reload_equals_rebind() -> None:
    binder = from_env_and_file(env={"X__URL": "u", "X__POOL": "7"})
    first = binder.bind("x", Opts)
    binder.reload()
    after = binder.current("x", Opts)
    assert after is not None
    assert after == first
    assert after is not first


def test_metamorphic_pinned_env_dominates_any_suffix() -> None:
    env_prov = EnvProvider({"X__URL": "env"}, pinned=True)
    base = StrictConfigBinder([env_prov]).bind("x", Opts)
    extended = StrictConfigBinder(
        [env_prov, DotEnvProvider({"X__URL": "file"})]
    ).bind("x", Opts)
    more_extended = StrictConfigBinder(
        [env_prov, DotEnvProvider({"X__URL": "file1"}), DotEnvProvider({"X__URL": "file2"})]
    ).bind("x", Opts)
    assert base.url == extended.url == more_extended.url == "env"


def test_differential_coercion_matches_python_literals() -> None:
    binder = from_env_and_file(env={
        "X__URL": "u",
        "X__POOL": "42",
        "X__RATIO": "3.14",
        "X__ON": "yes",
    })
    opts = binder.bind("x", Opts)
    assert opts.pool == 42
    assert opts.ratio == 3.14
    assert opts.on is True


def test_metamorphic_bool_literals_roundtrip() -> None:
    for truthy in ("1", "true", "True", "YES", "on", "y", "t"):
        binder = from_env_and_file(env={"X__URL": "u", "X__ON": truthy})
        assert binder.bind("x", Opts).on is True
    for falsy in ("0", "false", "no", "off", "n", "f"):
        binder = from_env_and_file(env={"X__URL": "u", "X__ON": falsy})
        assert binder.bind("x", Opts).on is False


def test_metamorphic_prefix_isolation() -> None:
    # Binding one prefix MUST NOT observe keys of another prefix.
    binder = from_env_and_file(env={
        "DB__URL": "db-url",
        "API__URL": "api-url",
    })

    @dataclasses.dataclass(frozen=True)
    class Small:
        url: str

    assert binder.bind("db", Small).url == "db-url"
    assert binder.bind("api", Small).url == "api-url"
