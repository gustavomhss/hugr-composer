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
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from hugr_core.layout import resolve_roots

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


@dataclass(frozen=True)
class Rule:
    item: str  # "B0.5"
    phase: int  # 0..7
    description: str  # short human label
    check: Callable[[], tuple[bool, str]]  # -> (ok, message)


def _exists(path: Path, *, min_bytes: int = 0) -> tuple[bool, str]:
    if not path.exists():
        return False, f"missing: {path}"
    if min_bytes and path.stat().st_size < min_bytes:
        return False, f"too small ({path.stat().st_size}B < {min_bytes}B): {path}"
    return True, f"ok: {path.relative_to(REPO_ROOT)}"


def _grep_count(pattern: str, paths: list[Path]) -> int:
    cmd = ["grep", "-rlE", pattern, *[str(p) for p in paths]]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return len([line for line in out.stdout.splitlines() if line])
    except FileNotFoundError:
        return 0
