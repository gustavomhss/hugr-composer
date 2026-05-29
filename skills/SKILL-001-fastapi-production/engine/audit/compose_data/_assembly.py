"""WP-17 — merge curated entries into the master ``E`` + ``EMERGING`` dicts.

The pre-split ``engine/audit/_build_compose.py`` declared ``E`` as a single
2 000-LOC dict literal (and ``EMERGING`` as a sibling 300-LOC dict). This
module re-assembles those exactly by merging every per-namespace fragment
from ``engine.audit.compose_data.entries``.

Invariants:

* No key collisions between any two entries modules (asserted below — any
  collision is a WP-17 bug, not a silent overwrite).
* The historic ``E.pop("TokenIntrospectorX", None)`` placeholder cleanup
  (pre-split line 2456) is preserved verbatim — see F-05 in the WP manifest.
"""

from __future__ import annotations

from engine.audit.compose_data import entries

# ---- E (production primitives) -------------------------------------------
_E_FRAGMENTS = [
    entries.api,
    entries.auth,
    entries.cache,
    entries.compliance,
    entries.data,
    entries.events,
    entries.extras_flags_jobs,
    entries.llm,
    entries.obs,
    entries.policy_resiliency,
    entries.security,
]

E: dict[str, tuple[str, list[str], list[tuple[str, list[str], str]]]] = {}
for _frag in _E_FRAGMENTS:
    _overlap = E.keys() & _frag.keys()
    assert not _overlap, f"compose_data: duplicate entries across fragments: {sorted(_overlap)}"
    E.update(_frag)

# Remove placeholder key (verbatim from pre-split line 2456).
E.pop("TokenIntrospectorX", None)

# ---- EMERGING (non-manifest primitives) ----------------------------------
EMERGING: dict[str, list[tuple[str, list[str], str]]] = dict(entries.emerging)

__all__ = ["E", "EMERGING"]
