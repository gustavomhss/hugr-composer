"""§B1.1 + §B1.2 one-shot builder (facade).

Implementation moved to ``engine.audit.compose_data`` (split per WP-17).
This module preserves the historic public surface::

    python -m engine.audit._build_compose
    from engine.audit._build_compose import build, E, EMERGING
    from engine.audit._build_compose import CONCERN_BY_NS, DATA_CONCERN, concern_for
"""

from __future__ import annotations

from engine.audit.compose_data import (
    CONCERN_BY_NS,
    DATA_CONCERN,
    EMERGING,
    REGISTRY,
    SKILL_ROOT,
    VENOUS,
    E,
    build,
    concern_for,
)

__all__ = [
    "CONCERN_BY_NS", "DATA_CONCERN", "E", "EMERGING",
    "REGISTRY", "SKILL_ROOT", "VENOUS", "build", "concern_for",
]  # fmt: skip

if __name__ == "__main__":
    build()
