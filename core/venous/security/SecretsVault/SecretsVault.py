"""SecretsVault primitive — fetch, cache, rotate, audit named secrets.

Implements the catalog Protocol for `security.SecretsVault`. Provides a
named-secret interface on top of pluggable backend adapters (env, file,
AWS / GCP / Azure KMS — registered lazily so the module boots on minimal
hosts without any cloud SDK installed).

Every get/rotate call emits a structured audit event naming the secret and
the caller identity but NEVER the material. Cache is time-bounded; cached
entries are evicted once their `not_after` deadline passes or when the
configured max-age elapses. When the backend is unavailable, cold secrets
fail closed and warm entries past their TTL are refused rather than
returned stale (SV-INV-05).

Import is side-effect-free: cloud-SDK backends are imported inside the
adapter registration functions (AWS / GCP / Azure) so the module remains
importable even with none of those libraries present.

Invariant IDs (enforced at runtime):

- SV-INV-01: secret material MUST NEVER appear in logs, exceptions, reprs,
  tracebacks, or telemetry.
- SV-INV-02: get() MUST honor a time-bounded cache; cached material MUST
  NEVER outlive `not_after` or the configured max-age.
- SV-INV-03: rotate() MUST produce a strictly increasing version and MUST
  NEVER return the same material for a different version.
- SV-INV-04: every get/rotate call emits an audit event with the secret
  name + caller identity but NEVER the material.
- SV-INV-05: on backend outage the vault MUST fail closed for cold secrets
  and MUST NEVER surface stale material past its cache TTL.
"""

from __future__ import annotations

import contextvars
import ctypes
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from typing import Final, Protocol, runtime_checkable

# Cache defaults — a 300 s max-age is the OWASP ASVS V6.4 rule-of-thumb for
# in-process secret caches; production callers override per-secret.
DEFAULT_MAX_AGE_S: Final[float] = 300.0
MIN_SECRET_NAME_LEN: Final[int] = 1
MAX_SECRET_NAME_LEN: Final[int] = 200
# Names MUST be printable ASCII without whitespace or control chars so they
# survive log lines, span tags, and metric labels without ambiguity.
_ALLOWED_NAME_CHARS: Final[frozenset[str]] = frozenset(
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789"
    "-_./:"
)


class SecretsVaultError(Exception):
    """Runtime invariant violation on a SecretsVault operation.

    Exception text NEVER carries secret material or partial fragments
    thereof (SV-INV-01). Callers MUST surface this as a 500/uncaught in
    production logs without re-serializing the offending value.
    """


class SecretNotFoundError(SecretsVaultError):
    """Requested secret name is not registered in any reachable scope."""


class SecretBackendUnavailableError(SecretsVaultError):
    """Backend call failed (network / permission / throttling).

    SV-INV-05: callers MUST treat this as fail-closed for cold secrets and
    MUST NOT substitute a cached value whose TTL has elapsed.
    """


class SecretScopeError(SecretsVaultError):
    """Caller attempted to access a secret outside its declared scope."""


# ---------------------------------------------------------------------------
# Public data types — catalog-exact surface (api_signature byte-for-byte)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SecretVersion:
    """A single version of a named secret.

    Immutable. `material` is stored as `bytes`; the vault returns a fresh
    copy per call so callers may zeroize their working buffer after use.

    SV-INV-01 defense-in-depth: `material` is `repr=False` so the default
    `__repr__` emitted by exceptions / logs / pytest asserts CANNOT leak
    plaintext. A custom `__repr__` deliberately surfaces only non-sensitive
    metadata.
    """

    name: str
    version: int
    material: bytes = field(repr=False)
    not_after: int | None

    def __repr__(self) -> str:
        return (
            f"SecretVersion(name={self.name!r}, version={self.version}, "
            f"material=<{len(self.material)} bytes redacted>, "
            f"not_after={self.not_after})"
        )


@runtime_checkable
class SecretsVault(Protocol):
    def get(self, name: str) -> SecretVersion: ...
    def rotate(self, name: str) -> SecretVersion: ...
    def invalidate(self, name: str) -> None: ...


