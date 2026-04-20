"""Specification primitive — Evans/Fowler DDD composable predicate pattern.

Implements the catalog Protocol for `data.Specification` and installs runtime
invariant checkers. The module performs zero I/O at import.

Invariant IDs cited by this module:

- SPEC-INV-01: ``is_satisfied_by`` MUST be a pure predicate — no I/O, no
  mutation of the candidate, and NEVER time-dependent unless time is injected.
- SPEC-INV-02: composed specifications (``and_``, ``or_``, ``not_``) MUST
  preserve the identity laws of boolean algebra so refactors CANNOT change
  semantics (double-negation, De Morgan, commutativity, associativity).
- SPEC-INV-03: a Specification CANNOT depend on the persistence layer;
  repository translation MUST be delegated to a separate visitor/translator
  stored in a dedicated registry.
- SPEC-INV-04: the same Specification used for in-memory filtering and
  repository querying SHALL produce logically equivalent results.
- SPEC-INV-05: composition operators (``and_`` / ``or_`` / ``not_``) SHALL
  NOT be overridden by subclasses; only ``is_satisfied_by`` MAY be overridden.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from typing import Final, Generic, Protocol, TypeVar, runtime_checkable

# ---------------------------------------------------------------------------
# Type variables (matches catalog api_signature verbatim)
# ---------------------------------------------------------------------------
T = TypeVar("T")


# ---------------------------------------------------------------------------
# Protocol surface (matches catalog api_signature verbatim)
# ---------------------------------------------------------------------------
@runtime_checkable
class Specification(Protocol, Generic[T]):
    def is_satisfied_by(self, candidate: T) -> bool: ...
    def and_(self, other: Specification[T]) -> Specification[T]: ...
    def or_(self, other: Specification[T]) -> Specification[T]: ...
    def not_(self) -> Specification[T]: ...


# ---------------------------------------------------------------------------
# Invariant-violation marker
# ---------------------------------------------------------------------------
class SpecificationInvariantError(RuntimeError):
    """Raised when a Specification invariant is violated at runtime."""


# ---------------------------------------------------------------------------
# Composition node kinds — closed algebra (SPEC-INV-05 prevents subclass override)
# ---------------------------------------------------------------------------
_KIND_LEAF: Final[str] = "leaf"
_KIND_AND: Final[str] = "and"
_KIND_OR: Final[str] = "or"
_KIND_NOT: Final[str] = "not"

_ALL_KINDS: Final[frozenset[str]] = frozenset({_KIND_LEAF, _KIND_AND, _KIND_OR, _KIND_NOT})


# ---------------------------------------------------------------------------
# Forbidden attribute names that a subclass MUST NOT override (SPEC-INV-05).
# These names form the closed boolean algebra; subclasses only override
# ``is_satisfied_by``.
# ---------------------------------------------------------------------------
_SEALED_OPERATORS: Final[frozenset[str]] = frozenset({
    "and_", "or_", "not_",
    "_kind", "_children", "_negated",
})


# ---------------------------------------------------------------------------
# Reference base implementation
# ---------------------------------------------------------------------------
class BaseSpecification(Generic[T]):
    """Reference Specification base that enforces the catalog invariants.

    Subclasses override ``is_satisfied_by`` to define a leaf predicate. The
    composition operators (``and_``, ``or_``, ``not_``) live on this base
    class and are SEALED — overriding them in a subclass raises
    ``SpecificationInvariantError`` on class creation (SPEC-INV-05).

    The class is intentionally hashable-by-identity and immutable: a
    specification's semantics MUST NOT change after construction, which keeps
    ``is_satisfied_by`` side-effect free (SPEC-INV-01) and the algebra stable
    (SPEC-INV-02).
    """

    # Leaf kind by default; composite subclasses override ``_kind``.
    _kind: str = _KIND_LEAF

    def __init_subclass__(cls, **kwargs: object) -> None:
        # SPEC-INV-05: subclasses MAY NOT override the algebra operators.
        # ``_CompositeSpecification`` / ``_NotSpecification`` are the only
        # internal subclasses that set ``_algebra_impl = True`` to opt-in.
        super().__init_subclass__(**kwargs)
        algebra_impl = getattr(cls, "_algebra_impl", False)
        if algebra_impl:
            return
        for name in ("and_", "or_", "not_"):
            if name in cls.__dict__:
                raise SpecificationInvariantError(
                    f"SPEC-INV-05: subclass {cls.__name__!r} overrides sealed "
                    f"operator {name!r}; only is_satisfied_by MAY be overridden."
                )

    # ----- predicate contract (SPEC-INV-01) ---------------------------------
    def is_satisfied_by(self, candidate: T) -> bool:
        raise NotImplementedError(
            "SPEC-INV-01: concrete Specification subclasses MUST override is_satisfied_by."
        )

    # ----- boolean algebra (SPEC-INV-02) ------------------------------------
    def and_(self, other: BaseSpecification[T]) -> BaseSpecification[T]:
        if not isinstance(other, BaseSpecification):
            raise SpecificationInvariantError(
                "SPEC-INV-02: and_ operand MUST be a Specification; got "
                f"{type(other).__name__}."
            )
        return _AndSpecification(self, other)

    def or_(self, other: BaseSpecification[T]) -> BaseSpecification[T]:
        if not isinstance(other, BaseSpecification):
            raise SpecificationInvariantError(
                "SPEC-INV-02: or_ operand MUST be a Specification; got "
                f"{type(other).__name__}."
            )
        return _OrSpecification(self, other)

    def not_(self) -> BaseSpecification[T]:
        # Double-negation collapses (SPEC-INV-02 — NOT NOT x == x).
        if isinstance(self, _NotSpecification):
            return self._inner
        return _NotSpecification(self)

    # ----- introspection helpers (SPEC-INV-03 — translator reads these) -----
    @property
    def kind(self) -> str:
        return self._kind

    def children(self) -> tuple[BaseSpecification[T], ...]:
        """Return child specifications for tree traversal — empty tuple for leaves."""
        return ()

    def __repr__(self) -> str:
        return f"{type(self).__name__}(kind={self._kind})"


# ---------------------------------------------------------------------------
# Internal composite nodes (SPEC-INV-02 enforces closed algebra)
# ---------------------------------------------------------------------------
class _AndSpecification(BaseSpecification[T]):
    _kind = _KIND_AND
    _algebra_impl = True

    def __init__(self, left: BaseSpecification[T], right: BaseSpecification[T]) -> None:
        self._left = left
        self._right = right

    def is_satisfied_by(self, candidate: T) -> bool:
        # Short-circuit left; both sides are pure (SPEC-INV-01).
        return self._left.is_satisfied_by(candidate) and self._right.is_satisfied_by(candidate)

    def children(self) -> tuple[BaseSpecification[T], ...]:
        return (self._left, self._right)


class _OrSpecification(BaseSpecification[T]):
    _kind = _KIND_OR
    _algebra_impl = True

    def __init__(self, left: BaseSpecification[T], right: BaseSpecification[T]) -> None:
        self._left = left
        self._right = right

    def is_satisfied_by(self, candidate: T) -> bool:
        return self._left.is_satisfied_by(candidate) or self._right.is_satisfied_by(candidate)

    def children(self) -> tuple[BaseSpecification[T], ...]:
        return (self._left, self._right)


class _NotSpecification(BaseSpecification[T]):
    _kind = _KIND_NOT
    _algebra_impl = True

    def __init__(self, inner: BaseSpecification[T]) -> None:
        self._inner = inner

    def is_satisfied_by(self, candidate: T) -> bool:
        return not self._inner.is_satisfied_by(candidate)

    def children(self) -> tuple[BaseSpecification[T], ...]:
        return (self._inner,)


# ---------------------------------------------------------------------------
# Predicate-backed leaf helper — build a leaf from a pure callable
# ---------------------------------------------------------------------------
class PredicateSpecification(BaseSpecification[T]):
    """Leaf Specification backed by a pure predicate callable.

    The callable MUST be side-effect free and MUST NOT mutate the candidate
    (SPEC-INV-01). This class stores an immutable name used for translator
    dispatch (SPEC-INV-03).
    """

    _kind = _KIND_LEAF

    def __init__(self, name: str, predicate: Callable[[T], bool]) -> None:
        if not name or not name.isidentifier():
            raise SpecificationInvariantError(
                "SPEC-INV-03: leaf Specification name MUST be a non-empty Python "
                f"identifier for translator dispatch; got {name!r}."
            )
        self._name = name
        self._predicate = predicate

    @property
    def name(self) -> str:
        return self._name

    def is_satisfied_by(self, candidate: T) -> bool:
        return bool(self._predicate(candidate))


# ---------------------------------------------------------------------------
# Translator registry (SPEC-INV-03)
# ---------------------------------------------------------------------------
# A Translator converts a Specification tree to a backend-specific query
# representation (SQL WHERE fragment, Mongo filter doc, etc.). The
# Specification itself is PERSISTENCE-FREE; the registry is the only place
# backend coupling is allowed.
TranslatorFn = Callable[[BaseSpecification[object]], object]


class TranslatorRegistry:
    """Thread-safe registry of leaf-name → translator function per backend.

    The registry carries shared state across the process (SPEC-INV-03):
    translators are installed once per backend at boot and read under a lock
    so concurrent query translations stay linearizable.
    """

    def __init__(self) -> None:
        self._translators: dict[str, dict[str, TranslatorFn]] = {}
        self._lock = threading.Lock()

    def register(self, backend: str, leaf_name: str, fn: TranslatorFn) -> None:
        if not backend or not backend.isidentifier():
            raise SpecificationInvariantError(
                "SPEC-INV-03: backend name MUST be a non-empty identifier."
            )
        if not leaf_name or not leaf_name.isidentifier():
            raise SpecificationInvariantError(
                "SPEC-INV-03: leaf_name MUST be a non-empty identifier."
            )
        with self._lock:
            bucket = self._translators.setdefault(backend, {})
            bucket[leaf_name] = fn

    def translate(self, backend: str, spec: BaseSpecification[object]) -> object:
        """Translate a Specification tree into a backend-specific query object.

        Composite nodes (``and``/``or``/``not``) are delegated recursively.
        Leaves dispatch via the registered translator for the given backend.
        """
        with self._lock:
            backend_map = dict(self._translators.get(backend, {}))
        return self._translate_node(backend, spec, backend_map)

    def _translate_node(
        self,
        backend: str,
        spec: BaseSpecification[object],
        backend_map: dict[str, TranslatorFn],
    ) -> object:
        kind = spec.kind
        if kind == _KIND_AND:
            left, right = spec.children()
            return {
                "op": "AND",
                "left": self._translate_node(backend, left, backend_map),
                "right": self._translate_node(backend, right, backend_map),
            }
        if kind == _KIND_OR:
            left, right = spec.children()
            return {
                "op": "OR",
                "left": self._translate_node(backend, left, backend_map),
                "right": self._translate_node(backend, right, backend_map),
            }
        if kind == _KIND_NOT:
            (inner,) = spec.children()
            return {
                "op": "NOT",
                "inner": self._translate_node(backend, inner, backend_map),
            }
        # Leaf
        if not isinstance(spec, PredicateSpecification):
            raise SpecificationInvariantError(
                "SPEC-INV-03: leaf Specification MUST expose a registered name "
                "via PredicateSpecification; opaque leaves CANNOT be translated."
            )
        fn = backend_map.get(spec.name)
        if fn is None:
            raise SpecificationInvariantError(
                f"SPEC-INV-03: no translator registered for backend={backend!r} "
                f"leaf={spec.name!r}; extend the registry at boot."
            )
        return fn(spec)


# ---------------------------------------------------------------------------
# Parity helper (SPEC-INV-04)
# ---------------------------------------------------------------------------
def in_memory_filter(
    spec: BaseSpecification[T],
    candidates: Iterable[T],
) -> list[T]:
    """Apply a Specification in-memory — the reference filter path.

    ``SPEC-INV-04`` demands that repository-side translation yield an
    equivalent result set. This helper is the authoritative in-memory side
    used by parity tests.
    """
    return [c for c in candidates if spec.is_satisfied_by(c)]


# ---------------------------------------------------------------------------
# Default global registry — convenience boot target for downstream code
# ---------------------------------------------------------------------------
default_registry: Final[TranslatorRegistry] = TranslatorRegistry()


__all__ = [
    "BaseSpecification",
    "PredicateSpecification",
    "Specification",
    "SpecificationInvariantError",
    "TranslatorFn",
    "TranslatorRegistry",
    "default_registry",
    "in_memory_filter",
]
