"""Shared base for every ``contract_rules.phase*`` module.

CONTRACT.md scope: NONE (helper module — no rules live here).

Holds the constants + dataclass + helpers every phase module needs:
  * ``REPO_ROOT`` / ``SKILL_ROOT`` — the two filesystem anchors every
    rule resolves paths against.
  * ``_SEMVER_RE`` — official semver 2.0.0 regex body (no anchors).
    Defined once, imported by every consumer (Codex v5 M2 anti-drift).
  * ``Rule`` dataclass — frozen tuple of ``(item, phase, description,
    check)`` the registry list is composed of.
  * ``_exists`` / ``_grep_count`` — helpers used by ≥2 phase modules.

Per WP-16 §3 + invariant I12: ``_common`` is the only module imported by
every ``phase*`` module; phase modules never import each other.

M3.1 consumer flip: the ``Rule`` dataclass + the ``_exists`` / ``_grep_count``
path helpers are no longer defined here — they are lifted into the shared
platform framework ``hugr_core.audit`` (the vocabulary-free §B audit harness)
and RE-EXPORTED below so the 16 phase/``r_*`` predicate modules keep their
``from ._common import Rule, _exists, _grep_count`` imports UNCHANGED. The §B
RULES + predicates stay skill-side; only the generic harness moves. Behavior-
preserving: ``_exists`` is wrapped to pass ``rel_to=REPO_ROOT`` so the printed
``ok: <relpath>`` text stays byte-identical to the pre-lift local helper.
The semver regex + the ``SKILL_ROOT``/``REPO_ROOT`` anchors stay skill-side.
"""

from __future__ import annotations

from pathlib import Path

from hugr_core.audit import Rule, exists
from hugr_core.audit import grep_count as _grep_count
from hugr_core.layout import resolve_roots

__all__ = ["Rule", "REPO_ROOT", "SKILL_ROOT", "_SEMVER_RE", "_exists", "_grep_count"]

# The two filesystem anchors every rule resolves against — SKILL_ROOT (the dir
# holding engine/) and REPO_ROOT (the git repo root) — now provided by the
# shared platform framework, hugr-core. ``resolve_roots`` walks up from this
# file to the skill root and derives the repo root, handling both the standalone
# skill repo and the Arsenal monorepo layouts. This monorepo-vs-standalone
# detection originated here in _common.py during the v1.0 extraction and was
# promoted into hugr_core.layout in the Phase 2 beachhead (core-v0.1.0); this
# module is now the first consumer of the framework core, proving the plug.
SKILL_ROOT, REPO_ROOT = resolve_roots(__file__)

# Official semver 2.0.0 regex body (no anchors).
# Source: https://semver.org/#is-there-a-suggested-regular-expression-regex-to-check-a-semver-string
# Rejects leading zeros (01.0.0), trailing dots (1.0.0-rc..1), empty
# identifiers (1.0.0-), and other malformed shapes that the looser
# Wave-E pattern admitted. Accepts pre-release suffixes (1.0.0-rc.1)
# AND build metadata (1.0.0+build.1). Module-level so every rule
# that touches a version string consumes the same definition —
# Codex v5 M2 flagged the drift between the canonical regex here and
# a looser per-rule copy.
_SEMVER_RE = (
    r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
    r"(?:-(?:(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*)?"
)


def _exists(path: Path, *, min_bytes: int = 0) -> tuple[bool, str]:
    """Skill-side wrapper over ``hugr_core.audit.exists``.

    The lifted helper is path-agnostic (no skill globals); we bind
    ``rel_to=REPO_ROOT`` here so the printed ``ok: <relpath>`` text stays
    byte-identical to the pre-lift local helper.
    """
    return exists(path, min_bytes=min_bytes, rel_to=REPO_ROOT)