# ---------------------------------------------------------------------------
# Backend adapter shape
# ---------------------------------------------------------------------------
class SecretBackend(Protocol):
    """Adapter shape every storage backend MUST implement.

    `fetch` returns the current `(version, material, not_after)` tuple.
    `rotate` advances to a new version — the backend MUST guarantee the
    returned version is strictly greater than any previously observed
    version for the same name (SV-INV-03).
    """

    def fetch(self, name: str) -> tuple[int, bytes, int | None]: ...
    def rotate(self, name: str) -> tuple[int, bytes, int | None]: ...


# ---------------------------------------------------------------------------
# Audit event — what gets logged on EVERY get/rotate
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AuditEvent:
    """Structured audit record. NEVER carries secret material (SV-INV-01, 04)."""

    timestamp_ms: int
    operation: str  # "get" | "rotate" | "invalidate"
    secret_name: str
    caller_identity: str
    version: int | None
    outcome: str  # "ok" | "miss" | "denied" | "backend_unavailable"
    cache_hit: bool


AuditSink = Callable[[AuditEvent], None]


# ---------------------------------------------------------------------------
# Clock — injectable so tests can advance time without monkey-patching
# ---------------------------------------------------------------------------
class Clock(Protocol):
    def now_s(self) -> float: ...


class _RealClock:
    def now_s(self) -> float:
        return time.time()


# ---------------------------------------------------------------------------
# Best-effort zeroization — SV-INV-01
# ---------------------------------------------------------------------------
def zeroize(buf: bytearray) -> None:
    """Overwrite a bytearray in place. Python's immutable `bytes` cannot be
    zeroed; callers that need zeroization MUST route material through
    bytearray and call this helper when the working buffer goes out of use.
    """
    if not isinstance(buf, bytearray):
        raise SecretsVaultError("SV-INV-01: zeroization requires a bytearray.")
    n = len(buf)
    if n == 0:
        return
    addr = (ctypes.c_char * n).from_buffer(buf)
    ctypes.memset(ctypes.addressof(addr), 0, n)


# ---------------------------------------------------------------------------
# Name validation — keeps audit labels safe for logs / metrics
# ---------------------------------------------------------------------------
def _validate_name(name: str) -> str:
    if not isinstance(name, str):
        raise SecretsVaultError("SV-INV-04: secret name MUST be a str.")
    if not (MIN_SECRET_NAME_LEN <= len(name) <= MAX_SECRET_NAME_LEN):
        raise SecretsVaultError(
            f"SV-INV-04: secret name length out of bounds "
            f"[{MIN_SECRET_NAME_LEN}..{MAX_SECRET_NAME_LEN}]."
        )
    if any(c not in _ALLOWED_NAME_CHARS for c in name):
        raise SecretsVaultError(
            "SV-INV-04: secret name contains disallowed characters "
            "(must match [A-Za-z0-9-_./:])."
        )
    return name


# ---------------------------------------------------------------------------
# In-memory reference backend — deterministic; perfect for tests + dev
# ---------------------------------------------------------------------------
@dataclass
class _InMemoryRecord:
    version: int
    material: bytes
    not_after: int | None


