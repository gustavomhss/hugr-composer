"""Behavioral end-to-end scenarios for ConfigBinding — proves invariants at runtime."""

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
class DbOpts:
    url: str
    pool: int = 10
    ssl: bool = False


@dataclasses.dataclass(frozen=True)
class ApiOpts:
    base_url: str
    timeout_s: float = 5.0


class _FakeVault:
    def __init__(self, store: dict[str, str]) -> None:
        self._store = dict(store)

    def get(self, key: str) -> str:
        return self._store[key]


def test_scenario_boot_binds_db_from_env() -> None:
    binder = from_env_and_file(env={
        "DB__URL": "postgres://prod/app",
        "DB__POOL": "25",
        "DB__SSL": "true",
    })
    db = binder.bind("db", DbOpts)
    assert db.url == "postgres://prod/app"
    assert db.pool == 25
    assert db.ssl is True


def test_scenario_missing_required_fails_fast_at_boot() -> None:
    # Boot-time bind of required config with no source must fail BEFORE any
    # downstream component is constructed.
    binder = from_env_and_file(env={})
    with pytest.raises(ConfigBindingError, match="CONFIG-INV-01"):
        binder.bind("db", DbOpts)


def test_scenario_env_overrides_file_but_file_fills_gaps() -> None:
    binder = from_env_and_file(
        env={"API__BASE_URL": "https://override"},
        dotenv={"API__BASE_URL": "https://default", "API__TIMEOUT_S": "9.5"},
    )
    api = binder.bind("api", ApiOpts)
    assert api.base_url == "https://override"
    assert api.timeout_s == 9.5


def test_scenario_unknown_keys_surface_as_boot_errors() -> None:
    binder = from_env_and_file(env={
        "DB__URL": "x",
        "DB__TYPO_URL": "oops",  # typo that must not be silently dropped
    })
    with pytest.raises(ConfigBindingError, match="typo_url"):
        binder.bind("db", DbOpts)


def test_scenario_secret_from_vault_participates_in_bind() -> None:
    vault = _FakeVault({"prod/db/url": "postgres://secrets/app"})
    secrets = SecretsProvider(
        vault,
        prefix_to_keys={"db": {"url": "prod/db/url"}},
        pinned=True,
    )
    # Vault is pinned and FIRST; env supplies pool only.
    binder = StrictConfigBinder([secrets, EnvProvider({"DB__POOL": "40"}, pinned=False)])
    db = binder.bind("db", DbOpts)
    assert db.url == "postgres://secrets/app"
    assert db.pool == 40


def test_scenario_reload_yields_fresh_record_no_aliasing() -> None:
    binder = from_env_and_file(env={"DB__URL": "u1", "DB__POOL": "5"})
    first = binder.bind("db", DbOpts)
    binder.reload()
    second = binder.current("db", DbOpts)
    assert second is not None
    assert second is not first
    assert second == first
    with pytest.raises(dataclasses.FrozenInstanceError):
        first.pool = 999  # type: ignore[misc]


def test_scenario_provider_ordering_is_operator_pinning() -> None:
    # Operator pins env; attacker-controlled file cannot clobber.
    env_prov = EnvProvider({"DB__URL": "operator-pinned"}, pinned=True)
    file_prov = DotEnvProvider({"DB__URL": "attacker-file"})
    binder = StrictConfigBinder([env_prov, file_prov])
    assert binder.bind("db", DbOpts).url == "operator-pinned"
