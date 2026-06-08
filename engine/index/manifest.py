"""Build the skill's catalog manifest deterministically from on-disk sources.

Entry point:

    python -m engine.index.manifest build       # writes engine/index/catalog.json
    python -m engine.index.manifest verify      # builds twice, fails if hash drifts

This module is now a thin **skill-side adapter** over the generic
``hugr_core.scanner``: the scanning / inference / hashing logic lives in the
shared core, and everything below is THIS skill's configuration (paths, scan
roots, closed-vocabulary inference maps, bundle derivation). A ``ScannerConfig``
is assembled per call from the module-level globals so tests can monkeypatch
e.g. ``TOOL_SCAN_ROOTS`` and have ``_scan_tools`` pick up the change.

Design:
  - Scans every `MCP_TOOL` dict under the roots listed in
    ``TOOL_SCAN_ROOTS`` (currently ``adapt``, ``generators``,
    ``modules``, ``benchmark``, ``meta``, ``core_tools``,
    ``discovery``). Each scan walks ``**/*.py`` (so both flat
    ``add_*.py`` modules and the per-tool directory layout
    ``add_<tool>/__init__.py`` are picked up) and produces a
    ToolEntry. ``mcp_tools/`` is **deliberately excluded** — the
    tier-1 meta tools defined there operate ON the manifest and
    must not appear IN it; they are surfaced via
    ``mcp_tools.tier1.register_tier1_tools`` instead.
  - Reads `engine/primitives_by_concern.yaml` → PrimitiveEntry per primitive.
  - Parses every primitive `<Name>.md` for its `## Compose with:` section →
    RecipeEntry per bullet.
  - Sorts everything so the output JSON is byte-stable for a given kit SHA.

Invariants the builder enforces (failures = non-zero exit):
  - Every MCP_TOOL name is uniquely-resolvable to a module.
  - Every tool's `primitives_used` ⊆ the registry.
  - Every tool's `tags` ⊆ TAG_VOCABULARY (the closed vocabulary).
  - Verb + domain are drawn from the closed lists in schemas.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

from hugr_core.scanner import (
    ManifestError,
    ScannerConfig,
)
from hugr_core.scanner import (
    build as _core_build,
)
from hugr_core.scanner import (
    canonical_tool_name as _core_canonical_tool_name,
)
from hugr_core.scanner import (
    extract_intent as _extract_intent,
)
from hugr_core.scanner import (
    infer_domain as _core_infer_domain,
)
from hugr_core.scanner import (
    infer_tags as _core_infer_tags,
)
from hugr_core.scanner import (
    infer_verb as _core_infer_verb,
)
from hugr_core.scanner import (
    main as _core_main,
)
from hugr_core.scanner import (
    scan_tools as _core_scan_tools,
)
from hugr_core.scanner import (
    slugify as _slugify,
)
from hugr_core.scanner import (
    write as _core_write,
)

from engine.index import MANIFEST_SCHEMA_VERSION
from engine.index.schemas import DOMAINS, TAG_VOCABULARY, VERBS

# Re-export so existing imports (`from engine.index.manifest import ManifestError`,
# `_extract_intent`, `_slugify`, `CatalogManifest` …) keep resolving.
__all__ = [
    "ManifestError",
    "build",
    "write",
    "main",
    "CATALOG_PATH",
    "SKILL_ROOT",
    "TOOL_SCAN_ROOTS",
    # re-exported generic helpers (used by engine/tests/test_manifest.py)
    "_extract_intent",
    "_slugify",
]

# ---------------------------------------------------------------------------
# Skill configuration (paths) — all module_path values are relative to SKILL_ROOT
# ---------------------------------------------------------------------------

SKILL_ROOT = Path(__file__).resolve().parents[2]
# Layout-aware (monorepo skills/ vs standalone repo root); see engine/docs/build.py.
# Only feeds the catalog's kit_commit provenance (git sha) — excluded from
# stable_hash. Without this it resolved outside the repo, so kit_commit fell
# back to "unknown".
REPO_ROOT = SKILL_ROOT.parents[1] if SKILL_ROOT.parent.name == "skills" else SKILL_ROOT
REGISTRY_PATH = SKILL_ROOT / "engine" / "primitives_by_concern.yaml"
CATALOG_PATH = SKILL_ROOT / "engine" / "index" / "catalog.json"
VENOUS_ROOT = SKILL_ROOT / "core" / "venous"

# Where MCP_TOOL declarations live. Order drives discovery; later entries
# DO NOT override earlier ones (ManifestError is raised on duplicate names).
# NOTE: `mcp_tools` is deliberately NOT scanned — its tier-1 meta tools operate
# ON the catalog and must not appear IN it.
TOOL_SCAN_ROOTS: tuple[tuple[str, Path], ...] = (
    ("adapt", SKILL_ROOT / "adapt"),
    ("generators", SKILL_ROOT / "generators"),
    ("modules", SKILL_ROOT / "modules"),
    ("benchmark", SKILL_ROOT / "benchmark"),
    ("meta", SKILL_ROOT / "meta"),
    ("core_tools", SKILL_ROOT / "core" / "tools"),
    ("discovery", SKILL_ROOT / "engine" / "discovery"),
)

# ---------------------------------------------------------------------------
# Closed-vocabulary inference maps (skill data fed to the generic scanner)
# ---------------------------------------------------------------------------

_DOMAIN_FROM_PATH = {
    # adapt/extend/<bucket>/ → domain
    "auth_access": "auth",
    "crud_data": "data",
    "api_design": "api",
    "realtime": "realtime",
    "infrastructure": "resiliency",  # overridden below when finer signal exists
    "testing_tools": "testing",
    "performance": "resiliency",
    "proactive": "resiliency",
    # generators/<bucket>/
    "auth": "auth",
    "database": "data",
    "deployment": "deployment",
    "endpoints": "api",
    "middleware": "resiliency",
    "observability": "observability",
    "infra": "deployment",
    "schemas": "api",
    "testing": "testing",
    "tools": "meta",
    # modules/<bucket>/
    "background_jobs": "resiliency",
    "caching": "resiliency",
    "security": "auth",
    "payments": "data",
    "websockets": "realtime",
}

# Sharpen the "infrastructure" catch-all via filename keywords.
_INFRA_KEYWORD_DOMAIN = (
    ("observability", "observability"),
    ("telemetry", "observability"),
    ("sentry", "observability"),
    ("metrics", "observability"),
    ("log", "observability"),
    ("otel", "observability"),
    ("audit", "compliance"),
    ("retention", "compliance"),
    ("consent", "compliance"),
    ("gdpr", "compliance"),
    ("webhook", "realtime"),
    ("sse", "realtime"),
    ("websocket", "realtime"),
    ("realtime", "realtime"),
    ("rbac", "auth"),
    ("rate_limit", "resiliency"),
    ("circuit", "resiliency"),
    ("retry", "resiliency"),
    ("bulkhead", "resiliency"),
    ("graceful", "resiliency"),
    ("event", "data"),
    ("outbox", "data"),
    ("saga", "data"),
    ("cqrs", "api"),
    ("graphql", "api"),
    ("versioning", "api"),
    ("docker", "deployment"),
    ("k8s", "deployment"),
    ("compose", "deployment"),
    ("ci", "deployment"),
    ("soak", "testing"),
    ("fuzz", "testing"),
    ("property", "testing"),
    ("chaos", "testing"),
)

_VERB_FROM_PREFIX = {
    "add_": "add",
    "generate_": "generate",
    "verify_": "verify",
    "operate_": "operate",
    "evolve_": "evolve",
    "proactive_": "proactive",
    "check_": "check",
    "analyze_": "analyze",
    "search_": "search",
    "scaffold_": "generate",  # scaffold_* is a generate synonym
}

# ---------------------------------------------------------------------------
# Skill + bundle derivation (schema v2)
# ---------------------------------------------------------------------------

SKILL_ID = "SKILL-001-fastapi-production"

_BUNDLE_TAGS: dict[str, tuple[str, ...]] = {
    "crud_data": ("data", "persistence"),
    "auth_access": ("security", "auth"),
    "infrastructure": ("resiliency", "infra"),
    "realtime": ("streaming", "sse", "websocket"),
    "testing_tools": ("testing", "fixtures"),
    "api_design": ("api", "versioning", "cqrs"),
}

# Order matters only for stable listing; the catalog re-sorts by name.
_BUNDLE_NAMES: tuple[str, ...] = (
    "api_design",
    "auth_access",
    "crud_data",
    "infrastructure",
    "realtime",
    "testing_tools",
)

# Domain → bundle fallback for tools NOT under adapt/extend/<bundle>/.
_DOMAIN_TO_BUNDLE: dict[str, str] = {
    "auth": "auth_access",
    "data": "crud_data",
    "api": "api_design",
    "realtime": "realtime",
    "testing": "testing_tools",
    "resiliency": "infrastructure",
    "observability": "infrastructure",
    "compliance": "infrastructure",
    "deployment": "infrastructure",
    "meta": "infrastructure",
}


# ---------------------------------------------------------------------------
# Config assembly + thin skill-bound wrappers over the generic scanner
# ---------------------------------------------------------------------------


def _cfg() -> ScannerConfig:
    """Snapshot the current module-level config into a ScannerConfig.

    Read fresh each call so tests that monkeypatch a global (e.g.
    ``TOOL_SCAN_ROOTS``) see the change reflected in ``_scan_tools`` / ``build``.
    """
    return ScannerConfig(
        skill_id=SKILL_ID,
        tool_prefix="fastapi",
        schema_version=MANIFEST_SCHEMA_VERSION,
        skill_root=SKILL_ROOT,
        repo_root=REPO_ROOT,
        registry_path=REGISTRY_PATH,
        catalog_path=CATALOG_PATH,
        venous_root=VENOUS_ROOT,
        staging_root=VENOUS_ROOT / "_staging",
        version_file=SKILL_ROOT / "VERSION",
        tool_scan_roots=TOOL_SCAN_ROOTS,
        verbs=VERBS,
        domains=DOMAINS,
        tag_vocabulary=TAG_VOCABULARY,
        domain_from_path=_DOMAIN_FROM_PATH,
        infra_keyword_domain=_INFRA_KEYWORD_DOMAIN,
        verb_from_prefix=_VERB_FROM_PREFIX,
        bundle_names=_BUNDLE_NAMES,
        bundle_tags=_BUNDLE_TAGS,
        domain_to_bundle=_DOMAIN_TO_BUNDLE,
    )


def build():
    """Build the catalog manifest from this skill's on-disk sources."""
    return _core_build(_cfg())


def write(manifest, path: Path = CATALOG_PATH) -> str:
    """Write catalog + persist the stable content hash; returns the hash."""
    return _core_write(_cfg(), manifest, path)


def _scan_tools() -> list[dict]:
    return _core_scan_tools(_cfg())


def _infer_verb(mcp_name: str, module_stem: str) -> str:
    return _core_infer_verb(_cfg(), mcp_name, module_stem)


def _infer_domain(module_path: Path, mcp_name: str) -> str:
    return _core_infer_domain(_cfg(), module_path, mcp_name)


def _infer_tags(mcp_name: str, module_stem: str) -> tuple[str, ...]:
    return _core_infer_tags(_cfg(), mcp_name, module_stem)


def _canonical_tool_name(verb: str, domain: str, mcp_name: str) -> str:
    return _core_canonical_tool_name(_cfg(), verb, domain, mcp_name)


def main(argv: list[str] | None = None) -> int:
    return _core_main(_cfg(), argv)


if __name__ == "__main__":
    sys.exit(main())
