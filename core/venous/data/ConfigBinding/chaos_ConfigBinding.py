"""Chaos / fault-injection for ConfigBinding.

Game-day scenarios: missing vault, partial data, type drift, attacker-controlled
files, oversized input. The binder MUST fail loud at boot — never partial.
"""

from __future__ import annotations

import dataclasses

import pytest

from ConfigBinding import (
    ConfigBindingError,
    DotEnvProvider,
    EnvProvider,
    SecretsProvider,
    StrictConfigBinder,
    from_env_and_file,
)


@dataclasses.dataclass(frozen=True)
class Opts:
    url: str
    pool: int = 10


class _ExplodingVault:
    def get(self, key: str) -> str:
        msg = f"vault network down (key={key})"
        raise RuntimeError(msg)


def test_chaos_vault_outage_surfaces_as_bind_error() -> None:
    provider = SecretsProvider(
        _ExplodingVault(),
        prefix_to_keys={"db": {"url": "prod/db/url"}},
        pinned=True,
    )
    binder = StrictConfigBinder([provider])
    with pytest.raises(ConfigBindingError, match="CONFIG-INV-01"):
        binder.bind("db", Opts)


def test_chaos_malformed_int_fails_loud() -> None:
    binder = from_env_and_file(env={"DB__URL": "x", "DB__POOL": "NaN"})
    with pytest.raises(ConfigBindingError, match="CONFIG-INV-01"):
        binder.bind("db", Opts)


def test_chaos_attacker_file_cannot_override_pinned_env() -> None:
    env_prov = EnvProvider({"DB__URL": "real"}, pinned=True)
    evil = DotEnvProvider({"DB__URL": "evil"})
    binder = StrictConfigBinder([env_prov, evil])
    assert binder.bind("db", Opts).url == "real"


def test_chaos_unknown_key_flood_is_rejected() -> None:
    # An operator ships a prefix with lots of extraneous junk — strict binding
    # lists every unknown and refuses the record.
    env = {"DB__URL": "x"} | {f"DB__EXTRA_{i}": "junk" for i in range(25)}
    binder = from_env_and_file(env=env)
    with pytest.raises(ConfigBindingError, match="CONFIG-INV-04"):
        binder.bind("db", Opts)


def test_chaos_empty_prefix_refused() -> None:
    binder = from_env_and_file(env={"DB__URL": "x"})
    with pytest.raises(ConfigBindingError, match="CONFIG-INV-01"):
        binder.bind("   ", Opts)


def test_chaos_non_frozen_schema_refused() -> None:
    @dataclasses.dataclass
    class Mutable:
        url: str

    binder = from_env_and_file(env={"MUT__URL": "x"})
    with pytest.raises(ConfigBindingError, match="CONFIG-INV-02"):
        binder.bind("mut", Mutable)


def test_chaos_reload_does_not_mutate_handed_out_reference() -> None:
    binder = from_env_and_file(env={"DB__URL": "v1"})
    first = binder.bind("db", Opts)
    binder.reload()
    binder.reload()
    binder.reload()
    assert first.url == "v1"
    with pytest.raises(dataclasses.FrozenInstanceError):
        first.url = "pwned"  # type: ignore[misc]


def test_chaos_oversized_value_tolerated_by_str_type() -> None:
    # str fields accept any length — no coercion panic.
    huge = "x" * 10_000
    binder = from_env_and_file(env={"DB__URL": huge})
    opts = binder.bind("db", Opts)
    assert opts.url == huge