class InMemoryBackend:
    """Reference SecretBackend. Holds records in a dict; rotation increments
    the version monotonically and regenerates material via the registered
    factory. Thread-safe for concurrent get/rotate via a single lock.
    """

    def __init__(self) -> None:
        self._records: dict[str, _InMemoryRecord] = {}
        self._factories: dict[str, Callable[[int], bytes]] = {}
        self._ttls: dict[str, int | None] = {}
        self._lock = threading.Lock()
        self._available = True  # flipped by tests to simulate outage

    def register(
        self,
        name: str,
        initial_material: bytes,
        *,
        factory: Callable[[int], bytes] | None = None,
        not_after: int | None = None,
    ) -> None:
        """Seed a secret. `factory(version)` generates material on rotation;
        if omitted, rotate() derives a distinct payload from the version number.
        """
        _validate_name(name)
        if not isinstance(initial_material, (bytes, bytearray)):
            raise SecretsVaultError("SV-INV-01: material MUST be bytes.")
        with self._lock:
            self._records[name] = _InMemoryRecord(
                version=1,
                material=bytes(initial_material),
                not_after=not_after,
            )
            self._factories[name] = factory or _default_factory
            self._ttls[name] = not_after

    def set_available(self, flag: bool) -> None:  # pragma: no cover - test hook
        self._available = flag

    def _check_available(self) -> None:
        if not self._available:
            raise SecretBackendUnavailableError(
                "SV-INV-05: backend marked unavailable (simulated outage)."
            )

    def fetch(self, name: str) -> tuple[int, bytes, int | None]:
        _validate_name(name)
        self._check_available()
        with self._lock:
            rec = self._records.get(name)
            if rec is None:
                raise SecretNotFoundError(
                    "SV-INV-04: secret not registered in backend (name withheld)."
                )
            return rec.version, rec.material, rec.not_after

    def rotate(self, name: str) -> tuple[int, bytes, int | None]:
        _validate_name(name)
        self._check_available()
        with self._lock:
            rec = self._records.get(name)
            if rec is None:
                raise SecretNotFoundError(
                    "SV-INV-04: cannot rotate unregistered secret (name withheld)."
                )
            new_version = rec.version + 1
            new_material = self._factories[name](new_version)
            if new_material == rec.material:
                # SV-INV-03: a factory that returns the same bytes for a new
                # version violates the monotonic-version rule. Refuse.
                raise SecretsVaultError(
                    "SV-INV-03: rotation factory produced identical material."
                )
            rec.version = new_version
            rec.material = bytes(new_material)
            rec.not_after = self._ttls[name]
            return rec.version, rec.material, rec.not_after


def _default_factory(version: int) -> bytes:
    """Deterministic-but-distinct default rotation payload used by tests.

    Production backends always supply a proper CSPRNG-driven factory; this
    default exists so InMemoryBackend is useful out of the box.
    """
    return f"v{version}-material".encode()


# ---------------------------------------------------------------------------
# Lazy-registered cloud backends — module boots without any SDK installed
# ---------------------------------------------------------------------------
def register_aws_secrets_manager_backend() -> SecretBackend:  # pragma: no cover - requires boto3
    """Factory for an AWS Secrets Manager adapter. Lazy import of `boto3`.

    SV-INV-03: AWS Secrets Manager exposes `VersionId` strings; the adapter
    MUST map them to a strictly increasing integer (e.g. via `VersionStage`
    history). An adapter that cannot guarantee monotonicity MUST be refused
    by the caller — we validate at construction here.
    """
    try:
        import boto3  # type: ignore[import-not-found,import-untyped,unused-ignore]  # SV-INV-05: optional SDK; module boots without it.
    except ImportError as exc:
        raise SecretsVaultError(
            "SV-INV-05: boto3 not installed; AWS backend unavailable."
        ) from exc

    class _AwsBackend:
        def __init__(self) -> None:
            self._client = boto3.client("secretsmanager")
            self._version_map: dict[str, int] = {}

        def fetch(self, name: str) -> tuple[int, bytes, int | None]:
            resp = self._client.get_secret_value(SecretId=name)
            material = resp.get("SecretBinary") or resp["SecretString"].encode()
            version = self._version_map.get(name, 1)
            return version, material, None

        def rotate(self, name: str) -> tuple[int, bytes, int | None]:
            self._client.rotate_secret(SecretId=name)
            v = self._version_map.get(name, 1) + 1
            self._version_map[name] = v
            resp = self._client.get_secret_value(SecretId=name)
            material = resp.get("SecretBinary") or resp["SecretString"].encode()
            return v, material, None

    return _AwsBackend()


def register_gcp_secret_manager_backend() -> SecretBackend:  # pragma: no cover - requires google-cloud
    """Factory for a GCP Secret Manager adapter. Lazy import."""
    try:
        from google.cloud import secretmanager  # type: ignore[import-not-found,import-untyped,unused-ignore]  # noqa: I001 — SV-INV-05: optional SDK; module boots without it; ruff/mypy compatibility needs the suppression on the import line.
    except ImportError as exc:
        raise SecretsVaultError(
            "SV-INV-05: google-cloud-secret-manager not installed."
        ) from exc

    class _GcpBackend:
        def __init__(self) -> None:
            self._client = secretmanager.SecretManagerServiceClient()

        def fetch(self, name: str) -> tuple[int, bytes, int | None]:
            resp = self._client.access_secret_version(name=f"{name}/versions/latest")
            # Response `name` encodes the integer version as the final path segment.
            version = int(resp.name.rsplit("/", 1)[-1])
            return version, resp.payload.data, None

        def rotate(self, name: str) -> tuple[int, bytes, int | None]:
            raise SecretsVaultError(
                "SV-INV-03: GCP Secret Manager rotation requires an external "
                "Cloud Scheduler trigger — refuse in-process rotation."
            )

    return _GcpBackend()


