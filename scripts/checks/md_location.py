#!/usr/bin/env python3
"""Repo rule: narrative markdown lives in docs/, not scattered through the tree.

Concentrating docs keeps the source navigable and free of AGENT_SESSION / brief /
KNOWLEDGE / HANDOFF noise. A markdown file is allowed only if it is:
  - under docs/ (at any depth — top-level or nested `<pkg>/docs/`), OR
  - under another exempt top-level prefix (.github/, _staging/, tools/), OR
  - inside a content directory (any path segment in CONTENT_SEGMENTS — these
    legitimately hold specs/eval/example/audit markdown), OR
  - a path-context-allowed convention basename:
      * ROOT_ONLY basenames (CHANGELOG/CONTRIBUTING/LICENSE/CLAUDE) only at repo root,
      * PACKAGE basenames (README/SKILL/KNOWLEDGE/LLM) at any code-package depth,
  - an explicit governance file at repo root (ROOT_GOV) or package root (PKG_GOV), OR
  - a per-primitive spec file matching `<Name>/<Name>.md` (the primitive's own
    invariant doc — colocated with its code by design).
Everything else — including stray narrative markdown in code packages and any
privileged basename used outside its allowed depth — is a violation.

STANDALONE-EXTRACTION NOTE (2026-06): in the Arsenal monorepo the skill lived
under `skills/SKILL-001-fastapi-production/`, so skill-root governance docs
(STATUS/INVENTORY/CONTRACT) and the grandfathered backlog were keyed at depth-3.
This repo IS the skill root, so those keys are re-anchored to depth-1: skill-root
governance is merged into ROOT_GOV, and GRANDFATHERED_PATHS drop the monorepo
prefix.

F-005 closure note: previously, ANY basename in ALLOWED_BASENAMES passed at ANY
depth, so a stray `CHANGELOG.md` or `CLAUDE.md` could be smuggled into any code
package. The bypass is closed by splitting the basename pool into ROOT_ONLY
(root-only) and PACKAGE (package-depth-allowed). A few pre-existing files are
grandfathered in GRANDFATHERED_PATHS — they predate this rule, are legit domain
artefacts, and a separate cleanup PR can migrate them to docs/.

Modes:
  - pre-commit (argv = changed files): only those files → blocks NEW noise.
  - manual/CI (no argv): scans all tracked .md → reports the backlog.
Exit 1 on any violation.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import PurePosixPath

# Top-level dirs whose markdown is fine (matched at path start).
ROOT_EXEMPT_PREFIXES = ("docs/", ".github/", "_staging/", "tools/")
# Content dirs that legitimately hold markdown at any depth (matched per-segment).
CONTENT_SEGMENTS = {"benchmarks", "examples", "specs", "evidence", "audit"}
# `docs/` at ANY depth (top-level or nested `<pkg>/docs/`) is exempt — this
# is the per-package narrative escape hatch the repo standard documents.
NESTED_DOCS_SEGMENT = "docs"

# Repo-root narrative governance docs — visible by convention at the top level.
# In this standalone repo the skill root IS the repo root, so the former
# skill-root governance (STATUS/INVENTORY) and the CORE-BOUNDARY map live here.
ROOT_GOV = {
    "CONTRACT.md",
    "CORE-BOUNDARY.md",
    "EXTERNAL_EVAL_PACKET.md",
    "EXTERNAL_EVAL_RESULTS.md",
    "FREEZE.md",
    "GOLIVE.md",
    "INTERFACES.md",
    "INVENTORY.md",
    "LAUNCH.md",
    "MIGRATION.md",
    "POST_RELEASE.md",
    "PRODUCT.md",
    "QUICK_START.md",
    "ROADMAP.md",
    "SECURITY.md",
    "STATUS.md",
}
# Top-level package-root governance (e.g. `agents/release_attestor/CONTRACT.md`).
PKG_GOV = {"CONTRACT.md"}
# Convention basenames that are root-only — passing them deeper used to be the
# F-005 bypass; restricting them to depth-0 closes it.
ROOT_ONLY_BASENAMES = {
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "LICENSE.md",
    "CLAUDE.md",
}
# Convention basenames that are package-level — each code package may carry
# one, at any depth that is a code-package directory.
PACKAGE_BASENAMES = {
    "README.md",
    "SKILL.md",
    "KNOWLEDGE.md",
    "LLM.md",
}
# Top-level code packages where governance/contract markdown is conventional.
CODE_TOPLEVEL = {
    "agents",
    "hugr_auth",
    "mcp_tools",
    "adapt",
    "generators",
    "engine",
    "core",
    "deploy",
    "tests",
    "scripts",
}
# Pre-existing tracked files that predate the F-005 tightening. They are
# legitimate domain artefacts (promotion executor handoff/ledger spec, test
# architecture overview, agent briefing templates). Grandfathered explicitly so
# the tightening doesn't ship as a baseline regression. A future cleanup PR may
# migrate these to a `docs/` subtree and remove them from this list. Paths are
# repo-root-relative (the standalone repo has no `skills/SKILL-001-*/` prefix).
GRANDFATHERED_PATHS = frozenset(
    {
        "engine/promotion/HANDOFF.md",
        "engine/promotion/LEDGER.md",
        "tests/TESTING.md",
        "tests/contracts/AGENT_BRIEFING_TEMPLATE.md",
        "tests/contracts/MEGA_BRIEFING.md",
    }
)

_IGNORE = (".venv", "site-packages", "emitted", "node_modules")


def _tracked_md() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "*.md"], capture_output=True, text=True, check=False
    ).stdout
    return [p for p in out.splitlines() if p]


def _is_violation(path: str) -> bool:
    norm = path.replace("\\", "/")
    if any(seg in norm for seg in _IGNORE):
        return False
    if norm in GRANDFATHERED_PATHS:
        return False
    if norm.startswith(ROOT_EXEMPT_PREFIXES):
        return False
    p = PurePosixPath(norm)
    parts = p.parts
    # `docs/` at any depth is exempt (per-package narrative escape hatch).
    if NESTED_DOCS_SEGMENT in parts:
        return False
    if any(seg in CONTENT_SEGMENTS for seg in parts):
        return False
    name = p.name
    # Repo root (depth 1).
    if len(parts) == 1:
        if name in ROOT_GOV or name in ROOT_ONLY_BASENAMES or name in PACKAGE_BASENAMES:
            return False
        return True
    # Top-level code-package root (depth 2, e.g. `agents/release_attestor/...`).
    if len(parts) == 2 and parts[0] in CODE_TOPLEVEL:
        if name in PACKAGE_BASENAMES or name in PKG_GOV:
            return False
    # PACKAGE_BASENAMES allowed at any code-package depth (modules/<x>/KNOWLEDGE.md etc.).
    if name in PACKAGE_BASENAMES:
        return False
    # Per-primitive spec colocated with its code (`.../<Name>/<Name>.md`).
    if len(parts) >= 2 and parts[-1] == parts[-2] + ".md":
        return False
    return True


def main(argv: list[str]) -> int:
    candidates = [a for a in argv if a.endswith(".md")] if argv else _tracked_md()
    violations = [p for p in candidates if _is_violation(p)]
    if violations:
        print(
            "✗ md_location: narrative markdown outside docs/ (move it to docs/ or delete):"
        )
        for v in sorted(violations)[:25]:
            print(f"    {v}")
        if len(violations) > 25:
            print(f"    … and {len(violations) - 25} more")
        print(
            "  Rule: narrative .md lives in docs/; code packages keep only README/SKILL/KNOWLEDGE/LLM."
        )
        print(
            "  Root-only basenames (CHANGELOG/CONTRIBUTING/LICENSE/CLAUDE) are NOT allowed deeper."
        )
        return 1
    print("✓ md_location: no stray narrative markdown")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
