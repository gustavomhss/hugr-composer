"""Unit tests for ConfigBinding — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import dataclasses

import pytest
from ConfigBinding import (
    ConfigBindingError,
    DotEnvProvider,
    EnvProvider,
    StrictConfigBinder,
    from_env_and_file,
)


@dataclasses.dataclass(frozen=True)
class DbOpts:
    url: str
    pool: int = 10


@dataclasses.dataclass(frozen=True)
class CacheOpts:
    host: str
    port: int = 6379
    tls: bool = False


@dataclasses.dataclass
class NotFrozen:
    url: str


# ---------------------------------------------------------------------------
# CONFIG_INV_01 — fail loudly on missing/bad values
# ---------------------------------------------------------------------------
def test_inv_fail_loud_confirms() -> None:
    binder = from_env_and_file(env={"DB__URL": "postgres://x", "DB__POOL": "7"})
    opts = binder.bind("db", DbOpts)
    assert opts.url == "postgres://x"
    assert opts.pool == 7


def test_inv_fail_loud_prevents() -> None:
    # Missing required key → error (NOT a partial record).
    binder = from_env_and_file(env={})
    with pytest.raises(ConfigBindingError, match="CONFIG-INV-01"):
        binder.bind("db", DbOpts)
    # Bad coercion → error.
    bad = from_env_and_file(env={"DB__URL": "x", "DB__POOL": "not-an-int"})
    with pytest.raises(ConfigBindingError, match="CONFIG-INV-01"):
        bad.bind("db", DbOpts)


def test_inv_fail_loud_under_failure() -> None:
    # Empty prefix, non-dataclass schema — both rejected with INV-01.
    binder = from_env_and_file(env={"DB__URL": "x"})
    with pytest.raises(ConfigBindingError, match="CONFIG-INV-01"):
        binder.bind("", DbOpts)
    with pytest.raises(ConfigBindingError, match="CONFIG-INV-01"):
        binder.bind("db", int)  # type: ignore[type-var]


# ---------------------------------------------------------------------------
# CONFIG_INV_02 — frozen/immutable records
# ---------------------------------------------------------------------------
def test_inv_frozen_confirms() -> None:
    binder = from_env_and_file(env={"DB__URL": "u"})
    opts = binder.bind("db", DbOpts)
    with pytest.raises(dataclasses.FrozenInstanceError):
        opts.url = "other"  # type: ignore[misc]


def test_inv_frozen_prevents() -> None:
    # Non-frozen dataclass schema → refused at bind-time.
    binder = from_env_and_file(env={"NOTFROZEN__URL": "x"})
    with pytest.raises(ConfigBindingError, match="CONFIG-INV-02"):
        binder.bind("notfrozen", NotFrozen)


def test_inv_frozen_under_failure() -> None:
    # Even if two consumers bind the same prefix, each gets an independent
    # frozen instance — mutating one cannot affect another (they are frozen
    # AND not identical objects).
    binder = from_env_and_file(env={"DB__URL": "u"})
    a = binder.bind("db", DbOpts)
    b = binder.bind("db", DbOpts)
    assert a == b
    assert a is not b  # fresh record each call
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.pool = 999  # type: ignore[misc]


# ---------------------------------------------------------------------------
# CONFIG_INV_03 — reload produces new record without aliasing
# ---------------------------------------------------------------------------
def test_inv_reload_no_alias_confirms() -> None:
    binder = from_env_and_file(env={"DB__URL": "v1"})
    first = binder.bind("db", DbOpts)
    binder.reload()
    second = binder.current("db", DbOpts)
    assert second is not None
    assert second is not first
    # Value parity: nothing changed in the providers, so equality holds.
    assert second == first


def test_inv_reload_no_alias_prevents() -> None:
    # After a handed-out reference, callers SHALL NOT observe silent mutation.
    binder = from_env_and_file(env={"DB__URL": "v1"})
    first = binder.bind("db", DbOpts)
    binder.reload()
    # First reference is frozen — and reload() did not mutate it in place.
    assert first.url == "v1"
    with pytest.raises(dataclasses.FrozenInstanceError):
        first.url = "hacked"  # type: ignore[misc]


def test_inv_reload_no_alias_under_failure() -> None:
    # If providers change between binds, reload() picks up the change AND
    # the previously handed-out reference stays untouched.
    env = {"DB__URL": "v1"}
    binder = StrictConfigBinder([EnvProvider(env, pinned=True)])
    first = binder.bind("db", DbOpts)
    env["DB__URL"] = "v2"
    # Existing EnvProvider holds a SNAPSHOT — so reload with same provider
    # keeps v1. Callers wanting a fresh read must rebuild providers.
    binder.reload()
    second = binder.current("db", DbOpts)
    assert first.url == "v1"
    assert second is not None
    assert second is not first


# ---------------------------------------------------------------------------
# CONFIG_INV_04 — unknown keys are errors
# ---------------------------------------------------------------------------
def test_inv_strict_unknown_confirms() -> None:
    binder = from_env_and_file(env={"DB__URL": "u", "DB__GARBAGE": "x"})
    with pytest.raises(ConfigBindingError, match="CONFIG-INV-04"):
        binder.bind("db", DbOpts)


def test_inv_strict_unknown_prevents() -> None:
    # Only declared keys succeed.
    binder = from_env_and_file(env={"CACHE__HOST": "h", "CACHE__PORT": "1", "CACHE__TLS": "yes"})
    opts = binder.bind("cache", CacheOpts)
    assert opts == CacheOpts(host="h", port=1, tls=True)


def test_inv_strict_unknown_under_failure() -> None:
    # Unknown key in the file provider is ALSO caught (not just env).
    binder = from_env_and_file(
        env={"DB__URL": "u"},
        dotenv={"DB__EXTRA": "sneaky"},
    )
    with pytest.raises(ConfigBindingError, match="CONFIG-INV-04"):
        binder.bind("db", DbOpts)


# ---------------------------------------------------------------------------
# CONFIG_INV_05 — precedence (env > file > defaults), env pinned
# ---------------------------------------------------------------------------
def test_inv_precedence_confirms() -> None:
    binder = from_env_and_file(
        env={"DB__URL": "from-env"},
        dotenv={"DB__URL": "from-file", "DB__POOL": "33"},
    )
    opts = binder.bind("db", DbOpts)
    assert opts.url == "from-env"  # env wins
    assert opts.pool == 33          # file fills where env is absent


def test_inv_precedence_prevents() -> None:
    # A later non-pinned provider SHALL NOT override an operator-pinned env value.
    # We simulate the wrong ordering by constructing providers manually with
    # env FIRST (pinned) then file (non-pinned): file SHALL NOT override env.
    env_prov = EnvProvider({"DB__URL": "pinned-by-operator"}, pinned=True)
    file_prov = DotEnvProvider({"DB__URL": "from-file"})
    binder = StrictConfigBinder([env_prov, file_prov])
    opts = binder.bind("db", DbOpts)
    assert opts.url == "pinned-by-operator"


def test_inv_precedence_under_failure() -> None:
    # When env is absent, file is used; when both absent, defaults apply.
    b1 = from_env_and_file(env={}, dotenv={"DB__URL": "only-file"})
    assert b1.bind("db", DbOpts).url == "only-file"

    b2 = from_env_and_file(env={"DB__URL": "u"})
    assert b2.bind("db", DbOpts).pool == 10  # dataclass default

    # If nothing supplies a required key, INV-01 fires (loud).
    b3 = from_env_and_file(env={}, dotenv={})
    with pytest.raises(ConfigBindingError):
        b3.bind("db", DbOpts)
