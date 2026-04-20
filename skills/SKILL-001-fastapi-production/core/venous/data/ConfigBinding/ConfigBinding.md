# ConfigBinding

## What it does (plain language)

Every service needs a handful of configuration values — database URL, pool
size, feature flags, API keys. `ConfigBinding` reads those values from a
well-defined set of sources (environment variables, a `.env` file, an
external secrets vault), checks that everything required is present, coerces
strings into their real types (`int`, `bool`, `float`, `str`), and hands the
application a single frozen record. If something is missing or malformed,
the service **fails to boot** with a loud, greppable error — it never starts
with a half-filled configuration.

## Purpose

Bind a namespaced slice of the runtime configuration to a typed record,
validated at startup so misconfiguration fails loud, not silent.

## When to use and when NOT to use

- USE: application boot, per-subsystem options (`db`, `cache`, `api`, `auth`),
  operator-pinned secrets from Vault/ConfigMap.
- DO NOT USE: hot-path per-request tuning — re-bind once per reload, read the
  frozen record in the hot path.
- DO NOT USE: as a feature-flag platform — see `FeatureFlag` for per-request
  rollout primitives. `ConfigBinding` is for values that change on deploy.

## API surface

The catalog `api_signature` is the sole authority; see `ConfigBinding.contract.json`
for the verbatim Protocol declaration. `ConfigBinding.py` re-declares the
Protocol and provides `StrictConfigBinder` as the reference implementation.

```python
class ConfigBinding(Protocol):
    def bind(self, prefix: str, schema: Type[T]) -> T: ...
    def reload(self) -> None: ...
```

Plug in new sources by implementing `ConfigProvider` (exposes `name`,
`pinned`, and `values(prefix)`). Built-ins: `EnvProvider`, `DotEnvProvider`,
`SecretsProvider` (wraps a `SecretsVault`-compatible client).

## Invariants

| ID | Rule |
|---|---|
| CONFIG_INV_01 | `bind()` MUST fail loudly if required keys are missing or typed coercion fails; it NEVER returns a partially-filled record. |
| CONFIG_INV_02 | Bound records MUST be frozen / immutable; runtime code CANNOT mutate a bound option to affect another consumer. |
| CONFIG_INV_03 | `reload()` MUST produce a new record without aliasing the previous one; references already handed out SHALL NOT silently mutate. |
| CONFIG_INV_04 | Unknown keys under the prefix MUST be reported as errors by default (strict binding) and NEVER silently dropped. |
| CONFIG_INV_05 | Precedence order (env > file > defaults) MUST be fixed and documented; a later source CANNOT override a value an operator pinned. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the authoritative binding.

## Precedence (CONFIG_INV_05)

Providers are composed left-to-right. Each provider declares whether it is
`pinned`:

1. A pinned provider's value is frozen against any later provider.
2. A non-pinned provider fills keys no pinned provider supplied.
3. Dataclass defaults apply when no provider supplied the key.

Default wiring (`from_env_and_file`): `[DotEnvProvider (not pinned), EnvProvider (pinned)]`.
Env wins over file; file fills the rest; dataclass defaults fill what remains.
To elevate a secrets vault above env, place `SecretsProvider(..., pinned=True)`
first in the provider list.

## Thread and async safety

- `StrictConfigBinder.bind()` is safe under concurrent callers; the internal
  binding registry is guarded by a lock.
- Frozen dataclasses cannot be mutated, so any reference handed out is
  thread-safe by construction.
- `reload()` atomically replaces the registry entry per `(prefix, schema)`;
  callers still holding the old reference observe no mutation (CONFIG_INV_03).

## Operational characteristics (for SRE)

