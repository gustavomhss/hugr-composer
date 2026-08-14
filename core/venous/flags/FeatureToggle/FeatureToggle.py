"""FeatureToggle primitive — named boolean predicate evaluated against context.

Invariant IDs:

- FT-INV-01: is_active() MUST be pure given the same (key, ctx); side effects
  (I/O, random draws) SHALL NEVER leak into evaluation.
- FT-INV-02: Evaluation MUST default to False (off) when the backing store is
  unreachable; CANNOT default to on.
- FT-INV-03: A toggle key MUST be unique within the registry and SHALL follow
  a fixed naming convention (snake_case, 3-64 chars, [a-z0-9_]).
- FT-INV-04: Evaluation MUST record an observability event for every call;
  audit entries NEVER are dropped.
- FT-INV-05: Removing a toggle MUST be a two-step deprecation: mark stale,
  then delete; code references CANNOT disappear abruptly.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Final, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Catalog surface (mirrors api_signature verbatim)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToggleContext:
    principal_id: str | None
    tenant_id: str | None
    environment: str


@runtime_checkable
class FeatureToggle(Protocol):
    key: str

    def is_active(self, ctx: ToggleContext) -> bool: ...


# ---------------------------------------------------------------------------
# Invariant enforcement
# ---------------------------------------------------------------------------
class FeatureToggleInvariantError(ValueError):
    """Raised when a runtime call violates a FeatureToggle invariant."""


KEY_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_]{2,63}$")


def validate_key(key: str) -> str:
    """FT-INV-03: key MUST match the naming convention."""
    if not isinstance(key, str) or not KEY_PATTERN.match(key):
        raise FeatureToggleInvariantError(
            f"FT-INV-03: toggle key MUST match {KEY_PATTERN.pattern!r}, got {key!r}."
        )
    return key


@dataclass(frozen=True)
class AuditEntry:
    key: str
    decision: bool
    ctx_principal: str | None
    ctx_tenant: str | None
    ctx_environment: str


class FeatureToggleRegistry:
    """Reference FeatureToggle registry.

    Enforces catalog invariants: unique keys, two-step deprecation, off-by-
    default when the underlying provider is unreachable, and per-evaluation
    audit recording (never dropped).
    """

    def __init__(self) -> None:
        self._toggles: dict[str, FeatureToggle] = {}
        self._stale: set[str] = set()
        self._audit: list[AuditEntry] = []
        self._lock = threading.Lock()

    def register(self, toggle: FeatureToggle) -> None:
        """FT-INV-03: unique key. FT-INV-01: toggle MUST expose a pure is_active."""
        validate_key(toggle.key)
        if not callable(getattr(toggle, "is_active", None)):
            raise FeatureToggleInvariantError(
                "FT-INV-01: toggle MUST expose callable is_active(ctx)."
            )
        with self._lock:
            if toggle.key in self._toggles:
                raise FeatureToggleInvariantError(
                    f"FT-INV-03: toggle key {toggle.key!r} already registered."
                )
            self._toggles[toggle.key] = toggle

    def mark_stale(self, key: str) -> None:
        """FT-INV-05: first step of two-step deprecation."""
        with self._lock:
            if key not in self._toggles:
                raise FeatureToggleInvariantError(
                    f"FT-INV-05: cannot mark unknown key {key!r} stale."
                )
            self._stale.add(key)

    def delete(self, key: str) -> None:
        """FT-INV-05: deletion REQUIRES a prior mark_stale."""
        with self._lock:
            if key not in self._toggles:
                raise FeatureToggleInvariantError(f"FT-INV-05: unknown toggle {key!r}.")
            if key not in self._stale:
                raise FeatureToggleInvariantError(
                    f"FT-INV-05: toggle {key!r} MUST be marked stale before deletion."
                )
            del self._toggles[key]
            self._stale.discard(key)

    def is_active(self, key: str, ctx: ToggleContext) -> bool:
        """Evaluate a toggle.

        FT-INV-02: unknown keys return False (off-by-default).
        FT-INV-04: every call records an audit entry.
        """
        if not isinstance(ctx, ToggleContext):
            raise FeatureToggleInvariantError("FT-INV-01: ctx MUST be a ToggleContext.")
        # FT-INV-02: atomically snapshot the toggle so a concurrent delete()
        # cannot produce a decision for a key that `known_keys()` no longer
        # reports. A stale toggle remains evaluable (FT-INV-05: code references
        # must not disappear abruptly); only deletion removes the toggle.
        with self._lock:
            toggle = self._toggles.get(key)
        decision: bool
        if toggle is None:
            decision = False
        else:
            try:
                decision = bool(toggle.is_active(ctx))
            except Exception:  # noqa: BLE001 — FT-INV-02: evaluation errors MUST resolve to False
                decision = False
        with self._lock:
            self._audit.append(
                AuditEntry(
                    key=key,
                    decision=decision,
                    ctx_principal=ctx.principal_id,
                    ctx_tenant=ctx.tenant_id,
                    ctx_environment=ctx.environment,
                )
            )
        return decision

    @property
    def audit(self) -> tuple[AuditEntry, ...]:
        with self._lock:
            return tuple(self._audit)

    def is_stale(self, key: str) -> bool:
        with self._lock:
            return key in self._stale

    def known_keys(self) -> frozenset[str]:
        with self._lock:
            return frozenset(self._toggles)


__all__ = [
    "KEY_PATTERN",
    "AuditEntry",
    "FeatureToggle",
    "FeatureToggleInvariantError",
    "FeatureToggleRegistry",
    "ToggleContext",
    "validate_key",
]
