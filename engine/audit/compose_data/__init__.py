"""WP-17 — compose-data package: split of pre-split ``_build_compose.py``.

Public surface (re-exported by the ``engine.audit._build_compose`` facade):

* ``build`` — the one-shot §B1.1 + §B1.2 builder.
* ``E`` — curated entries for production primitives (124 after placeholder pop).
* ``EMERGING`` — curated entries for non-manifest primitives (~18).
* ``CONCERN_BY_NS``, ``DATA_CONCERN``, ``concern_for`` — taxonomy.
* ``SKILL_ROOT``, ``VENOUS``, ``REGISTRY`` — path constants.
"""

from __future__ import annotations

from engine.audit.compose_data._assembly import EMERGING, E
from engine.audit.compose_data._build import build
from engine.audit.compose_data._constants import (
    CONCERN_BY_NS,
    DATA_CONCERN,
    REGISTRY,
    SKILL_ROOT,
    VENOUS,
    concern_for,
)

__all__ = [
    "CONCERN_BY_NS",
    "DATA_CONCERN",
    "E",
    "EMERGING",
    "REGISTRY",
    "SKILL_ROOT",
    "VENOUS",
    "build",
    "concern_for",
]