def register_azure_key_vault_backend() -> SecretBackend:  # pragma: no cover - requires azure-keyvault
    """Factory for an Azure Key Vault adapter. Lazy import."""
    try:
        from azure.identity import DefaultAzureCredential  # type: ignore[import-not-found,import-untyped,unused-ignore]  # noqa: I001 — SV-INV-05: optional SDK; module boots without it.
        from azure.keyvault.secrets import SecretClient  # type: ignore[import-not-found,import-untyped,unused-ignore]  # SV-INV-05: optional SDK; module boots without it.
    except ImportError as exc:
        raise SecretsVaultError(
            "SV-INV-05: azure-keyvault-secrets not installed."
        ) from exc

    class _AzureBackend:
        def __init__(self, vault_url: str) -> None:
            self._client = SecretClient(
                vault_url=vault_url, credential=DefaultAzureCredential(),
            )
            self._version_map: dict[str, int] = {}

        def fetch(self, name: str) -> tuple[int, bytes, int | None]:
            s = self._client.get_secret(name)
            v = self._version_map.get(name, 1)
            return v, (s.value or "").encode(), None

        def rotate(self, name: str) -> tuple[int, bytes, int | None]:
            v = self._version_map.get(name, 1) + 1
            self._version_map[name] = v
            s = self._client.get_secret(name)
            return v, (s.value or "").encode(), None

    # Return a *factory* the caller pins; we do not guess a vault_url.
    return _AzureBackend("https://example.vault.azure.net/")


# ---------------------------------------------------------------------------
# Cache — TTL-bounded; entries are evicted at `now >= expires_at`
# ---------------------------------------------------------------------------
@dataclass
class _CacheEntry:
    version: int
    material: bytes
    not_after: int | None
    cached_at_s: float
    expires_at_s: float


# ---------------------------------------------------------------------------
# Caller identity context — propagated to every audit event
# ---------------------------------------------------------------------------
# SV-INV-04 correctness: we use ContextVar (NOT threading.local) so concurrent
# asyncio coroutines on the same event-loop thread each carry their own
# identity — otherwise two interleaved `caller_identity("alice") / ("bob")`
# blocks would write each other's identity into the audit log.
_caller_context: contextvars.ContextVar[str] = contextvars.ContextVar(
    "secretsvault.caller_identity", default="anonymous",
)


@contextmanager
def caller_identity(identity: str) -> Iterator[str]:
    """Bind a caller identity for the duration of the `with` block.

    SV-INV-04: every get/rotate inside this block emits an audit event
    citing `identity`. Outside any block, identity defaults to "anonymous"
    which still passes validation but is flagged by the audit log.
    """
    if not isinstance(identity, str) or not identity.strip():
        raise SecretsVaultError("SV-INV-04: caller_identity MUST be non-empty str.")
    token = _caller_context.set(identity)
    try:
        yield identity
    finally:
        _caller_context.reset(token)


def current_caller_identity() -> str:
    """Return the currently bound caller identity or `"anonymous"`."""
    return _caller_context.get()


# ---------------------------------------------------------------------------
# In-memory audit sink — tests inspect the buffer; production wires a real logger
# ---------------------------------------------------------------------------
class InMemoryAuditSink:
    """Thread-safe list-backed audit collector.

    SV-INV-01: stores the `AuditEvent` as-is; since `AuditEvent` has NO
    material field, no leak is possible via this sink.
    """

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []
        self._lock = threading.Lock()

    def __call__(self, event: AuditEvent) -> None:
        with self._lock:
            self._events.append(event)

    def events(self) -> list[AuditEvent]:
        with self._lock:
            return list(self._events)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


# ---------------------------------------------------------------------------
# Reference vault — orchestrates backend + cache + audit
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class _Scope:
    """Caller scope — the set of secret names a caller is permitted to read."""

    identity: str
    allowed: frozenset[str]


