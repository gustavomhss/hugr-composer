"""ContextMap primitive — catalog of BoundedContexts and their relationships.

Declares the `ContextMap` Protocol (verbatim from the research catalog entry)
plus an in-memory reference implementation that installs runtime invariant
checks. Performs no I/O at import time.

Invariant IDs:

- CTXMAP-INV-01: every pairwise integration MUST carry a canonical relationship
  kind; ad-hoc or blank kinds are FORBIDDEN.
- CTXMAP-INV-02: the graph of Customer-Supplier edges SHALL be acyclic; a cycle
  CANNOT be introduced without promoting the relationship to Partnership.
- CTXMAP-INV-03: a BoundedContext CANNOT participate in an integration that is
  not registered on the ContextMap; shadow integrations MUST be surfaced.
- CTXMAP-INV-04: relationship changes ALWAYS flow through add_relationship so
  the mutation history is auditable.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Canonical relationship kinds (Evans, DDD Ch.14; Vernon, IDDD Ch.3)
# ---------------------------------------------------------------------------
RELATIONSHIP_KINDS: Final[frozenset[str]] = frozenset({
    "Partnership",
    "Shared Kernel",
    "Customer-Supplier",
    "Conformist",
    "Anticorruption Layer",
    "Open Host Service",
    "Published Language",
    "Separate Ways",
})

# Kinds that carry a directional power asymmetry; cycles among these are forbidden.
# Conformist is asymmetric (downstream conforms upstream's model) — a cycle
# involving Conformist would be semantically incoherent.
_DIRECTIONAL_KINDS: Final[frozenset[str]] = frozenset({
    "Customer-Supplier", "Conformist",
})

# Kinds whose edges are SYMMETRIC — the pair `(A,B)` and `(B,A)` describe the
# same relationship. We canonicalize symmetric-kind endpoints as a sorted
# tuple on insert so `add_relationship('A','B','Partnership')` followed by
# `add_relationship('B','A','Partnership')` collapse to one edge instead of
# producing duplicates with divergent version counters.
_SYMMETRIC_KINDS: Final[frozenset[str]] = frozenset({
    "Partnership", "Shared Kernel",
})

# Context names: non-empty, no leading/trailing whitespace, printable only.
_MAX_CONTEXT_NAME_LEN: Final[int] = 80


class ContextMapInvariantError(ValueError):
    """Raised when a runtime call violates a ContextMap invariant."""


def _validate_context_name(name: str) -> str:
    if not isinstance(name, str):
        raise ContextMapInvariantError(
            "CTXMAP-INV-03: context name MUST be a string."
        )
    cleaned = name.strip()
    if not cleaned:
        raise ContextMapInvariantError(
            "CTXMAP-INV-03: context name MUST be non-empty (whitespace rejected)."
        )
    if len(cleaned) > _MAX_CONTEXT_NAME_LEN:
        raise ContextMapInvariantError(
            f"CTXMAP-INV-03: context name MUST be ≤ {_MAX_CONTEXT_NAME_LEN} chars, "
            f"got {len(cleaned)}."
        )
    if any(ord(c) < 0x20 or ord(c) == 0x7f for c in cleaned):
        raise ContextMapInvariantError(
            "CTXMAP-INV-03: context name MUST NOT contain control characters."
        )
    return cleaned


def _validate_kind(kind: str) -> str:
    if not isinstance(kind, str) or not kind.strip():
        raise ContextMapInvariantError(
            "CTXMAP-INV-01: relationship kind MUST be a non-empty string."
        )
    if kind not in RELATIONSHIP_KINDS:
        raise ContextMapInvariantError(
            f"CTXMAP-INV-01: relationship kind MUST be one of "
            f"{sorted(RELATIONSHIP_KINDS)}; got {kind!r}."
        )
    return kind


# ---------------------------------------------------------------------------
# Protocol surface — mirrors the catalog api_signature
# ---------------------------------------------------------------------------
@runtime_checkable
class ContextMap(Protocol):
    def contexts(self) -> Iterable[str]: ...
    def relationship(self, upstream: str, downstream: str) -> str: ...
    def add_relationship(self, upstream: str, downstream: str, kind: str) -> None: ...
    def integrations(self) -> Iterable[tuple[str, str, str]]: ...


# ---------------------------------------------------------------------------
# Reference implementation
# ---------------------------------------------------------------------------
class InMemoryContextMap:
    """Reference ContextMap backed by a dict of directed edges.

    The map keeps a version counter that increments on every `add_relationship`
    so an auditor can verify CTXMAP-INV-04 (every change flows through the
    single mutator).
    """

    def __init__(self) -> None:
        self._edges: dict[tuple[str, str], str] = {}
        self._contexts: set[str] = set()
        self._version: int = 0

    # --- public API ----------------------------------------------------------
    def contexts(self) -> Iterable[str]:
        return tuple(sorted(self._contexts))

    def relationship(self, upstream: str, downstream: str) -> str:
        u = _validate_context_name(upstream)
        d = _validate_context_name(downstream)
        kind = self._edges.get((u, d))
        if kind is None:
            raise ContextMapInvariantError(
                f"CTXMAP-INV-03: no registered integration for ({u!r} -> {d!r}); "
                f"shadow integrations are FORBIDDEN."
            )
        return kind

    def add_relationship(self, upstream: str, downstream: str, kind: str) -> None:
        u = _validate_context_name(upstream)
        d = _validate_context_name(downstream)
        if u == d:
            raise ContextMapInvariantError(
                "CTXMAP-INV-03: upstream and downstream CANNOT be the same context."
            )
        k = _validate_kind(kind)
        # CTXMAP-INV-01 canonicalisation for symmetric kinds: Partnership and
        # Shared Kernel describe a mutual relationship, so the pair (A,B) and
        # (B,A) are the SAME edge. Sort to a canonical key so both insertion
        # orders collapse into one entry (prevents duplicate-edge audit noise).
        if k in _SYMMETRIC_KINDS:
            u, d = sorted((u, d))
        if k in _DIRECTIONAL_KINDS and self._would_create_directional_cycle(u, d, k):
            raise ContextMapInvariantError(
                f"CTXMAP-INV-02: adding {k!r} edge ({u!r} -> {d!r}) would create "
                f"a directional cycle; promote to Partnership instead."
            )
        self._contexts.add(u)
        self._contexts.add(d)
        self._edges[(u, d)] = k
        self._version += 1

    def integrations(self) -> Iterable[tuple[str, str, str]]:
        return tuple(
            (u, d, k) for (u, d), k in sorted(self._edges.items())
        )

    # --- introspection hooks for tests / auditors -----------------------------
    @property
    def version(self) -> int:
        return self._version

    def has_edge(self, upstream: str, downstream: str) -> bool:
        u = _validate_context_name(upstream)
        d = _validate_context_name(downstream)
        # Symmetric-kind edges are stored canonical (sorted); look both ways
        # so callers can query either orientation and get the same answer.
        return (u, d) in self._edges or (d, u) in self._edges

    # --- internals -----------------------------------------------------------
    def _would_create_directional_cycle(self, u: str, d: str, k: str) -> bool:
        # Treat Customer-Supplier as the sole directional-cycle-forbidding kind.
        # Build adjacency from current directional edges then test reachability
        # from d back to u. If reachable, adding u->d closes a cycle.
        adj: dict[str, list[str]] = {}
        for (x, y), xk in self._edges.items():
            if xk != k:
                continue
            adj.setdefault(x, []).append(y)
        visited: set[str] = set()
        stack: list[str] = [d]
        while stack:
            node = stack.pop()
            if node == u:
                return True
            if node in visited:
                continue
            visited.add(node)
            stack.extend(adj.get(node, []))
        return False


__all__ = [
    "RELATIONSHIP_KINDS",
    "ContextMap",
    "ContextMapInvariantError",
    "InMemoryContextMap",
]
