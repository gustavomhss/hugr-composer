"""ConfigBinding primitive — namespaced, typed, strict config binder.

Binds a namespaced slice of runtime configuration to a frozen dataclass
record, validated at startup. Sources are composed left-to-right as providers;
precedence is fixed: env > file > defaults. Misconfiguration fails loudly
at bind-time so boot never continues with a partially-filled record.

Invariant IDs cited by this module:

- CONFIG-INV-01: bind() MUST fail loudly if required keys are missing or typed
  coercion fails; it NEVER returns a partially-filled record.
- CONFIG-INV-02: Bound records MUST be frozen/immutable; runtime code CANNOT
  mutate a bound option to affect another consumer.
- CONFIG-INV-03: reload() MUST produce a new record without aliasing the
  previous one; references already handed out SHALL NOT silently mutate.
- CONFIG-INV-04: Unknown keys under the prefix MUST be reported as errors by
  default (strict binding) and NEVER silently dropped.
- CONFIG-INV-05: Precedence order (env > file > defaults) MUST be fixed and
  documented; a later source CANNOT override a value an operator pinned.
"""

from __future__ import annotations

import dataclasses
import os
import threading
from collections.abc import Iterable, Mapping
from typing import Any, Final, Protocol, TypeVar, runtime_checkable

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ConfigBindingError(ValueError):
    """Raised when a runtime call violates a ConfigBinding invariant."""


# ---------------------------------------------------------------------------
# Provider protocol + built-in providers
# ---------------------------------------------------------------------------
@runtime_checkable
class ConfigProvider(Protocol):
    """A pluggable source of raw string values keyed by dotted/underscore path.

    Providers are stateless lookups; they MUST be side-effect-free on read.
    """

    @property
    def name(self) -> str: ...
    @property
    def pinned(self) -> bool: ...
    def values(self, prefix: str) -> Mapping[str, str]: ...


_ENV_KEY_SEP: Final[str] = "__"


def _env_key(prefix: str, field: str) -> str:
    # Convention: DB__URL maps to prefix=db, field=url. Double-underscore
    # guards against field names that legitimately contain a single `_`.
    return f"{prefix}{_ENV_KEY_SEP}{field}".upper()


class EnvProvider:
    """Reads `PREFIX__FIELD` env vars from a snapshot dict.

    A snapshot is taken at construction time; reload() consumers should build
    a fresh EnvProvider to observe os.environ changes (or pass a dict).
    """

    def __init__(self, env: Mapping[str, str] | None = None, *, pinned: bool = True) -> None:
        src: Mapping[str, str] = env if env is not None else os.environ
        self._env: dict[str, str] = dict(src)
        self._pinned = pinned

    @property
    def name(self) -> str:
        return "env"

    @property
    def pinned(self) -> bool:
        # CONFIG-INV-05: env is the pinned operator source by default.
        return self._pinned

    def values(self, prefix: str) -> Mapping[str, str]:
        pfx = _env_key(prefix, "")
        out: dict[str, str] = {}
        for k, v in self._env.items():
            if k.startswith(pfx):
                field = k[len(pfx):].lower()
                if field:
                    out[field] = v
        return out