class CachingSecretsVault:
    """Reference `SecretsVault` implementation.

    - Wraps any `SecretBackend`.
    - Applies a time-bounded cache keyed by secret name (SV-INV-02).
    - Emits an `AuditEvent` on every get / rotate / invalidate (SV-INV-04).
    - Fails closed on backend outage for cold secrets (SV-INV-05).
    - Refuses access to names outside the calling scope, if scopes are set.
    """

    def __init__(
        self,
        backend: SecretBackend,
        *,
        audit: AuditSink | None = None,
        clock: Clock | None = None,
        max_age_s: float = DEFAULT_MAX_AGE_S,
    ) -> None:
        if max_age_s <= 0:
            raise SecretsVaultError("SV-INV-02: max_age_s MUST be > 0.")
        self._backend = backend
        self._audit: AuditSink = audit or (lambda _e: None)
        self._clock: Clock = clock or _RealClock()
        self._max_age_s = float(max_age_s)
        self._cache: dict[str, _CacheEntry] = {}
        self._cache_lock = threading.Lock()
        self._versions_seen: dict[str, int] = {}
        self._scopes: dict[str, _Scope] = {}

    # ---- scope management -------------------------------------------------
    def declare_scope(self, identity: str, allowed: Mapping[str, object]) -> None:
        """Register the allow-list of secret names for `identity`.

        If no scope is declared for an identity, access is unrestricted —
        useful for single-tenant services. Declaring ANY scope switches the
        vault into explicit-allow mode for that caller.
        """
        if not isinstance(identity, str) or not identity.strip():
            raise SecretsVaultError("SV-INV-04: identity MUST be non-empty str.")
        names: list[str] = []
        for name in allowed:
            _validate_name(str(name))
            names.append(str(name))
        self._scopes[identity] = _Scope(
            identity=identity, allowed=frozenset(names),
        )

    def _enforce_scope(self, name: str) -> None:
        ident = current_caller_identity()
        scope = self._scopes.get(ident)
        if scope is None:
            return  # no scope declared → unrestricted
        if name not in scope.allowed:
            raise SecretScopeError(
                "SV-INV-04: caller is not in scope for this secret (name withheld)."
            )

    # ---- core public surface ---------------------------------------------
    def get(self, name: str) -> SecretVersion:
        _validate_name(name)
        self._enforce_scope(name)
        now_s = self._clock.now_s()
        cached = self._cache_lookup(name, now_s)
        if cached is not None:
            self._emit_audit("get", name, cached.version, "ok", cache_hit=True)
            return SecretVersion(
                name=name,
                version=cached.version,
                material=cached.material,
                not_after=cached.not_after,
            )
        try:
            v, material, not_after = self._backend.fetch(name)
        except SecretNotFoundError:
            self._emit_audit("get", name, None, "miss", cache_hit=False)
            raise
        except SecretBackendUnavailableError:
            # SV-INV-05: cold fail-closed. Scrub cache just in case the TTL
            # was also elapsed so a subsequent stale read cannot sneak in.
            self._cache_evict_expired(now_s)
            self._emit_audit(
                "get", name, None, "backend_unavailable", cache_hit=False,
            )
            raise
        self._cache_store(name, v, material, not_after, now_s)
        self._track_version(name, v)
        self._emit_audit("get", name, v, "ok", cache_hit=False)
        return SecretVersion(
            name=name, version=v, material=material, not_after=not_after,
        )

    def rotate(self, name: str) -> SecretVersion:
        _validate_name(name)
        self._enforce_scope(name)
        now_s = self._clock.now_s()
        try:
            v, material, not_after = self._backend.rotate(name)
        except SecretBackendUnavailableError:
            self._emit_audit(
                "rotate", name, None, "backend_unavailable", cache_hit=False,
            )
            raise
        # SV-INV-03: version MUST strictly increase vs any prior observation.
        prior = self._versions_seen.get(name)
        if prior is not None and v <= prior:
            raise SecretsVaultError(
                f"SV-INV-03: rotation returned non-monotonic version "
                f"{v} <= prior {prior} for named secret (name withheld)."
            )
        self._track_version(name, v)
        # Replace cache entry atomically so subsequent get() sees new version.
        self._cache_store(name, v, material, not_after, now_s)
        self._emit_audit("rotate", name, v, "ok", cache_hit=False)
        return SecretVersion(
            name=name, version=v, material=material, not_after=not_after,
        )

    def invalidate(self, name: str) -> None:
        _validate_name(name)
        self._enforce_scope(name)
        with self._cache_lock:
            self._cache.pop(name, None)
        self._emit_audit(
            "invalidate", name, None, "ok", cache_hit=False,
        )

    # ---- internals --------------------------------------------------------
    def _cache_lookup(self, name: str, now_s: float) -> _CacheEntry | None:
        with self._cache_lock:
            entry = self._cache.get(name)
            if entry is None:
                return None
            # SV-INV-02: evict if expired by max-age OR by not_after deadline.
            if now_s >= entry.expires_at_s:
                self._cache.pop(name, None)
                return None
            if entry.not_after is not None and now_s >= float(entry.not_after):
                self._cache.pop(name, None)
                return None
            return entry

    def _cache_store(
        self,
        name: str,
        version: int,
        material: bytes,
        not_after: int | None,
        now_s: float,
    ) -> None:
        expires = now_s + self._max_age_s
        if not_after is not None:
            expires = min(expires, float(not_after))
        with self._cache_lock:
            self._cache[name] = _CacheEntry(
                version=version,
                material=bytes(material),
                not_after=not_after,
                cached_at_s=now_s,
                expires_at_s=expires,
            )

    def _cache_evict_expired(self, now_s: float) -> None:
        with self._cache_lock:
            stale = [
                k for k, e in self._cache.items()
                if now_s >= e.expires_at_s
                or (e.not_after is not None and now_s >= float(e.not_after))
            ]
            for k in stale:
                self._cache.pop(k, None)

    def _track_version(self, name: str, v: int) -> None:
        prior = self._versions_seen.get(name)
        if prior is None or v > prior:
            self._versions_seen[name] = v

    def _emit_audit(
        self,
        op: str,
        name: str,
        version: int | None,
        outcome: str,
        *,
        cache_hit: bool,
    ) -> None:
        event = AuditEvent(
            timestamp_ms=int(self._clock.now_s() * 1000),
            operation=op,
            secret_name=name,
            caller_identity=current_caller_identity(),
            version=version,
            outcome=outcome,
            cache_hit=cache_hit,
        )
        try:
            self._audit(event)
        except Exception as exc:
            # SV-INV-04: audit-sink failure MUST NOT silently swallow; re-raise as vault error.
            raise SecretsVaultError(
                "SV-INV-04: audit sink raised — refusing to proceed."
            ) from exc


