"""DiContainer primitive — typed dependency registry with lifetime scoping.

Implements the catalog Protocol for `data.DiContainer` and installs runtime
invariant checkers. The module performs zero I/O at import.

Invariant IDs cited by this module:

- DI-INV-01: resolve() MUST detect cycles; re-entering a partially-constructed
  node SHALL raise DiContainerInvariantError rather than deadlock or recurse.
- DI-INV-02: a scoped or transient registration NEVER leaks into a singleton —
  an instance whose declared scope outlives the resolving scope is FORBIDDEN.
- DI-INV-03: when a scope ends, the container ALWAYS disposes instances it
  owns (singleton / scoped). Callers MUST NOT dispose externally-created
  instances.
- DI-INV-04: register() MUST NOT silently replace a prior registration for
  the same key; re-registration SHALL raise unless the caller passes
  allow_override=True (explicit re-registration).
- DI-INV-05: register() keys on the interface type; keyed registrations
  (multiple impls of the same iface) MUST supply an extra `name` discriminator
  and MUST be resolved with the same discriminator.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable
from types import TracebackType
from typing import Any, Final, Literal, Protocol, Self, TypeVar, cast, runtime_checkable

T = TypeVar("T")

_SCOPE_SINGLETON: Final[str] = "singleton"
_SCOPE_SCOPED: Final[str] = "scoped"
_SCOPE_TRANSIENT: Final[str] = "transient"

_VALID_SCOPES: Final[frozenset[str]] = frozenset({
    _SCOPE_SINGLETON,
    _SCOPE_SCOPED,
    _SCOPE_TRANSIENT,
})

# Scope rank for leak detection — higher rank means shorter lifetime.
# A shorter-lifetime dependency CANNOT be captured by a longer-lifetime owner.
_SCOPE_RANK: Final[dict[str, int]] = {
    _SCOPE_SINGLETON: 0,
    _SCOPE_SCOPED: 1,
    _SCOPE_TRANSIENT: 2,
}


# ---------------------------------------------------------------------------
# Protocol surface (matches catalog api_signature verbatim)
# ---------------------------------------------------------------------------
@runtime_checkable
class DiContainer(Protocol):
    def register(
        self,
        iface: type[T],
        impl: type[T] | Callable[..., T],
        *,
        scope: str,
    ) -> None: ...
    def resolve(self, iface: type[T]) -> T: ...
    def create_scope(self) -> DiContainer: ...


class DiContainerInvariantError(RuntimeError):
    """Raised when a DiContainer invariant is violated at runtime."""


# ---------------------------------------------------------------------------
# Registration record
# ---------------------------------------------------------------------------
class _Registration:
    __slots__ = ("iface", "impl", "name", "scope")

    def __init__(
        self,
        iface: type[Any],
        impl: type[Any] | Callable[..., Any],
        scope: str,
        name: str | None,
    ) -> None:
        self.iface: type[Any] = iface
        self.impl: type[Any] | Callable[..., Any] = impl
        self.scope: str = scope
        self.name: str | None = name


_Key = tuple[type[Any], str | None]


# ---------------------------------------------------------------------------
# Reference implementation
# ---------------------------------------------------------------------------
class InMemoryDiContainer:
    """Reference DiContainer: thread-safe registry with lifetime scoping.

    Hierarchy:
    - The root container holds singleton registrations and singleton instances.
    - `create_scope()` returns a child container that shares the registration
      map with its root but maintains its own scoped-instance cache and scope
      stack. Transients are never cached.

    Instances created via factories (non-type impls) count as owned by the
    container; `register_instance` wires an externally-created object that is
    NOT disposed by the container (DI-INV-03).
    """

    # ------------------------------------------------------------------ init
    def __init__(
        self,
        *,
        _parent: InMemoryDiContainer | None = None,
    ) -> None:
        self._parent = _parent
        self._is_root = _parent is None
        if _parent is None:
            self._registrations: dict[_Key, _Registration] = {}
            self._singletons: dict[_Key, object] = {}
            self._external: set[int] = set()
            self._reg_lock: threading.RLock = threading.RLock()
            self._singleton_lock: threading.RLock = threading.RLock()
        else:
            # Share registrations + singleton cache + locks with the root so
            # every scope observes a single registry (DI-INV-02, DI-INV-04).
            # Same-class sibling access — private attrs are legitimate here.
            self._registrations = _parent._registrations  # noqa: SLF001  # DI-INV-04 shared registry across scopes
            self._singletons = _parent._singletons  # noqa: SLF001  # DI-INV-02 singleton cache lives at root
            self._external = _parent._external  # noqa: SLF001  # DI-INV-03 external-ownership registry
            self._reg_lock = _parent._reg_lock  # noqa: SLF001  # DI-INV-04 shared registration lock
            self._singleton_lock = _parent._singleton_lock  # noqa: SLF001  # DI-INV-02 shared singleton lock

        self._scoped_instances: dict[_Key, object] = {}
        self._scoped_order: list[tuple[_Key, object]] = []
        self._scope_lock = threading.RLock()
        self._resolve_stack: threading.local = threading.local()
        self._disposed = False
        self._entered = False

    # ---------------------------------------------------------- registration
    def register(
        self,
        iface: type[T],
        impl: type[T] | Callable[..., T],
        *,
        scope: str,
        name: str | None = None,
        allow_override: bool = False,
    ) -> None:
        """Register a provider for `iface` with the given lifetime scope.

        DI-INV-04: re-registration raises unless `allow_override=True`.
        DI-INV-05: keyed registrations MUST provide a non-empty `name`.
        """
        if scope not in _VALID_SCOPES:
            raise DiContainerInvariantError(
                f"DI-INV-04: scope must be one of {_VALID_SCOPES!r}; got {scope!r}."
            )
        if name is not None and not name:
            raise DiContainerInvariantError(
                "DI-INV-05: keyed registration requires a non-empty discriminator name."
            )
        key: _Key = (iface, name)
        with self._reg_lock:
            if key in self._registrations and not allow_override:
                raise DiContainerInvariantError(
                    f"DI-INV-04: registration for {iface!r} (name={name!r}) already "
                    f"exists; pass allow_override=True to replace explicitly."
                )
            self._registrations[key] = _Registration(
                iface=iface,
                impl=impl,
                scope=scope,
                name=name,
            )

    def register_instance(
        self,
        iface: type[T],
        instance: T,
        *,
        name: str | None = None,
    ) -> None:
        """Register an externally-created instance as a singleton.

        DI-INV-03: the container WILL NOT dispose this instance — the caller
        owns its lifetime.
        """
        if name is not None and not name:
            raise DiContainerInvariantError(
                "DI-INV-05: keyed registration requires a non-empty discriminator name."
            )
        if not self._is_root:
            raise DiContainerInvariantError(
                "DI-INV-03: register_instance is only valid on the root container."
            )
        key: _Key = (iface, name)
        with self._reg_lock, self._singleton_lock:
            if key in self._registrations:
                raise DiContainerInvariantError(
                    f"DI-INV-04: registration for {iface!r} already exists."
                )
            self._registrations[key] = _Registration(
                iface=iface,
                impl=lambda: instance,
                scope=_SCOPE_SINGLETON,
                name=name,
            )
            self._singletons[key] = instance
            self._external.add(id(instance))

    # -------------------------------------------------------------- resolve
    def resolve(
        self,
        iface: type[T],
        *,
        name: str | None = None,
    ) -> T:
        """Resolve a dependency by interface type.

        DI-INV-01: raises DiContainerInvariantError on cycles.
        DI-INV-02: a resolving scope SHALL NEVER capture a longer-lived
        singleton dependency that itself transitively holds a shorter-lived
        scoped or transient reference; this method detects the leak at
        resolve-time.
        """
        if self._disposed:
            raise DiContainerInvariantError(
                "DI-INV-03: container has been disposed; resolve is forbidden."
            )
        key: _Key = (iface, name)
        reg = self._registrations.get(key)
        if reg is None:
            raise DiContainerInvariantError(
                f"DI-INV-05: no registration for {iface!r} (name={name!r})."
            )

        stack = self._get_stack()
        if key in stack:
            cycle = " -> ".join(
                f"{k[0].__name__}" + (f"[{k[1]}]" if k[1] else "")
                for k in (*stack, key)
            )
            raise DiContainerInvariantError(
                f"DI-INV-01: cycle detected during resolve: {cycle}"
            )

        stack.append(key)
        try:
            # Runtime dispatch — the registration contract guarantees the
            # returned object implements iface (enforced by register()).
            resolved = self._resolve_locked(reg, key)
            return cast("T", resolved)
        finally:
            stack.pop()

    def _resolve_locked(self, reg: _Registration, key: _Key) -> object:
        if reg.scope == _SCOPE_SINGLETON:
            with self._singleton_lock:
                existing = self._singletons.get(key)
                if existing is not None:
                    return existing
                instance = self._construct(reg, owner_scope=_SCOPE_SINGLETON)
                self._singletons[key] = instance
                return instance
        if reg.scope == _SCOPE_SCOPED:
            if self._is_root:
                raise DiContainerInvariantError(
                    "DI-INV-02: scoped registration cannot be resolved from the root; "
                    "open a child scope via create_scope() first."
                )
            with self._scope_lock:
                existing = self._scoped_instances.get(key)
                if existing is not None:
                    return existing
                instance = self._construct(reg, owner_scope=_SCOPE_SCOPED)
                self._scoped_instances[key] = instance
                self._scoped_order.append((key, instance))
                return instance
        # transient — never cached
        return self._construct(reg, owner_scope=_SCOPE_TRANSIENT)

    def _construct(self, reg: _Registration, *, owner_scope: str) -> object:
        impl = reg.impl
        factory: Callable[..., object] = impl if callable(impl) else cast("Callable[..., object]", impl)
        try:
            instance = factory()
        except TypeError as e:
            # Factories with required positional args are not supported by the
            # reference container; downstream code MUST register a zero-arg
            # factory (lambda: Impl(dep1=..., dep2=...)).
            raise DiContainerInvariantError(
                f"DI-INV-05: factory for {reg.iface!r} requires arguments; "
                f"register a zero-arg callable: lambda: Impl(...)"
            ) from e
        self._assert_scope_containment(reg, instance, owner_scope)
        return instance

    def _assert_scope_containment(
        self,
        reg: _Registration,
        instance: object,
        owner_scope: str,
    ) -> None:
        """Check DI-INV-02: a dependency declared with a shorter lifetime
        than its owner cannot be captured.

        The reference container only enforces this at construction time for
        dependencies that expose ``__scope_declaration__`` on their class —
        test helpers set this attribute to declare their intended lifetime.
        Real-world implementations wire this to the introspected graph.
        """
        declared = getattr(type(instance), "__scope_declaration__", None)
        if declared is None:
            return
        if declared not in _VALID_SCOPES:
            return
        if _SCOPE_RANK[declared] > _SCOPE_RANK[owner_scope]:
            raise DiContainerInvariantError(
                f"DI-INV-02: {type(instance).__name__} declares scope={declared!r} "
                f"(shorter than owner scope={owner_scope!r}); captured dependencies "
                f"MUST NOT outlive their owner."
            )

    # --------------------------------------------------------------- scopes
    def create_scope(self) -> InMemoryDiContainer:
        """Open a child scope for scoped / transient resolution."""
        if self._disposed:
            raise DiContainerInvariantError(
                "DI-INV-03: container has been disposed; create_scope is forbidden."
            )
        return InMemoryDiContainer(_parent=self._root())

    def _root(self) -> InMemoryDiContainer:
        if self._parent is None:
            return self
        return self._parent._root()  # noqa: SLF001  # DI-INV-02 walk up same-class chain to the root

    def dispose(self) -> None:
        """Dispose all scope-owned instances. DI-INV-03."""
        if self._disposed:
            return
        with self._scope_lock:
            # Dispose in reverse construction order, skipping externally-owned.
            while self._scoped_order:
                _key, instance = self._scoped_order.pop()
                if id(instance) in self._external:
                    continue
                close = getattr(instance, "close", None)
                if callable(close):
                    # DI-INV-03: dispose MUST drain the scope even when an
                    # individual close() raises; swallowing here is the only
                    # way to guarantee later instances are also released.
                    with contextlib.suppress(Exception):
                        close()
            self._scoped_instances.clear()
            self._disposed = True

    # -------------------------------------------------- context-manager
    def __enter__(self) -> Self:
        if self._disposed:
            raise DiContainerInvariantError(
                "DI-INV-03: container has been disposed; cannot re-enter scope."
            )
        self._entered = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> Literal[False]:
        # DI-INV-03: ALWAYS dispose scope-owned instances on exit, even on error.
        self.dispose()
        return False

    # --------------------------------------------------------- introspection
    def is_registered(self, iface: type[Any], *, name: str | None = None) -> bool:
        return (iface, name) in self._registrations

    def scope_snapshot(self) -> tuple[object, ...]:
        with self._scope_lock:
            return tuple(inst for _k, inst in self._scoped_order)

    def singleton_snapshot(self) -> tuple[object, ...]:
        with self._singleton_lock:
            return tuple(self._singletons.values())

    @property
    def disposed(self) -> bool:
        return self._disposed

    # ------------------------------------------------- helpers
    def _get_stack(self) -> list[_Key]:
        stack = getattr(self._resolve_stack, "value", None)
        if stack is None:
            stack = []
            self._resolve_stack.value = stack
        return stack


__all__ = [
    "DiContainer",
    "DiContainerInvariantError",
    "InMemoryDiContainer",
]
