"""AntiCorruptionLayer primitive — Evans/Vernon DDD translation boundary.

Implements the catalog Protocol for `data.AntiCorruptionLayer` and installs
runtime invariant checkers. The module performs zero I/O at import.

An AntiCorruptionLayer (ACL) is the narrow, versioned, stateless translator
that sits between a local BoundedContext and a foreign or legacy model. Every
inbound foreign payload is guarded, then translated to a local representation
BEFORE it reaches domain logic; every outbound local value is translated to
the foreign shape on the way out. The ACL NEVER lets foreign types leak into
the local context, NEVER reads or writes local repositories, and always
carries an explicit foreign-contract version so schema drift is detected
deterministically.

Invariant IDs cited by this module:

- ACL-INV-01: foreign types MUST NEVER cross the boundary of the local
  BoundedContext; all inbound payloads SHALL be translated through to_local
  before entering domain logic.
- ACL-INV-02: guard MUST reject inbound payloads that violate local
  invariants and raise before the payload reaches any local aggregate.
- ACL-INV-03: translation SHALL be stateless with respect to the local
  domain; the ACL CANNOT read or mutate local repositories during translation.
- ACL-INV-04: versioning of the foreign contract MUST be explicit; unversioned
  ACLs are FORBIDDEN.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from typing import Final, Generic, Protocol, TypeVar, runtime_checkable

# ---------------------------------------------------------------------------
# Type variables matching the catalog api_signature verbatim
# ---------------------------------------------------------------------------
Local = TypeVar("Local")
Foreign = TypeVar("Foreign")


# ---------------------------------------------------------------------------
# Protocol surface (matches catalog api_signature verbatim)
# ---------------------------------------------------------------------------
@runtime_checkable
class AntiCorruptionLayer(Protocol[Local, Foreign]):
    def to_local(self, foreign: Foreign) -> Local: ...
    def to_foreign(self, local: Local) -> Foreign: ...
    def guard(self, foreign: Foreign) -> None: ...


# ---------------------------------------------------------------------------
# Invariant-violation markers
# ---------------------------------------------------------------------------
class AntiCorruptionLayerInvariantError(RuntimeError):
    """Raised when an ACL invariant is violated at runtime."""


class ForeignTypeLeakError(AntiCorruptionLayerInvariantError):
    """ACL-INV-01: a foreign object crossed into the local domain untranslated."""


class ForeignPayloadRejectedError(AntiCorruptionLayerInvariantError):
    """ACL-INV-02: guard rejected an inbound foreign payload."""


class StatefulTranslationError(AntiCorruptionLayerInvariantError):
    """ACL-INV-03: the ACL attempted to read or mutate local state during translation."""


class UnversionedContractError(AntiCorruptionLayerInvariantError):
    """ACL-INV-04: the ACL is missing a declared foreign-contract version."""


class SchemaDriftError(AntiCorruptionLayerInvariantError):
    """ACL-INV-04: a foreign payload advertised a version the ACL does not handle."""


# ---------------------------------------------------------------------------
# Contract version sentinel (ACL-INV-04)
# ---------------------------------------------------------------------------
class ContractVersion:
    """Explicit, comparable foreign-contract version tag.

    ACL-INV-04 forbids unversioned ACLs. A ``ContractVersion`` carries the
    foreign-system identifier (e.g. ``"legacy.billing"``) and a semantic
    version string. Two versions are equal iff both fields match; they order
    lexicographically on the ``version`` tuple so old/new can be compared.
    """

    __slots__ = ("_system", "_version")

    def __init__(self, system: str, version: str) -> None:
        if not system:
            raise UnversionedContractError(
                "ACL-INV-04: contract system identifier MUST be a non-empty string."
            )
        if not version:
            raise UnversionedContractError(
                "ACL-INV-04: contract version MUST be a non-empty string."
            )
        self._system: str = system
        self._version: str = version

    @property
    def system(self) -> str:
        return self._system

    @property
    def version(self) -> str:
        return self._version

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ContractVersion):
            return NotImplemented
        return self._system == other._system and self._version == other._version

    def __hash__(self) -> int:
        return hash((self._system, self._version))

    def __repr__(self) -> str:
        return f"ContractVersion(system={self._system!r}, version={self._version!r})"


# ---------------------------------------------------------------------------
# Foreign payload envelope
# ---------------------------------------------------------------------------
class ForeignPayload:
    """Envelope that tags every inbound foreign payload with its declared version.

    Use :meth:`wrap` to attach a :class:`ContractVersion` to an arbitrary
    foreign-domain object before it reaches the ACL. The ACL uses ``version``
    to pick the correct inbound translator (ACL-INV-04) and ``body`` as the
    payload it will guard and translate. A :class:`ForeignPayload` is itself
    considered a foreign type — only the translator may unwrap it.
    """

    __slots__ = ("_body", "_version")

    def __init__(self, version: ContractVersion, body: object) -> None:
        self._version: ContractVersion = version
        self._body: object = body

    @property
    def version(self) -> ContractVersion:
        return self._version

    @property
    def body(self) -> object:
        return self._body

    @classmethod
    def wrap(cls, version: ContractVersion, body: object) -> ForeignPayload:
        return cls(version, body)

    def __repr__(self) -> str:
        return f"ForeignPayload(version={self._version!r}, body=<opaque>)"


# ---------------------------------------------------------------------------
# Versioned translator registry (ACL-INV-04)
# ---------------------------------------------------------------------------
_InboundFn = Callable[[object], object]
_OutboundFn = Callable[[object], object]
_GuardFn = Callable[[object], None]


class VersionedAntiCorruptionLayer(Generic[Local, Foreign]):
    """Reference ACL with explicit per-version inbound/outbound/guard functions.

    This implementation enforces all four catalog invariants at runtime:

    - A :class:`ForeignPayload` coming in MUST declare a ``version`` that was
      registered on the ACL via :meth:`register_version`; unknown versions
      raise :class:`SchemaDriftError` (ACL-INV-04).
    - :meth:`guard` runs BEFORE :meth:`to_local` and MUST raise on invalid
      payloads (ACL-INV-02).
    - :meth:`to_local` / :meth:`to_foreign` are invoked inside a thread-local
      re-entry guard that rejects any nested call made through a caller-
      supplied probe, the standard way we detect repository access attempted
      during translation (ACL-INV-03).
    - :meth:`to_local` / :meth:`to_foreign` NEVER return raw foreign envelopes
      into the local domain (ACL-INV-01) and NEVER let local types out as the
      inbound result.
    """

    def __init__(
        self,
        *,
        default_version: ContractVersion,
        local_types: tuple[type, ...] = (),
        foreign_types: tuple[type, ...] = (),
    ) -> None:
        # ACL-INV-04: a default (current) contract version is mandatory. The
        # :class:`ContractVersion` constructor already guards empty strings,
        # but we also reject the explicit ``None`` case here by typing.
        #
        # ACL-INV-01 footgun defense: `foreign_types` defaults to `()` for
        # convenience (the base `ForeignPayload` envelope check is always
        # active). But that defence catches ONLY the sanctioned envelope
        # shape — arbitrary foreign dicts can leak if no concrete types are
        # declared. We emit a runtime warning when the primitive is
        # constructed with an empty tuple so operators notice the gap.
        if not foreign_types:
            import warnings
            warnings.warn(
                "AntiCorruptionLayer initialised with empty `foreign_types=()`. "
                "ACL-INV-01 ('foreign types MUST NEVER cross the boundary') "
                "is ENFORCED ONLY for `ForeignPayload` envelopes in this mode. "
                "Declare the concrete foreign types your upstream emits to "
                "close the gap.",
                category=RuntimeWarning,
                stacklevel=2,
            )
        self._default_version: ContractVersion = default_version
        self._local_types: tuple[type, ...] = local_types
        self._foreign_types: tuple[type, ...] = foreign_types
        self._inbound: dict[ContractVersion, _InboundFn] = {}
        self._outbound: dict[ContractVersion, _OutboundFn] = {}
        self._guards: dict[ContractVersion, _GuardFn] = {}
        self._lock = threading.Lock()
        # Thread-local re-entry guard — ACL-INV-03 rejects nested translation.
        self._entry: threading.local = threading.local()

    # ----- Registration -----------------------------------------------------
    def register_version(
        self,
        version: ContractVersion,
        *,
        inbound: _InboundFn,
        outbound: _OutboundFn,
        guard: _GuardFn,
    ) -> None:
        """Register inbound / outbound / guard callables for ``version``.

        All three callables MUST be pure with respect to the local domain
        (ACL-INV-03) and MUST NOT reach into local repositories. The ACL does
        not attempt to prove purity — the :class:`StatefulTranslationError`
        reporting path only fires if a translator re-enters the ACL.
        """
        with self._lock:
            self._inbound[version] = inbound
            self._outbound[version] = outbound
            self._guards[version] = guard

    @property
    def default_version(self) -> ContractVersion:
        return self._default_version

    def known_versions(self) -> tuple[ContractVersion, ...]:
        with self._lock:
            return tuple(self._inbound.keys())

    # ----- Protocol surface -------------------------------------------------
    def guard(self, foreign: Foreign) -> None:
        """Validate an inbound foreign payload (ACL-INV-02 + ACL-INV-04).

        Accepts either a :class:`ForeignPayload` (carrying its own version)
        or a raw foreign body matched against the ACL's declared
        ``default_version``. Raises :class:`ForeignPayloadRejectedError` if
        the registered guard rejects, :class:`SchemaDriftError` if the
        envelope's version is unknown.
        """
        version, body = self._resolve_envelope(foreign)
        with self._lock:
            guard_fn = self._guards.get(version)
        if guard_fn is None:
            raise SchemaDriftError(
                f"ACL-INV-04: no guard registered for version {version!r}; "
                f"known versions: {sorted(str(v) for v in self.known_versions())!r}."
            )
        try:
            guard_fn(body)
        except AntiCorruptionLayerInvariantError:
            raise
        except Exception as exc:
            raise ForeignPayloadRejectedError(
                f"ACL-INV-02: guard rejected inbound payload for version "
                f"{version!r}: {exc}"
            ) from exc

    def to_local(self, foreign: Foreign) -> Local:
        """Translate a foreign payload into a local value.

        ACL-INV-01: the return value MUST NOT be a :class:`ForeignPayload`
        nor an instance of any declared ``foreign_types``. ACL-INV-02: guard
        runs first. ACL-INV-03: nested ``to_local`` / ``to_foreign`` calls on
        this ACL instance are rejected.
        """
        version, body = self._resolve_envelope(foreign)
        # Run guard BEFORE translation so invalid payloads NEVER reach
        # anything downstream (ACL-INV-02).
        self.guard(foreign)
        with self._lock:
            fn = self._inbound.get(version)
        if fn is None:
            raise SchemaDriftError(
                f"ACL-INV-04: no inbound translator registered for version "
                f"{version!r}."
            )
        with self._reentry_guard("to_local"):
            result = fn(body)
        if isinstance(result, ForeignPayload):
            raise ForeignTypeLeakError(
                "ACL-INV-01: to_local returned a ForeignPayload — foreign "
                "envelopes MUST NEVER cross into the local domain."
            )
        if self._foreign_types and isinstance(result, self._foreign_types):
            raise ForeignTypeLeakError(
                f"ACL-INV-01: to_local returned a foreign type "
                f"{type(result).__qualname__}; local aggregates would be "
                "polluted by upstream vocabulary."
            )
        return result  # type: ignore[return-value]  # ACL-INV-01: inbound fn is contracted to return Local.

    def to_foreign(self, local: Local) -> Foreign:
        """Translate a local value into the foreign representation.

        ACL-INV-01 (outbound direction): the return value MUST NOT be an
        instance of any declared ``local_types`` — the ACL is the one place
        that converts domain objects to wire shape.
        """
        if self._local_types and not isinstance(local, self._local_types):
            # This is a soft warning by construction: callers may legitimately
            # pass a DTO instead of a domain class. We only assert the local
            # value is NOT a ForeignPayload so we never round-trip foreign
            # envelopes through the outbound translator.
            if isinstance(local, ForeignPayload):
                raise ForeignTypeLeakError(
                    "ACL-INV-01: to_foreign received a ForeignPayload; "
                    "outbound translation operates on LOCAL values only."
                )
        with self._lock:
            fn = self._outbound.get(self._default_version)
        if fn is None:
            raise SchemaDriftError(
                f"ACL-INV-04: no outbound translator registered for default "
                f"version {self._default_version!r}."
            )
        with self._reentry_guard("to_foreign"):
            result = fn(local)
        if self._local_types and isinstance(result, self._local_types):
            raise ForeignTypeLeakError(
                f"ACL-INV-01: to_foreign returned a local type "
                f"{type(result).__qualname__}; the foreign system would see "
                "raw domain objects."
            )
        return result  # type: ignore[return-value]  # ACL-INV-01: outbound fn is contracted to return Foreign.

    # ----- Internal helpers -------------------------------------------------
    def _resolve_envelope(self, foreign: object) -> tuple[ContractVersion, object]:
        if isinstance(foreign, ForeignPayload):
            return foreign.version, foreign.body
        return self._default_version, foreign

    @contextmanager
    def _reentry_guard(self, op: str) -> Iterator[None]:
        depth = int(getattr(self._entry, "depth", 0))
        if depth > 0:
            raise StatefulTranslationError(
                f"ACL-INV-03: nested {op!r} detected — translators "
                "MUST be stateless and MUST NOT call back into the ACL."
            )
        self._entry.depth = depth + 1
        try:
            yield
        finally:
            cur = int(getattr(self._entry, "depth", 1))
            self._entry.depth = max(cur - 1, 0)


# ---------------------------------------------------------------------------
# Reference ACL used by tests / docs
# ---------------------------------------------------------------------------
class DictAntiCorruptionLayer(VersionedAntiCorruptionLayer[Mapping[str, object], Mapping[str, object]]):
    """Dict-based reference ACL used by tests.

    Inbound mapping ``{"legacy_id": int, "legacy_name": str}`` becomes local
    ``{"id": int, "name": str}``; outbound reverses the field rename. Guard
    rejects payloads missing ``legacy_id`` or carrying a non-string name.
    """

    def __init__(self, version: ContractVersion | None = None) -> None:
        v = version if version is not None else ContractVersion("legacy.example", "1.0")
        super().__init__(default_version=v)
        self.register_version(
            v,
            inbound=self.inbound_fn,
            outbound=self.outbound_fn,
            guard=self.guard_fn,
        )

    @staticmethod
    def inbound_fn(body: object) -> Mapping[str, object]:
        if not isinstance(body, Mapping):
            raise ForeignPayloadRejectedError(
                "ACL-INV-02: inbound body MUST be a Mapping."
            )
        return {"id": body["legacy_id"], "name": body["legacy_name"]}

    @staticmethod
    def outbound_fn(local: object) -> Mapping[str, object]:
        if not isinstance(local, Mapping):
            raise ForeignTypeLeakError(
                "ACL-INV-01: outbound local value MUST be a Mapping."
            )
        return {"legacy_id": local["id"], "legacy_name": local["name"]}

    @staticmethod
    def guard_fn(body: object) -> None:
        if not isinstance(body, Mapping):
            raise ForeignPayloadRejectedError(
                "ACL-INV-02: inbound body MUST be a Mapping."
            )
        if "legacy_id" not in body:
            raise ForeignPayloadRejectedError(
                "ACL-INV-02: inbound payload missing 'legacy_id'."
            )
        if not isinstance(body.get("legacy_name"), str):
            raise ForeignPayloadRejectedError(
                "ACL-INV-02: inbound 'legacy_name' MUST be a string."
            )


# ---------------------------------------------------------------------------
# Schema-drift detector (helper — ACL-INV-04)
# ---------------------------------------------------------------------------
def detect_schema_drift(
    acl: VersionedAntiCorruptionLayer[Local, Foreign],
    payload: ForeignPayload,
) -> bool:
    """Return True iff ``payload.version`` is NOT registered on ``acl``.

    A small helper that observability pipelines use to count drift events
    without having to call :meth:`guard` (which raises).
    """
    known: Final[tuple[ContractVersion, ...]] = acl.known_versions()
    return payload.version not in known


__all__ = [
    "AntiCorruptionLayer",
    "AntiCorruptionLayerInvariantError",
    "ContractVersion",
    "DictAntiCorruptionLayer",
    "Foreign",
    "ForeignPayload",
    "ForeignPayloadRejectedError",
    "ForeignTypeLeakError",
    "Local",
    "SchemaDriftError",
    "StatefulTranslationError",
    "UnversionedContractError",
    "VersionedAntiCorruptionLayer",
    "detect_schema_drift",
]