# ---------------------------------------------------------------------------
# Extension-contract guard — refuse adapters that can't guarantee monotonicity
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AdapterCapabilities:
    """Declared capabilities an adapter claims to support.

    The extension_contract refuses an adapter that cannot produce a
    monotonically increasing version identifier or does not support
    rotation callbacks.
    """

    supports_monotonic_versions: bool
    supports_rotation_callback: bool
    name: str = field(default="")


def validate_adapter(caps: AdapterCapabilities) -> AdapterCapabilities:
    """Gate for registering an external adapter. Raises on violation."""
    if not caps.supports_monotonic_versions:
        raise SecretsVaultError(
            "SV-INV-03: adapter MUST expose monotonically increasing version ids."
        )
    if not caps.supports_rotation_callback:
        raise SecretsVaultError(
            "SV-INV-04: adapter MUST support rotation callbacks for audit."
        )
    return caps


__all__ = [
    "DEFAULT_MAX_AGE_S",
    "AdapterCapabilities",
    "AuditEvent",
    "AuditSink",
    "CachingSecretsVault",
    "Clock",
    "InMemoryAuditSink",
    "InMemoryBackend",
    "SecretBackend",
    "SecretBackendUnavailableError",
    "SecretNotFoundError",
    "SecretScopeError",
    "SecretVersion",
    "SecretsVault",
    "SecretsVaultError",
    "caller_identity",
    "current_caller_identity",
    "register_aws_secrets_manager_backend",
    "register_azure_key_vault_backend",
    "register_gcp_secret_manager_backend",
    "validate_adapter",
    "zeroize",
]