class DotEnvProvider:
    """Reads a simple `.env`-style mapping (pre-parsed dict).

    Accepts either a file path or an already-parsed mapping. The parser is
    intentionally tiny (KEY=VALUE per line; `#` comments; no interpolation);
    production deployments typically pre-parse via a richer library and pass
    the resulting mapping in.
    """

    def __init__(
        self,
        source: Mapping[str, str] | str | os.PathLike[str] | None = None,
    ) -> None:
        if source is None:
            self._raw: dict[str, str] = {}
        elif isinstance(source, Mapping):
            self._raw = {str(k): str(v) for k, v in source.items()}
        else:
            self._raw = self._parse_file(source)

    @staticmethod
    def _parse_file(path: str | os.PathLike[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        # Lazy import of pathlib — already stdlib but keep the convention
        # of localising file I/O in a single helper.
        from pathlib import Path
        p = Path(path)
        if not p.exists():
            return out
        for raw_line in p.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"').strip("'")
        return out

    @property
    def name(self) -> str:
        return "file"

    @property
    def pinned(self) -> bool:
        # CONFIG-INV-05: file source is NOT pinned; env can override it.
        return False

    def values(self, prefix: str) -> Mapping[str, str]:
        pfx = _env_key(prefix, "")
        out: dict[str, str] = {}
        for k, v in self._raw.items():
            up = k.upper()
            if up.startswith(pfx):
                field = up[len(pfx):].lower()
                if field:
                    out[field] = v
        return out


@runtime_checkable
class SecretsProviderLike(Protocol):
    """Minimal SecretsVault interface sufficient for ConfigBinding."""

    def get(self, key: str) -> str: ...


class SecretsProvider:
    """Pulls selected fields from an external SecretsVault-like store.

    The provider is constructed with an explicit map of `field_name -> vault_key`
    per prefix. This keeps vault lookups deterministic and auditable.
    """

    def __init__(
        self,
        vault: SecretsProviderLike,
        *,
        prefix_to_keys: Mapping[str, Mapping[str, str]] | None = None,
        pinned: bool = False,
    ) -> None:
        self._vault = vault
        self._map: dict[str, dict[str, str]] = {
            p: dict(kv) for p, kv in (prefix_to_keys or {}).items()
        }
        self._pinned = pinned

    @property
    def name(self) -> str:
        return "vault"

    @property
    def pinned(self) -> bool:
        return self._pinned

    def values(self, prefix: str) -> Mapping[str, str]:
        mapping = self._map.get(prefix, {})
        out: dict[str, str] = {}
        for field, vault_key in mapping.items():
            out[field] = self._fetch_one(prefix, field, vault_key)
        return out

    def _fetch_one(self, prefix: str, field: str, vault_key: str) -> str:
        try:
            return str(self._vault.get(vault_key))
        except Exception as exc:  # CONFIG-INV-01: any vault error is bind-time fatal; re-raised as typed error
            # Defense-in-depth: do NOT echo the vault exception message — it can
            # embed the secret value if the vault implementation is chatty.
            # Emit only the exception type and the requested key.
            raise ConfigBindingError(
                f"CONFIG-INV-01: secret fetch failed for {prefix}.{field} "
                f"(vault_key={vault_key!r}): {type(exc).__name__}"
            ) from exc


# ---------------------------------------------------------------------------
# Type coercion
# ---------------------------------------------------------------------------
_TRUE_LITERALS: Final[frozenset[str]] = frozenset({"1", "true", "yes", "on", "y", "t"})
_FALSE_LITERALS: Final[frozenset[str]] = frozenset({"0", "false", "no", "off", "n", "f"})


def _coerce(field_name: str, raw: str, target: type) -> object:
    """Coerce a raw string to the declared dataclass field type.

    Supports str, int, float, bool. Anything else raises (CONFIG-INV-01).
    """
    if target is str:
        return raw
    # Defense-in-depth: coerce errors MUST NOT echo `raw` — the binder cannot
    # know which fields are secrets. The field name + target type suffice for
    # diagnostics; the caller controls the raw value.
    if target is bool:
        lowered = raw.strip().lower()
        if lowered in _TRUE_LITERALS:
            return True
        if lowered in _FALSE_LITERALS:
            return False
        raise ConfigBindingError(
            f"CONFIG-INV-01: cannot coerce {field_name!r} to bool."
        )
    if target is int:
        try:
            return int(raw, 10)
        except ValueError as exc:
            raise ConfigBindingError(
                f"CONFIG-INV-01: cannot coerce {field_name!r} to int."
            ) from exc
    if target is float:
        try:
            return float(raw)
        except ValueError as exc:
            raise ConfigBindingError(
                f"CONFIG-INV-01: cannot coerce {field_name!r} to float."
            ) from exc
    raise ConfigBindingError(
        f"CONFIG-INV-01: unsupported field type {target!r} for {field_name!r}; "
        f"supported: str, int, float, bool."
    )


# ---------------------------------------------------------------------------
# Protocol surface (mirrors the catalog api_signature verbatim in intent)
# ---------------------------------------------------------------------------
@runtime_checkable
class ConfigBinding(Protocol):
    def bind(self, prefix: str, schema: type[T]) -> T: ...
    def reload(self) -> None: ...


# ---------------------------------------------------------------------------
# Reference implementation
# ---------------------------------------------------------------------------
class StrictConfigBinder:
    """Reference ConfigBinding implementation.

    Providers are composed left-to-right. Precedence is fixed by `pinned`:

    - A `pinned` provider's value CANNOT be overridden by a later provider
      (CONFIG-INV-05). In the default `from_env_and_file(...)` wiring, env is
      pinned and file is not — so env wins over file, and both win over
      dataclass defaults.

    - Unknown keys under the prefix (present in any provider but not declared
      on the schema) raise ConfigBindingError (CONFIG-INV-04).

    - Each bind() returns a freshly-constructed frozen dataclass; reload()
      rebinds previously-requested prefixes into NEW records without aliasing
      the old ones (CONFIG-INV-02 / CONFIG-INV-03).
    """

    def __init__(self, providers: Iterable[ConfigProvider]) -> None:
        self._providers: list[ConfigProvider] = list(providers)
        self._lock = threading.Lock()
        self._bindings: dict[tuple[str, type], object] = {}

    # ----- catalog API --------------------------------------------------------
    def bind(self, prefix: str, schema: type[T]) -> T:
        self._validate_prefix(prefix)
        self._validate_schema(schema)

        fields = dataclasses.fields(schema)  # type: ignore[arg-type]  # CONFIG-INV-01: _validate_schema already asserts is_dataclass
        field_names: set[str] = {f.name for f in fields}

        resolved, unknown = self._collect(prefix, field_names)
        if unknown:
            detail = ", ".join(
                f"{k!r} (from {'+'.join(srcs)})" for k, srcs in sorted(unknown.items())
            )
            raise ConfigBindingError(
                f"CONFIG-INV-04: unknown key(s) under prefix {prefix!r}: {detail}. "
                f"Strict binding — declare on {schema.__name__} or remove the key."
            )

        kwargs, missing = self._assemble_kwargs(schema, fields, resolved)
        if missing:
            raise ConfigBindingError(
                f"CONFIG-INV-01: missing required key(s) under prefix {prefix!r}: "
                f"{sorted(missing)}. No partial record is returned."
            )

        record = self._construct(schema, kwargs)
        with self._lock:
            self._bindings[(prefix, schema)] = record
        return record

    @staticmethod
    def _validate_prefix(prefix: str) -> None:
        if not isinstance(prefix, str) or not prefix.strip():
            raise ConfigBindingError(
                "CONFIG-INV-01: prefix MUST be a non-empty string."
            )

    @staticmethod
    def _validate_schema(schema: type) -> None:
        if not dataclasses.is_dataclass(schema):
            raise ConfigBindingError(
                f"CONFIG-INV-01: schema {schema!r} MUST be a @dataclass."
            )
        if not schema.__dataclass_params__.frozen:  # type: ignore[attr-defined]  # CONFIG-INV-02: dataclass private sentinel is the only frozen flag
            raise ConfigBindingError(
                f"CONFIG-INV-02: schema {schema.__name__} MUST be frozen "
                "(@dataclass(frozen=True))."
            )

    def _collect(
        self, prefix: str, field_names: set[str]
    ) -> tuple[dict[str, str], dict[str, list[str]]]:
        # CONFIG-INV-05: left-to-right provider order; a pinned provider's value
        # is frozen against later overrides.
        resolved: dict[str, str] = {}
        pinned_keys: set[str] = set()
        unknown: dict[str, list[str]] = {}
        for provider in self._providers:
            for k, v in provider.values(prefix).items():
                if k not in field_names:
                    unknown.setdefault(k, []).append(provider.name)
                    continue
                if k in pinned_keys:
                    continue
                resolved[k] = v
                if provider.pinned:
                    pinned_keys.add(k)
        return resolved, unknown

    @staticmethod
    def _assemble_kwargs(
        schema: type,
        fields: tuple[dataclasses.Field[Any], ...],
        resolved: Mapping[str, str],
    ) -> tuple[dict[str, Any], list[str]]:
        kwargs: dict[str, Any] = {}
        missing: list[str] = []
        for f in fields:
            target_type = f.type if isinstance(f.type, type) else _resolve_type_hint(schema, f.name)
            if f.name in resolved:
                kwargs[f.name] = _coerce(f.name, resolved[f.name], target_type)
            elif f.default is not dataclasses.MISSING or f.default_factory is not dataclasses.MISSING:
                continue
            else:
                missing.append(f.name)
        return kwargs, missing

    @staticmethod
    def _construct(schema: type[T], kwargs: Mapping[str, Any]) -> T:
        try:
            return schema(**kwargs)
        except Exception as exc:  # CONFIG-INV-01: any construction failure is bind-time fatal
            # Defense-in-depth: upstream `__post_init__` validators may echo
            # field values into their error messages. Suppress the inner message
            # so coerced secret values never reach logs via the binder.
            raise ConfigBindingError(
                f"CONFIG-INV-01: construction of {schema.__name__} failed: "
                f"{type(exc).__name__} (message suppressed to prevent value leakage)"
            ) from exc

    def reload(self) -> None:
        """Rebind every prefix/schema previously requested, producing NEW records.

        CONFIG-INV-03: existing references handed out to callers remain valid
        (frozen dataclasses cannot mutate), and the refreshed records live in
        the binder's own registry. Callers requesting the same (prefix, schema)
        after reload() SHALL receive the freshly-bound instance.
        """
        with self._lock:
            targets = list(self._bindings.keys())
        for prefix, schema in targets:
            # bind() re-writes _bindings under its own lock.
            self.bind(prefix, schema)

    # ----- observability hooks -----------------------------------------------
    @property
    def providers(self) -> tuple[ConfigProvider, ...]:
        return tuple(self._providers)

    def current(self, prefix: str, schema: type[T]) -> T | None:
        with self._lock:
            obj = self._bindings.get((prefix, schema))
        # Narrow to schema type for callers; cache keys already encode schema.
        if obj is None:
            return None
        if isinstance(obj, schema):
            return obj
        return None


def _resolve_type_hint(schema: type, field_name: str) -> type:
    """Resolve a dataclass field type when `f.type` is a forward-ref string."""
    import typing as _typing
    hints = _typing.get_type_hints(schema)
    hint = hints.get(field_name)
    if isinstance(hint, type):
        return hint
    raise ConfigBindingError(
        f"CONFIG-INV-01: field {field_name!r} on {schema.__name__} has unsupported "
        f"non-simple type annotation {hint!r}."
    )


# ---------------------------------------------------------------------------
# Convenience constructor
# ---------------------------------------------------------------------------
def from_env_and_file(
    env: Mapping[str, str] | None = None,
    dotenv: Mapping[str, str] | str | os.PathLike[str] | None = None,
) -> StrictConfigBinder:
    """Build a binder with the canonical precedence env > file > defaults.

    CONFIG-INV-05: provider ordering is declared once, here. File is added
    first so env (appended second) is the final pinned source.
    """
    providers: list[ConfigProvider] = [DotEnvProvider(dotenv), EnvProvider(env)]
    return StrictConfigBinder(providers)


__all__ = [
    "ConfigBinding",
    "ConfigBindingError",
    "ConfigProvider",
    "DotEnvProvider",
    "EnvProvider",
    "SecretsProvider",
    "SecretsProviderLike",
    "StrictConfigBinder",
    "from_env_and_file",
]
