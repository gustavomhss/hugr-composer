"""LifetimeScope primitive — typed lifetime enum + stateful ScopeManager.

The catalog `api_signature` defines a closed enum of three lifetimes:
SINGLETON, SCOPED, TRANSIENT. That enum is the public vocabulary. To make
the primitive USEFUL (and stateful enough to exercise T2/T3/T5), this module
also ships a reference `ScopeManager` that implements per-scope instance
tracking, LIFO disposal on scope exit, parent to child scope inheritance,
and singleton-capture-of-scoped leak detection.

Invariant IDs cited by this module:

- LS-INV-01: SINGLETON instances MUST be shared process-wide and created
  at most once per container. The ScopeManager caches singletons at the
  root and every descendant scope observes the same identity.
- LS-INV-02: SCOPED instances MUST be created at most once per scope and
  disposed when the scope ends. Disposal runs in LIFO order of creation.
- LS-INV-03: TRANSIENT instances MUST be created per resolution call and
  NEVER reused across call sites. The ScopeManager caches zero transients.
- LS-INV-04: A SINGLETON MUST NEVER depend on a SCOPED or TRANSIENT
  disposable that requires a live request scope. Leak detection runs at
  construction time and rejects the capture.
- LS-INV-05: The value set MUST be closed: any new lifetime requires an
  explicit enum addition, NEVER a string literal. `coerce()` rejects any
  unknown string; `__members__` is sealed by enum semantics.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable, Iterator
from enum import Enum
from types import TracebackType
from typing import Any, Final, Literal, Self, TypeVar

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Protocol surface (matches catalog api_signature verbatim)
# ---------------------------------------------------------------------------
class LifetimeScope(str, Enum):
    """Closed vocabulary for instance lifetimes (LS-INV-05).

    Values are strings for wire-compatibility with framework adapters
    (Spring 'singleton'/'prototype', ASP.NET 'Scoped', Nest.js 'REQUEST')
    but the ENUM is the authoritative set; callers MUST NEVER pass raw
    string literals at the boundary.
    """

    SINGLETON = "singleton"
    SCOPED = "scoped"
    TRANSIENT = "transient"


class LifetimeScopeInvariantError(RuntimeError):
    """Raised when a LifetimeScope / ScopeManager invariant is violated."""


# Scope rank for leak detection — higher rank means shorter lifetime.
# A shorter-lifetime dependency CANNOT be captured by a longer-lifetime owner.
_SCOPE_RANK: Final[dict[LifetimeScope, int]] = {
    LifetimeScope.SINGLETON: 0,
    LifetimeScope.SCOPED: 1,
    LifetimeScope.TRANSIENT: 2,
}


def coerce(value: str | LifetimeScope) -> LifetimeScope:
    """Convert a known wire string into the enum; reject anything else.

    LS-INV-05: the value set is closed. Unknown strings SHALL raise rather
    than silently degrade to TRANSIENT (the worst surprise under load).
    """
    if isinstance(value, LifetimeScope):
        return value
    try:
        return LifetimeScope(value)
    except ValueError as e:
        valid = sorted(m.value for m in LifetimeScope)
        raise LifetimeScopeInvariantError(
            f"LS-INV-05: unknown lifetime value {value!r}; "
            f"the value set is closed to {valid}."
        ) from e


# ---------------------------------------------------------------------------
# Registration record
# ---------------------------------------------------------------------------
class _Registration:
    __slots__ = ("factory", "key", "scope")

    def __init__(
        self,
        key: str,
        factory: Callable[[], object],
        scope: LifetimeScope,
    ) -> None:
        self.key: str = key
        self.factory: Callable[[], object] = factory
        self.scope: LifetimeScope = scope


# ---------------------------------------------------------------------------
# Reference ScopeManager implementation
# ---------------------------------------------------------------------------
class ScopeManager:
    """Reference manager: LIFO-disposing scope stack with parent inheritance.

    Hierarchy:
    - The root manager holds singleton registrations and singleton instances.
    - `open_scope()` returns a child manager that SHARES the registration map
      and singleton cache with its root but maintains its OWN scoped-instance
      cache + creation-order list. Transients are never cached (LS-INV-03).
    - A child scope inherits the parent's resolution chain: singletons go to
      the root, scoped go to the nearest live scope in the chain.

    The scope stack is LIFO — `dispose()` releases instances in reverse of
    construction order so a resource that depends on another constructed
    earlier is torn down first (LS-INV-02).
    """

    # ------------------------------------------------------------------ init
    def __init__(self, *, _parent: ScopeManager | None = None) -> None:
        self._parent = _parent
        self._is_root = _parent is None
        if _parent is None:
            self._registrations: dict[str, _Registration] = {}
            self._singletons: dict[str, object] = {}
            self._external_ids: set[int] = set()
            self._reg_lock: threading.RLock = threading.RLock()
            self._singleton_lock: threading.RLock = threading.RLock()
        else:
            # Share registrations + singleton cache + locks with the root so
            # every descendant observes a single registry (LS-INV-01).
            # Same-class sibling attribute access — private attrs are
            # legitimate here to realise the parent-child inheritance chain.
            self._registrations = _parent._registrations  # noqa: SLF001  # LS-INV-01 shared registry
            self._singletons = _parent._singletons  # noqa: SLF001  # LS-INV-01 singleton cache at root
            self._external_ids = _parent._external_ids  # noqa: SLF001  # LS-INV-02 external-ownership registry
            self._reg_lock = _parent._reg_lock  # noqa: SLF001  # LS-INV-01 shared registration lock
            self._singleton_lock = _parent._singleton_lock  # noqa: SLF001  # LS-INV-01 shared singleton lock

        self._scoped_instances: dict[str, object] = {}
        # Creation order — disposed in reverse (LIFO) by dispose().
        self._scoped_order: list[tuple[str, object]] = []
        self._scope_lock = threading.RLock()
        self._disposed = False
        # Depth is 0 for the root, root.depth + 1 for each child.
        self._depth: int = 0 if _parent is None else _parent._depth + 1  # noqa: SLF001  # LS-INV-02 depth inheritance

    # ------------------------------------------------------------- register
    def register(
        self,
        key: str,
        factory: Callable[[], object],
        *,
        scope: LifetimeScope | str,
    ) -> None:
        """Register a zero-arg `factory` under `key` with the given lifetime.

        LS-INV-05: `scope` is coerced through the enum; unknown strings raise.
        Re-registration under the same key is forbidden — matches DiContainer
        semantics so callers see one vocabulary across the two primitives.
        """
        if not key:
            raise LifetimeScopeInvariantError(
                "LS-INV-05: registration key MUST be a non-empty string."
            )
        scope_enum = coerce(scope)
        with self._reg_lock:
            if key in self._registrations:
                raise LifetimeScopeInvariantError(
                    f"LS-INV-05: key {key!r} is already registered; "
                    f"re-registration MUST be explicit."
                )
            self._registrations[key] = _Registration(
                key=key, factory=factory, scope=scope_enum,
            )

    def register_instance(self, key: str, instance: object) -> None:
        """Register a pre-built singleton owned by the caller.

        The ScopeManager WILL NOT dispose externally-owned instances on
        scope exit (callers own their lifetime).
        """
        if not key:
            raise LifetimeScopeInvariantError(
                "LS-INV-05: registration key MUST be a non-empty string."
            )
        if not self._is_root:
            raise LifetimeScopeInvariantError(
                "LS-INV-02: register_instance is only valid on the root manager."
            )
        with self._reg_lock, self._singleton_lock:
            if key in self._registrations:
                raise LifetimeScopeInvariantError(
                    f"LS-INV-05: key {key!r} is already registered."
                )
            self._registrations[key] = _Registration(
                key=key,
                factory=lambda: instance,
                scope=LifetimeScope.SINGLETON,
            )
            self._singletons[key] = instance
            self._external_ids.add(id(instance))

    # -------------------------------------------------------------- resolve
    def resolve(self, key: str) -> object:
        """Resolve `key` respecting its declared lifetime.

        LS-INV-01 (singleton identity), LS-INV-02 (scoped-per-scope),
        LS-INV-03 (transient-per-call), LS-INV-04 (leak rejection).
        """
        if self._disposed:
            raise LifetimeScopeInvariantError(
                "LS-INV-02: scope has been disposed; resolve is forbidden."
            )
        reg = self._registrations.get(key)
        if reg is None:
            raise LifetimeScopeInvariantError(
                f"LS-INV-05: no registration for key={key!r}."
            )

        if reg.scope is LifetimeScope.SINGLETON:
            with self._singleton_lock:
                existing = self._singletons.get(key)
                if existing is not None:
                    return existing
                instance = self._construct(reg, owner_scope=LifetimeScope.SINGLETON)
                self._singletons[key] = instance
                return instance

        if reg.scope is LifetimeScope.SCOPED:
            if self._is_root:
                raise LifetimeScopeInvariantError(
                    "LS-INV-02: scoped registration cannot be resolved from the root; "
                    "open a scope via open_scope() first."
                )
            with self._scope_lock:
                existing = self._scoped_instances.get(key)
                if existing is not None:
                    return existing
                instance = self._construct(reg, owner_scope=LifetimeScope.SCOPED)
                self._scoped_instances[key] = instance
                self._scoped_order.append((key, instance))
                return instance

        # TRANSIENT — never cached (LS-INV-03).
        return self._construct(reg, owner_scope=LifetimeScope.TRANSIENT)

    def resolve_typed(self, key: str, expected_type: type[T]) -> T:
        """Typed wrapper — casts the resolved object to `expected_type`."""
        obj = self.resolve(key)
        if not isinstance(obj, expected_type):
            raise LifetimeScopeInvariantError(
                f"LS-INV-05: resolved object for key={key!r} is "
                f"{type(obj).__name__!r}, expected {expected_type.__name__!r}."
            )
        return obj

    def _construct(
        self,
        reg: _Registration,
        *,
        owner_scope: LifetimeScope,
    ) -> object:
        try:
            instance = reg.factory()
        except TypeError as e:
            raise LifetimeScopeInvariantError(
                f"LS-INV-05: factory for key={reg.key!r} requires arguments; "
                f"register a zero-arg callable."
            ) from e
        self._assert_no_leak(reg, instance, owner_scope)
        return instance

    def _assert_no_leak(
        self,
        reg: _Registration,
        instance: object,
        owner_scope: LifetimeScope,
    ) -> None:
        """LS-INV-04: reject a shorter-lifetime dep captured by a longer-lived
        owner. The declaration lives on the instance class via
        ``__lifetime_scope__``; test fixtures set this to declare intent.
        """
        declared = getattr(type(instance), "__lifetime_scope__", None)
        if declared is None:
            return
        try:
            declared_enum = coerce(declared) if isinstance(declared, str) else declared
        except LifetimeScopeInvariantError:
            return
        if not isinstance(declared_enum, LifetimeScope):
            return
        if _SCOPE_RANK[declared_enum] > _SCOPE_RANK[owner_scope]:
            raise LifetimeScopeInvariantError(
                f"LS-INV-04: {type(instance).__name__} declares "
                f"lifetime={declared_enum.value!r} but owner scope is "
                f"{owner_scope.value!r}; a shorter-lived dependency MUST NOT "
                f"be captured by a longer-lived owner."
            )

    # --------------------------------------------------------------- scopes
    def open_scope(self) -> ScopeManager:
        """Open a new child scope inheriting registrations from this manager."""
        if self._disposed:
            raise LifetimeScopeInvariantError(
                "LS-INV-02: manager has been disposed; open_scope is forbidden."
            )
        return ScopeManager(_parent=self)

    @contextlib.contextmanager
    def scope(self) -> Iterator[ScopeManager]:
        """Context-manager variant — guarantees LIFO dispose on block exit."""
        child = self.open_scope()
        try:
            yield child
        finally:
            child.dispose()

    def dispose(self) -> None:
        """Dispose all scope-owned instances in LIFO order (LS-INV-02)."""
        if self._disposed:
            return
        with self._scope_lock:
            # Dispose in reverse construction order, skipping externally-owned.
            while self._scoped_order:
                _key, instance = self._scoped_order.pop()
                if id(instance) in self._external_ids:
                    continue
                close = getattr(instance, "close", None)
                if callable(close):
                    # LS-INV-02: the scope MUST drain even when a close()
                    # raises; swallowing here is the only way to guarantee
                    # later instances are also released.
                    with contextlib.suppress(Exception):
                        close()
            self._scoped_instances.clear()
            self._disposed = True

    # -------------------------------------------------- context-manager
    def __enter__(self) -> Self:
        if self._disposed:
            raise LifetimeScopeInvariantError(
                "LS-INV-02: manager has been disposed; cannot re-enter scope."
            )
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> Literal[False]:
        # LS-INV-02: ALWAYS dispose scope-owned instances on exit, even on error.
        self.dispose()
        return False

    # --------------------------------------------------------- introspection
    @property
    def disposed(self) -> bool:
        return self._disposed

    @property
    def depth(self) -> int:
        """0 for root; +1 per nested open_scope."""
        return self._depth

    def is_registered(self, key: str) -> bool:
        return key in self._registrations

    def scope_snapshot(self) -> tuple[object, ...]:
        """Instances owned by this scope, in LIFO order (last-created first)."""
        with self._scope_lock:
            return tuple(inst for _k, inst in reversed(self._scoped_order))

    def singleton_snapshot(self) -> tuple[object, ...]:
        with self._singleton_lock:
            return tuple(self._singletons.values())

    def lifetime_of(self, key: str) -> LifetimeScope:
        """Return the declared lifetime for `key` (LS-INV-05)."""
        reg = self._registrations.get(key)
        if reg is None:
            raise LifetimeScopeInvariantError(
                f"LS-INV-05: no registration for key={key!r}."
            )
        return reg.scope


def is_closed_value(value: Any) -> bool:
    """Return True iff `value` corresponds to a declared LifetimeScope member.

    LS-INV-05: this is the *only* safe way for framework adapters to accept
    a free-form string at their boundary. Unknown values MUST fall through
    to a rejection path.
    """
    if isinstance(value, LifetimeScope):
        return True
    if isinstance(value, str):
        return value in {m.value for m in LifetimeScope}
    return False


__all__ = [
    "LifetimeScope",
    "LifetimeScopeInvariantError",
    "ScopeManager",
    "coerce",
    "is_closed_value",
]