- Boot cost is O(#fields × #providers); typically sub-millisecond.
- `reload()` emits `config.reload.completed` with `rebound_count`; a sudden
  drop in that count after a config push is the canonical symptom of a
  failed deployment rollback.
- Recommended alerts:
  - `rate(config_binds_total{result="failed"}[5m]) > 0` → page: boot failed.
  - `rate(config_reload_total{result="failed"}[10m]) > 0` → warn.
- Failure mode: a bad value or missing key raises `ConfigBindingError` at
  boot. Supervisors should NOT auto-restart — backing off prevents a
  misconfigured rollout from spreading.

## Security considerations

- Secrets SHOULD arrive via `SecretsProvider` backed by a vault client.
  Committing secrets to `.env` files in source control is explicitly
  discouraged; the `DotEnvProvider` is intended for local development
  overrides.
- Unknown keys fail loud (CONFIG_INV_04). This prevents an attacker-controlled
  file from smuggling extra fields into a dataclass schema that a later
  refactor silently starts reading.
- Operator-pinned precedence (CONFIG_INV_05) means a compromised non-pinned
  source (e.g. a world-writable `.env`) cannot override a vault- or
  environment-supplied value without also compromising the pinned source.
- Coercion accepts only primitive types (`str`, `int`, `float`, `bool`). The
  binder refuses arbitrary types; this closes a de-serialisation injection
  vector that generic YAML loaders would otherwise open.

## Provenance

- Source agent: Agent #1 FRAMEWORKS
  (`docs/research/outputs/AGENT_1_FRAMEWORKS.json`).
- Primary sources:
  - Spring Boot 3.x — `@ConfigurationProperties`, `ConstructorBinding`,
    `DefaultValue`.
  - ASP.NET Core 8.0 — Options pattern (`IOptions<T>`, `Configure<T>`).
  - 12-Factor App (`https://12factor.net/config`) — environment as the canonical
    source of runtime configuration.

## Alternatives considered and rejected

- Read `os.environ` directly — no schema, silent typos; every module reinvents
  defaults; the only source of truth is grep.
- Dict-of-dicts passed around — no validation, no defaults, and the drift
  between what keys a module reads and what it documents is unbounded.
- Per-module singleton loaders — key-naming drift; every module picks its
  own precedence, so an `XYZ_URL` env var behaves differently in the DB
  module vs. the cache module.

## Extension contract

A downstream tool extends binding by implementing `ConfigProvider`:

```python
class VaultProvider:
    @property
    def name(self) -> str: return "vault"
    @property
    def pinned(self) -> bool: return True
    def values(self, prefix: str) -> Mapping[str, str]: ...
```

Providers are injected via `StrictConfigBinder([a, b, c])`; the ordering fixes
precedence. Custom providers MUST preserve the five invariants above.

## Schema of `ConfigBinding.contract.json`

The contract file is a verbatim copy of the `PrimitiveSpec` dict from the
research catalog. Fields: `name`, `namespace`, `purpose`, `api_signature`,
`invariants[]`, `extension_contract`, `consumption_example`, `sources[]`,
`why_essential`, `alternatives_considered[]`, `maturity`.

## Usage

```python
from dataclasses import dataclass
from ConfigBinding import from_env_and_file

@dataclass(frozen=True)
class DbOpts:
    url: str
    pool: int = 10

def boot() -> DbOpts:
    binder = from_env_and_file()  # reads os.environ, no .env by default
    return binder.bind("db", DbOpts)  # INV-01: raises if DB__URL is missing
```

## Compose with:

- **Fail-fast startup** → `DiContainer` + `LifetimeScope`
  DI resolution requires every declared binding; a missing or mistyped value crashes boot instead of surfacing as a 500 under load.

- **Secrets vs config split** → `SecretsVault` + `FeatureToggle`
  ConfigBinding holds non-secret, per-env shape; secrets come from the vault at request time; feature toggles drive per-cohort behavior — three distinct lifecycles, three distinct tools.

- **Typed reload** → `LifetimeScope` + `AuditEvent`
  Hot-reload of config rebinds the typed record and emits an audit event with a diff — no operator 'maybe I changed that flag' ambiguity.
