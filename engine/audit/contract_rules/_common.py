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

# SKILL_ROOT is the dir that holds engine/ — always parents[3] of this file
# (engine/audit/contract_rules/_common.py), in both repo layouts.
SKILL_ROOT = Path(__file__).resolve().parents[3]
# Layout detection: in the Arsenal monorepo the skill lives under
# <repo>/skills/SKILL-001-fastapi-production/, so REPO_ROOT is one level above
# skills/. In a standalone skill repo (v1.0 extraction) the skill IS the repo
# root, so REPO_ROOT == SKILL_ROOT. Detect by whether the parent dir is skills/.
if SKILL_ROOT.parent.name == "skills":
    REPO_ROOT = SKILL_ROOT.parent.parent  # monorepo root (one level above skills/)
else:
    REPO_ROOT = SKILL_ROOT  # standalone skill repo

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
