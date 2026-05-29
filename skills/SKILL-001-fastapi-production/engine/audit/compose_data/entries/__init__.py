"""WP-17 — re-export curated entries dicts for ``_assembly`` to merge.

Each per-namespace module exposes its fragment as ``ENTRIES`` (a module-level
constant dict). The N811 ``noqa`` below acknowledges the convention: the
imported name is reused as a lowercase namespace alias so ``_assembly`` reads
``entries.api`` rather than ``entries.api.ENTRIES``.
"""

from __future__ import annotations

from .api import ENTRIES as api  # noqa: N811
from .auth import ENTRIES as auth  # noqa: N811
from .cache import ENTRIES as cache  # noqa: N811
from .compliance import ENTRIES as compliance  # noqa: N811
from .data import ENTRIES as data  # noqa: N811
from .emerging import ENTRIES as emerging  # noqa: N811
from .events import ENTRIES as events  # noqa: N811
from .extras_flags_jobs import ENTRIES as extras_flags_jobs  # noqa: N811
from .llm import ENTRIES as llm  # noqa: N811
from .obs import ENTRIES as obs  # noqa: N811
from .policy_resiliency import ENTRIES as policy_resiliency  # noqa: N811
from .security import ENTRIES as security  # noqa: N811

__all__ = [
    "api",
    "auth",
    "cache",
    "compliance",
    "data",
    "emerging",
    "events",
    "extras_flags_jobs",
    "llm",
    "obs",
    "policy_resiliency",
    "security",
]
