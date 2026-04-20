"""BoundedContext primitive — Evans/Vernon DDD model-and-language boundary.

Implements the catalog Protocol for `data.BoundedContext` and installs runtime
invariant checkers. The module performs zero I/O at import.

A BoundedContext is a named boundary inside which ONE ubiquitous language and
ONE set of invariants apply. Aggregate types are owned by exactly one context;
integration with other contexts MUST go through a published relationship on a
ContextMap (Partnership, Customer-Supplier, Conformist, Open Host) and MUST be
translated by an AntiCorruptionLayer — raw object sharing across contexts is
NEVER permitted.

Invariant IDs cited by this module:

- BC-INV-01: every Aggregate type MUST be owned by exactly one BoundedContext;
  shared ownership across contexts is FORBIDDEN.
- BC-INV-02: cross-context calls MUST pass through an AntiCorruptionLayer or a
  published-language schema; raw object sharing is NEVER permitted.
- BC-INV-03: the ubiquitous language of a context SHALL be locally consistent:
  one term CANNOT carry two meanings inside the same BoundedContext.
- BC-INV-04: a BoundedContext ALWAYS exposes its integration points through a
  ContextMap relationship (Customer-Supplier, Conformist, Partnership, Open
  Host).
"""

from __future__ import annotations

import threading
from collections.abc import Iterable, Mapping
from typing import Final, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Canonical relationship kinds (BC-INV-04)
# ---------------------------------------------------------------------------
REL_PARTNERSHIP: Final[str] = "Partnership"
REL_CUSTOMER_SUPPLIER: Final[str] = "Customer-Supplier"
REL_CONFORMIST: Final[str] = "Conformist"
REL_OPEN_HOST: Final[str] = "Open Host"
REL_ACL: Final[str] = "Anticorruption Layer"

CANONICAL_RELATIONSHIPS: Final[frozenset[str]] = frozenset(
    {
        REL_PARTNERSHIP,
        REL_CUSTOMER_SUPPLIER,
        REL_CONFORMIST,
        REL_OPEN_HOST,
        REL_ACL,
    }
)


