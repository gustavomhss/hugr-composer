"""Formal hexagonal port boundary for ``core/venous/`` per ADR-0001.

This package is the single source of truth for the Protocol surfaces that
adapters (``core/venous/_adapters/``) implement and compose tools
(``adapt/extend/``, ``adapt/_base/``) consume. It is **type-only** — no
file under this tree contains runtime code other than ``Protocol`` class
bodies whose methods are ``...`` ellipsis stubs.

Importing :mod:`core.venous._ports` itself triggers no side effects and
does **not** eagerly load any namespace. Consumers import the specific
namespace they need (e.g. ``from core.venous._ports.api import
CommandBusProtocol``).

See ``core/venous/_ports/README.md`` for the boundary doc, derivation
procedure, and the phased migration plan (WP-15 ships phase 1 only).
"""

from __future__ import annotations

__all__: list[str] = []