# ---------------------------------------------------------------------------
# Protocol surface (matches catalog api_signature verbatim)
# ---------------------------------------------------------------------------
@runtime_checkable
class BoundedContext(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def language(self) -> Mapping[str, str]: ...
    def owns(self, aggregate_type: type) -> bool: ...
    def translator_to(self, other: BoundedContext) -> object: ...


# ---------------------------------------------------------------------------
# Invariant-violation markers
# ---------------------------------------------------------------------------
class BoundedContextInvariantError(RuntimeError):
    """Raised when a BoundedContext invariant is violated at runtime."""


class SharedOwnershipError(BoundedContextInvariantError):
    """BC-INV-01: an Aggregate type was claimed by more than one context."""


class UbiquitousLanguageConflictError(BoundedContextInvariantError):
    """BC-INV-03: a term was re-defined with a different meaning inside a context."""


class CrossContextLeakError(BoundedContextInvariantError):
    """BC-INV-02: a raw cross-context object reference was detected."""


class UnmappedIntegrationError(BoundedContextInvariantError):
    """BC-INV-04: an integration between contexts is not registered on the ContextMap."""


# ---------------------------------------------------------------------------
# AntiCorruptionLayer — minimal translator surface (BC-INV-02)
# ---------------------------------------------------------------------------
class AntiCorruptionLayer(Protocol):
    """Translator surface between two BoundedContexts.

    Implementations MUST be stateless with respect to the local domain and
    MUST validate inbound payloads before they reach any local aggregate.
    """

    def to_local(self, foreign: object) -> object: ...
    def to_foreign(self, local: object) -> object: ...
    def guard(self, foreign: object) -> None: ...


# ---------------------------------------------------------------------------
# ContextMap — registry of integrations (BC-INV-04)
# ---------------------------------------------------------------------------
class ContextMap:
    """Registry of (upstream, downstream) → relationship kind.

    Every pairwise integration between BoundedContexts MUST be classified by
    one of :data:`CANONICAL_RELATIONSHIPS`. Relationship mutations are always
    explicit and thread-safe.
    """

    def __init__(self) -> None:
        self._edges: dict[tuple[str, str], str] = {}
        self._sealed: bool = False
        self._lock = threading.Lock()

    def seal(self) -> None:
        """BC-INV-04: freeze the integration map. Post-seal, `add_relationship`
        raises. Operators MUST seal the map once the deployment topology is
        decided so runtime reclassification (e.g. ACL silently downgraded to
        Conformist) becomes a loud error."""
        with self._lock:
            self._sealed = True

    @property
    def sealed(self) -> bool:
        with self._lock:
            return self._sealed

    def add_relationship(self, upstream: str, downstream: str, kind: str) -> None:
        if kind not in CANONICAL_RELATIONSHIPS:
            raise UnmappedIntegrationError(
                f"BC-INV-04: relationship kind {kind!r} is not canonical; "
                f"expected one of {sorted(CANONICAL_RELATIONSHIPS)!r}."
            )
        if upstream == downstream:
            raise UnmappedIntegrationError(
                "BC-INV-04: a context CANNOT integrate with itself."
            )
        with self._lock:
            if self._sealed:
                raise UnmappedIntegrationError(
                    "BC-INV-04: context map is sealed; add_relationship refused. "
                    "Unseal is NOT exposed by design — stand up a new map."
                )
            existing = self._edges.get((upstream, downstream))
            if existing is not None and existing != kind:
                raise UnmappedIntegrationError(
                    f"BC-INV-04: relationship {upstream!r}→{downstream!r} is "
                    f"already {existing!r}; cannot silently reclassify to {kind!r}. "
                    f"Remove and re-add with intent if reclassification is genuinely wanted."
                )
            self._edges[(upstream, downstream)] = kind

    def relationship(self, upstream: str, downstream: str) -> str:
        with self._lock:
            edge = self._edges.get((upstream, downstream))
        if edge is None:
            raise UnmappedIntegrationError(
                f"BC-INV-04: no registered integration between {upstream!r} and "
                f"{downstream!r}; shadow integrations are FORBIDDEN."
            )
        return edge

    def integrations(self) -> Iterable[tuple[str, str, str]]:
        with self._lock:
            return tuple((u, d, k) for (u, d), k in self._edges.items())

    def contexts(self) -> Iterable[str]:
        with self._lock:
            names: set[str] = set()
            for u, d in self._edges:
                names.add(u)
                names.add(d)
            return tuple(sorted(names))

    def has_relationship(self, upstream: str, downstream: str) -> bool:
        with self._lock:
            return (upstream, downstream) in self._edges


# ---------------------------------------------------------------------------
# Global ownership ledger (BC-INV-01)
# ---------------------------------------------------------------------------
class _OwnershipLedger:
    """Process-wide ledger mapping Aggregate type → owning context name.

    BC-INV-01 enforces single-ownership: once an aggregate type is registered
    to a context, any attempt to register it to a different context raises
    :class:`SharedOwnershipError`. Registering the same (type, context) pair
    twice is idempotent.
    """

    def __init__(self) -> None:
        self._by_type: dict[type, str] = {}
        self._lock = threading.Lock()

    def claim(self, aggregate_type: type, context_name: str) -> None:
        with self._lock:
            existing = self._by_type.get(aggregate_type)
            if existing is not None and existing != context_name:
                raise SharedOwnershipError(
                    f"BC-INV-01: aggregate type {aggregate_type.__qualname__} is "
                    f"already owned by context {existing!r}; shared ownership "
                    f"across contexts is FORBIDDEN (attempted owner: {context_name!r})."
                )
            self._by_type[aggregate_type] = context_name

    def release(self, aggregate_type: type, context_name: str) -> None:
        with self._lock:
            existing = self._by_type.get(aggregate_type)
            if existing == context_name:
                del self._by_type[aggregate_type]

    def owner_of(self, aggregate_type: type) -> str | None:
        with self._lock:
            return self._by_type.get(aggregate_type)


_LEDGER: Final[_OwnershipLedger] = _OwnershipLedger()


def _global_ledger() -> _OwnershipLedger:
    """Return the process-wide ownership ledger (BC-INV-01)."""
    return _LEDGER


# ---------------------------------------------------------------------------
# Reference BoundedContext implementation
# ---------------------------------------------------------------------------
class SimpleBoundedContext:
    """Reference BoundedContext enforcing the four catalog invariants.

    - Aggregate types registered via :meth:`claim` are recorded in the global
      ledger (BC-INV-01); re-claiming an existing type from another context
      raises :class:`SharedOwnershipError`.
    - The ubiquitous language is locally consistent: once a term is mapped to
      a definition, re-mapping it to a different definition raises
      :class:`UbiquitousLanguageConflictError` (BC-INV-03).
    - Cross-context translation goes through a registered
      :class:`AntiCorruptionLayer`; direct object sharing raises
      :class:`CrossContextLeakError` (BC-INV-02).
    - Integrations MUST be declared on a :class:`ContextMap` via
      :meth:`publish_integration` (BC-INV-04).
    """

    def __init__(
        self,
        name: str,
        *,
        context_map: ContextMap | None = None,
        language: Mapping[str, str] | None = None,
        ledger: _OwnershipLedger | None = None,
    ) -> None:
        if not name:
            raise BoundedContextInvariantError(
                "BC-INV-01: BoundedContext.name MUST be a non-empty identifier."
            )
        self._name = name
        self._context_map: ContextMap = context_map if context_map is not None else ContextMap()
        self._language: dict[str, str] = dict(language) if language is not None else {}
        self._ledger: _OwnershipLedger = ledger if ledger is not None else _LEDGER
        self._translators: dict[str, AntiCorruptionLayer] = {}
        self._aggregate_types: set[type] = set()
        self._lock = threading.Lock()

    # ----- Protocol surface --------------------------------------------------
    @property
    def name(self) -> str:
        return self._name

    @property
    def language(self) -> Mapping[str, str]:
        # Return an immutable view so callers CANNOT mutate the glossary.
        with self._lock:
            return dict(self._language)

    def owns(self, aggregate_type: type) -> bool:
        with self._lock:
            return aggregate_type in self._aggregate_types

    def translator_to(self, other: BoundedContext) -> object:
        other_name = other.name
        with self._lock:
            translator = self._translators.get(other_name)
        if translator is None:
            raise CrossContextLeakError(
                f"BC-INV-02: no AntiCorruptionLayer registered from {self._name!r} "
                f"to {other_name!r}; cross-context calls MUST be translated."
            )
        return translator

    # ----- claim / language --------------------------------------------------
    def claim(self, aggregate_type: type) -> None:
        """Register ownership of an aggregate type with this context.

        BC-INV-01: a type already owned by another context is rejected.
        """
        self._ledger.claim(aggregate_type, self._name)
        with self._lock:
            self._aggregate_types.add(aggregate_type)

    def define_term(self, term: str, meaning: str) -> None:
        """Add an entry to the ubiquitous language.

        BC-INV-03: re-defining a term with a different meaning is rejected.
        Re-defining with the SAME meaning is idempotent.
        """
        if not term:
            raise UbiquitousLanguageConflictError(
                "BC-INV-03: language term MUST be a non-empty identifier."
            )
        with self._lock:
            existing = self._language.get(term)
            if existing is not None and existing != meaning:
                raise UbiquitousLanguageConflictError(
                    f"BC-INV-03: term {term!r} is already defined inside context "
                    f"{self._name!r} as {existing!r}; redefining to {meaning!r} "
                    f"would break local linguistic consistency."
                )
            self._language[term] = meaning

    # ----- integrations ------------------------------------------------------
    def publish_integration(
        self,
        other: BoundedContext,
        kind: str,
        *,
        direction: str = "downstream",
        translator: AntiCorruptionLayer | None = None,
    ) -> None:
        """Publish an integration between this context and ``other``.

        ``direction="downstream"`` means ``self`` is upstream; ``"upstream"``
        means ``other`` is upstream. When ``kind`` involves translation
        (Conformist / Customer-Supplier / ACL) a translator MUST be provided
        so cross-context calls (BC-INV-02) never see raw foreign objects.
        """
        if direction not in ("upstream", "downstream"):
            raise UnmappedIntegrationError(
                f"BC-INV-04: direction MUST be 'upstream' or 'downstream'; got {direction!r}."
            )
        # BC-INV-02: validate translator requirement BEFORE mutating the map so
        # a rejected publish NEVER leaves a partial edge behind.
        requires_translator = kind in {REL_CONFORMIST, REL_CUSTOMER_SUPPLIER, REL_ACL}
        if requires_translator and translator is None:
            raise CrossContextLeakError(
                f"BC-INV-02: relationship {kind!r} with {other.name!r} requires an "
                "AntiCorruptionLayer so foreign payloads are translated before "
                "entering the local context."
            )
        upstream = self._name if direction == "downstream" else other.name
        downstream = other.name if direction == "downstream" else self._name
        self._context_map.add_relationship(upstream, downstream, kind)
        if requires_translator and translator is not None:
            with self._lock:
                self._translators[other.name] = translator

    def register_translator(self, other_name: str, translator: AntiCorruptionLayer) -> None:
        """Register an ACL translator for an already-published integration."""
        with self._lock:
            self._translators[other_name] = translator

    # ----- runtime cross-context guard (BC-INV-02) --------------------------
    def forward(
        self,
        other: BoundedContext,
        payload: object,
        *,
        local_types: tuple[type, ...] = (),
    ) -> object:
        """Forward a payload to ``other`` through the registered translator.

        If ``payload`` is an instance of any type in ``local_types`` (i.e. a
        raw local domain object), the call is rejected — callers MUST pass a
        published-language payload, or go through the translator explicitly.
        """
        if local_types and isinstance(payload, local_types):
            raise CrossContextLeakError(
                f"BC-INV-02: raw local object of type "
                f"{type(payload).__qualname__} CANNOT cross the boundary "
                f"from {self._name!r} to {other.name!r}; translate via the ACL."
            )
        translator = self.translator_to(other)
        acl: AntiCorruptionLayer = translator  # type: ignore[assignment]  # BC-INV-02: translator_to returns an ACL
        acl.guard(payload)
        return acl.to_foreign(payload)

    # ----- introspection -----------------------------------------------------
    @property
    def context_map(self) -> ContextMap:
        return self._context_map

    def owned_types(self) -> tuple[type, ...]:
        with self._lock:
            return tuple(self._aggregate_types)


# ---------------------------------------------------------------------------
# Reference ACL used by tests / docs
# ---------------------------------------------------------------------------
class NoopAntiCorruptionLayer:
    """Reference pass-through ACL used by tests.

    Real ACLs validate foreign payloads and translate them to local
    representations; this one is a minimal stand-in that records calls.
    """

    def __init__(self) -> None:
        self.guarded: list[object] = []
        self.to_local_calls: list[object] = []
        self.to_foreign_calls: list[object] = []

    def guard(self, foreign: object) -> None:
        self.guarded.append(foreign)

    def to_local(self, foreign: object) -> object:
        self.to_local_calls.append(foreign)
        return {"local_of": foreign}

    def to_foreign(self, local: object) -> object:
        self.to_foreign_calls.append(local)
        return {"foreign_of": local}


__all__ = [
    "CANONICAL_RELATIONSHIPS",
    "REL_ACL",
    "REL_CONFORMIST",
    "REL_CUSTOMER_SUPPLIER",
    "REL_OPEN_HOST",
    "REL_PARTNERSHIP",
    "AntiCorruptionLayer",
    "BoundedContext",
    "BoundedContextInvariantError",
    "ContextMap",
    "CrossContextLeakError",
    "NoopAntiCorruptionLayer",
    "SharedOwnershipError",
    "SimpleBoundedContext",
    "UbiquitousLanguageConflictError",
    "UnmappedIntegrationError",
]
