"""Build the skill's catalog manifest deterministically from on-disk sources.

Entry point:

    python -m engine.index.manifest build       # writes engine/index/catalog.json
    python -m engine.index.manifest verify      # builds twice, fails if hash drifts

Design:
  - Scans every `MCP_TOOL` dict across `adapt/`, `generators/`, `modules/`,
    `mcp_tools/`, `benchmark/analyzer.py` — same discovery path as the MCP
    server. Each produces a ToolEntry.
  - Reads `engine/primitives_by_concern.yaml` → PrimitiveEntry per primitive.
  - Parses every primitive `<Name>.md` for its `## Compose with:` section →
    RecipeEntry per bullet.
  - Sorts everything by (domain, verb, name) / (namespace, name) / id so the
    output JSON is byte-stable for a given kit SHA (prompt-cache friendly).

Invariants this builder enforces (failures = non-zero exit):
  - Every MCP_TOOL name is uniquely-resolvable to a module.
  - Every tool's `primitives_used` ⊆ the registry.
  - Every tool's `tags` ⊆ TAG_VOCABULARY (the closed vocabulary).
  - Verb + domain are drawn from the closed lists in schemas.py.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

from engine.index import MANIFEST_SCHEMA_VERSION
from engine.index.schemas import (
    DOMAINS,
    TAG_VOCABULARY,
    VERBS,
    BundleEntry,
    CatalogManifest,
    PrimitiveEntry,
    RecipeEntry,
    SkillEntry,
    ToolEntry,
)

SKILL_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = SKILL_ROOT.parents[1]
REGISTRY_PATH = SKILL_ROOT / "engine" / "primitives_by_concern.yaml"
CATALOG_PATH = SKILL_ROOT / "engine" / "index" / "catalog.json"
VENOUS_ROOT = SKILL_ROOT / "core" / "venous"

# Where MCP_TOOL declarations live. Order drives discovery; later entries
# DO NOT override earlier ones (ManifestError is raised on duplicate names).
# NOTE: `mcp_tools/` is deliberately NOT scanned. The tier-1 meta tools
# under `mcp_tools/tier1.py` operate ON the manifest and must NOT appear
# IN it (they would be circular entries pointing at themselves). Their
# registration goes through `register_tier1_tools` instead of discovery.
TOOL_SCAN_ROOTS: tuple[tuple[str, Path], ...] = (
    ("adapt", SKILL_ROOT / "adapt"),
    ("generators", SKILL_ROOT / "generators"),
    ("modules", SKILL_ROOT / "modules"),
    ("benchmark", SKILL_ROOT / "benchmark"),
    ("meta", SKILL_ROOT / "meta"),
    ("core_tools", SKILL_ROOT / "core" / "tools"),
    ("discovery", SKILL_ROOT / "engine" / "discovery"),
)


class ManifestError(RuntimeError):
    """Raised when the on-disk sources violate a manifest invariant."""


# ---------------------------------------------------------------------------
# Derive verb + domain + tags from the module path + MCP_TOOL fields.
#
# The rename to `fastapi_<domain>_<verb>_<noun>` is applied in a later commit;
# for now we capture the CURRENT name as `legacy_name` if it doesn't already
# match the new scheme, and compute the canonical `name` by concatenation.
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


def _parse_canonical_name(mcp_name: str) -> tuple[str | None, str | None]:
    """Return (verb, domain) if mcp_name is already in canonical form.

    Canonical = ``fastapi_<domain>_<verb>_<noun>`` with both drawn from
    the closed vocabularies. Returns (None, None) otherwise.
    """
    if not mcp_name.startswith("fastapi_"):
        return None, None
    stripped = mcp_name[len("fastapi_") :]
    # Longest-match domain first (meta, auth, data, api, ...).
    for dom in sorted(DOMAINS, key=len, reverse=True):
        prefix = f"{dom}_"
        if not stripped.startswith(prefix):
            continue
        rest = stripped[len(prefix) :]
        for v in VERBS:
            if rest.startswith(f"{v}_"):
                return v, dom
    return None, None


def _infer_verb(mcp_name: str, module_stem: str) -> str:
    """Infer the verb from MCP_TOOL name or fall back to filename."""
    # Strip optional `fastapi_` prefix for checks.
    stripped = mcp_name.removeprefix("fastapi_")
    for prefix, verb in _VERB_FROM_PREFIX.items():
        if stripped.startswith(prefix) or module_stem.startswith(prefix):
            return verb
    # Default: `analyze`. Most surviving tools are analyzers / checks.
    return "analyze"


def _infer_domain(module_path: Path, mcp_name: str) -> str:
    """Infer the domain from directory + filename keywords."""
    parts = module_path.parts
    # Walk parents from nearest upward looking for a known bucket.
    for p in reversed(parts[:-1]):
        if p in _DOMAIN_FROM_PATH:
            d = _DOMAIN_FROM_PATH[p]
            if d != "resiliency":
                return d
    # Fell through with infrastructure / resiliency — sharpen via keyword match.
    blob = (mcp_name + " " + module_path.stem).lower()
    for keyword, dom in _INFRA_KEYWORD_DOMAIN:
        if keyword in blob:
            return dom
    # Final default: resiliency (matches the catch-all bucket).
    return "resiliency"


def _infer_tags(mcp_name: str, module_stem: str) -> tuple[str, ...]:
    """Infer tags from name keywords (intersection with TAG_VOCABULARY)."""
    blob = (mcp_name + " " + module_stem).lower().replace("_", "-")
    hits: set[str] = set()
    for tag in TAG_VOCABULARY:
        if tag in blob:
            hits.add(tag)
    # add_* + "auth" filename picks up 'auth' via the word match above; good.
    return tuple(sorted(hits))


def _canonical_tool_name(verb: str, domain: str, mcp_name: str) -> str:
    """Apply the `fastapi_<domain>_<verb>_<noun>` convention.

    If the existing MCP name already has the `fastapi_` prefix, extract the
    noun tail (everything after the trailing verb prefix); otherwise, use the
    module stem stripped of the verb prefix as the noun.

    Commit 1 scope: we RECORD this as `name`, keeping the original as
    `legacy_name` when they differ. No actual MCP registration renaming
    happens until the dedicated rename commit.
    """
    # If the name already follows the canonical form, return as-is
    # (prevents double-prefix when the name was rewritten in a prior pass).
    canonical_prefix = f"fastapi_{domain}_{verb}_"
    if mcp_name.startswith(canonical_prefix):
        return mcp_name

    # Remove leading "fastapi_".
    stripped = mcp_name.removeprefix("fastapi_")
    # Strip leading "<domain>_" if present (historical names often embed it).
    if stripped.startswith(f"{domain}_"):
        stripped = stripped[len(domain) + 1 :]
    # Strip the verb prefix from the start.
    for prefix, v in _VERB_FROM_PREFIX.items():
        if v == verb and stripped.startswith(prefix):
            stripped = stripped[len(prefix) :]
            break
    noun = stripped
    return f"fastapi_{domain}_{verb}_{noun}"


# ---------------------------------------------------------------------------
# Tool scanning — reuses the same MCP_TOOL discovery path as mcp_tools/
# ---------------------------------------------------------------------------


def _load_mcp_tool_from_source(py: Path) -> dict | None:
    """Extract the MCP_TOOL dict from a Python module WITHOUT executing it.

    We parse the AST so we don't import optional dependencies (Stripe,
    Celery, …) at manifest time. Only literal dict MCP_TOOL declarations
    are supported; anything else is skipped.
    """
    try:
        tree = ast.parse(py.read_text(encoding="utf-8"))
    except (SyntaxError, OSError):
        return None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not (isinstance(target, ast.Name) and target.id == "MCP_TOOL"):
                continue
            if not isinstance(node.value, (ast.Dict, ast.Call)):
                # `MCP_TOOL = {...}` — expect literal dict
                if isinstance(node.value, ast.Dict):
                    return _ast_literal_dict(node.value)
                return None
            if isinstance(node.value, ast.Dict):
                return _ast_literal_dict(node.value)
    return None


def _ast_literal_dict(node: ast.Dict) -> dict | None:
    """Evaluate an ast.Dict into a Python dict if every entry is a literal."""
    out: dict = {}
    for k, v in zip(node.keys, node.values, strict=False):
        try:
            kk = ast.literal_eval(k) if k is not None else None
            vv = ast.literal_eval(v)
        except (ValueError, SyntaxError):
            return None
        out[kk] = vv
    return out


def _scan_tools() -> list[dict]:
    """Return raw MCP_TOOL + source-path tuples across every scan root."""
    out: list[dict] = []
    seen_names: dict[str, Path] = {}
    for _label, root in TOOL_SCAN_ROOTS:
        if not root.exists():
            continue
        for py in sorted(root.rglob("*.py")):
            if "__pycache__" in py.parts:
                continue
            # Skip test files UNLESS they declare MCP_TOOL (rare, but some
            # tool files legitimately start with `test_` — e.g. a tool that
            # emits test scaffolding).
            if py.name.startswith("test_"):
                try:
                    if "MCP_TOOL" not in py.read_text(encoding="utf-8"):
                        continue
                except (OSError, UnicodeDecodeError):
                    continue
            meta = _load_mcp_tool_from_source(py)
            if not meta:
                continue
            name = meta.get("name")
            if not name:
                continue
            if name in seen_names:
                raise ManifestError(
                    f"duplicate MCP_TOOL name {name!r}: {seen_names[name]} AND {py}"
                )
            seen_names[name] = py
            meta["_path"] = str(py.relative_to(SKILL_ROOT))
            out.append(meta)
    return out


_CORE_VENOUS_IMPORT_RE = re.compile(
    r"(?:from|import)\s+core\.venous\.(?!_adapters\b|_staging\b)"
    r"[a-z][a-z_]*\.(?P<name>[A-Z][A-Za-z0-9]+)"
)


def _extract_primitive_imports(py: Path, declared: tuple[str, ...] = ()) -> tuple[str, ...]:
    """Return the set of `core.venous.<ns>.<Name>` references *actually used*.

    Precedence:

      0. MCP_TOOL.imports_primitives — if the author explicitly declared
         which primitives the emitted code references, trust the declaration.
         This is authoritative; inference below is only a fallback.
      1. Python imports (AST scan) — captures adapter + compose-like tools
         that import primitives at module load.
      2. String-embedded imports — captures generator tools that emit
         `from core.venous.<ns>.<Name> import <Name>` inside templated
         strings. We parse the AST, collect every string literal that is
         NOT a docstring, then regex-match `(from|import) core.venous.*`
         against that set. This is strict: a primitive mentioned only in
         prose (comments, docstrings) does NOT populate primitives_used —
         it has to be an actual import line.

    `declared` is the MCP_TOOL["imports_primitives"] list (paths like
    ``core.venous.resiliency.RateLimiter``); we extract the last segment
    as the primitive name.

    The `_adapters` and `_staging` sub-roots are excluded — those are
    meta namespaces, not primitives.
    """
    # Channel 0: explicit MCP_TOOL declaration wins.
    if declared:
        names: set[str] = set()
        for path in declared:
            parts = str(path).split(".")
            if len(parts) >= 4 and parts[0] == "core" and parts[1] == "venous":
                if parts[2] in ("_adapters", "_staging"):
                    continue
                names.add(parts[3])
        return tuple(sorted(names))
    try:
        source = py.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ()
    names: set[str] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ()

    # Channel 1: real Python imports.
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.startswith("core.venous.")
        ):
            parts = node.module.split(".")
            if len(parts) >= 4 and parts[2] not in ("_adapters", "_staging"):
                names.add(parts[3])
            elif len(parts) >= 3 and parts[2] not in ("_adapters", "_staging"):
                for alias in node.names:
                    names.add(alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("core.venous."):
                    parts = alias.name.split(".")
                    if len(parts) >= 4 and parts[2] not in ("_adapters", "_staging"):
                        names.add(parts[3])

    # Channel 2: string-embedded `from/import core.venous.*` inside non-
    # docstring string constants. Docstrings are excluded so narrative
    # prose doesn't create false positives.
    docstring_ids: set[int] = set()

    def _collect_docstring_ids(n: ast.AST) -> None:
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(n, "body", None) or []
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstring_ids.add(id(body[0].value))
        for child in ast.iter_child_nodes(n):
            _collect_docstring_ids(child)

    _collect_docstring_ids(tree)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant):
            continue
        if not isinstance(node.value, str):
            continue
        if id(node) in docstring_ids:
            continue
        for m in _CORE_VENOUS_IMPORT_RE.finditer(node.value):
            names.add(m.group("name"))
    return tuple(sorted(names))


# ---------------------------------------------------------------------------
# Primitives + recipes
# ---------------------------------------------------------------------------


def _load_primitives() -> list[PrimitiveEntry]:
    data = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    out: list[PrimitiveEntry] = []
    for entry in data.get("primitives", []):
        ns = entry["namespace"]
        name = entry["name"]
        module_path = VENOUS_ROOT / ns / name / f"{name}.py"
        out.append(
            PrimitiveEntry(
                name=name,
                namespace=ns,
                concern=entry.get("concern", ns),
                purpose=entry.get("purpose", "")[:140],
                compose_with=tuple(entry.get("compose_with") or []),
                module_path=str(module_path.relative_to(SKILL_ROOT))
                if module_path.exists()
                else f"core/venous/{ns}/{name}/",
            )
        )
    # Append staged primitives from _staging/ (excluding _quarantine), then
    # globally sort so BM25 and byte-stable hashing see a single ordered list.
    out.extend(_load_staged_primitives(registered_names={p.name for p in out}))
    out.sort(key=lambda p: (p.namespace, p.name))
    return out


def _load_staged_primitives(*, registered_names: set[str]) -> list[PrimitiveEntry]:
    """Surface every pre-audited staged primitive as `status="staged"`.

    The staging area (`core/venous/_staging/<ns>/<Name>/`) carries full
    HuGR shell (contract.json, protocol, md, tests) but `REPLACE_ME`
    stubs in the impl. We index them so the agent can discover them
    via `fastapi_meta_search` and decide when a benchmark gap justifies
    promotion — but the `staged` status flags them as non-production.
    Quarantined primitives are skipped.
    """
    root = VENOUS_ROOT / "_staging"
    if not root.exists():
        return []
    out: list[PrimitiveEntry] = []
    seen: set[str] = set()
    for ns_dir in sorted(root.iterdir()):
        if not ns_dir.is_dir() or ns_dir.name.startswith("_"):
            continue
        ns = ns_dir.name
        for prim_dir in sorted(ns_dir.iterdir()):
            if not prim_dir.is_dir():
                continue
            name = prim_dir.name
            # Require PascalCase naming — excludes helper snake_case dirs like
            # `check_rate_limit` that crept into the staging pool.
            if not (name[:1].isupper() and "_" not in name):
                continue
            # A staged primitive must have its own <Name>.py.
            if not (prim_dir / f"{name}.py").exists():
                continue
            if name in registered_names or name in seen:
                # Do not duplicate a primitive that already lives in the
                # production registry, nor a same-named primitive from a
                # different _staging namespace.
                continue
            seen.add(name)
            purpose = _first_doc_line(prim_dir / f"{name}.md")[:140]
            out.append(
                PrimitiveEntry(
                    name=name,
                    namespace=ns,
                    concern=ns,
                    purpose=purpose
                    or "Staged primitive; promote via engine/extraction before use.",
                    compose_with=(),
                    module_path=str(prim_dir.relative_to(SKILL_ROOT)) + "/",
                    status="staged",
                )
            )
    return sorted(out, key=lambda p: (p.namespace, p.name))


def _first_doc_line(md_path: Path) -> str:
    """Return the first non-empty, non-heading line from a primitive .md."""
    if not md_path.exists():
        return ""
    try:
        for line in md_path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or s.startswith("---"):
                continue
            return re.sub(r"\s+", " ", s)
    except (OSError, UnicodeDecodeError):
        pass
    return ""


_RECIPE_BULLET_RE = re.compile(
    r"^\s*-\s+(?P<body>.+?)(?=\n\s*-\s|\n\n|\Z)",
    re.DOTALL | re.MULTILINE,
)
_RECIPE_PRIM_REF_RE = re.compile(r"`(?P<name>[A-Z][A-Za-z0-9]+)`")


def _extract_recipes(primitives: list[PrimitiveEntry]) -> list[RecipeEntry]:
    """Parse each primitive .md for its Compose-with bullets → recipes."""
    out: list[RecipeEntry] = []
    for prim in primitives:
        md_path = SKILL_ROOT / prim.module_path
        if md_path.is_dir():
            md_path = md_path / f"{prim.name}.md"
        else:
            md_path = md_path.with_name(f"{prim.name}.md")
        if not md_path.exists():
            continue
        body = md_path.read_text(encoding="utf-8")
        m = re.search(r"## Compose with.*?(?=\n## |\Z)", body, re.DOTALL | re.IGNORECASE)
        if not m:
            continue
        section = m.group(0)
        for idx, bullet in enumerate(_RECIPE_BULLET_RE.finditer(section), 1):
            text = bullet.group("body").strip()
            refs = tuple(sorted(set(h.group("name") for h in _RECIPE_PRIM_REF_RE.finditer(text))))
            # Skip bullets that don't reference a primitive directly.
            if not refs:
                continue
            intent = _extract_intent(text)
            rid = f"{prim.name}__{idx:02d}_{_slugify(intent or text)[:40]}"
            out.append(
                RecipeEntry(
                    id=rid,
                    source_primitive=prim.name,
                    primitives=refs,
                    intent=intent or "",
                    description=_clean_desc(text),
                )
            )
    out.sort(key=lambda r: r.id)
    return out


def _extract_intent(text: str) -> str:
    """Pull the bolded intent after an arrow, e.g. **`A` + `B` → the intent**."""
    m = re.search(r"→\s*\*\*(?P<intent>.+?)\*\*", text, re.DOTALL)
    if m:
        return re.sub(r"\s+", " ", m.group("intent")).strip()
    m = re.search(r"→\s*(?P<intent>.+?)(?=\.|$)", text, re.DOTALL)
    if m:
        return re.sub(r"\s+", " ", m.group("intent")).strip()[:120]
    return ""


def _clean_desc(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()[:280]


def _slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "recipe"


# ---------------------------------------------------------------------------
# Skill + bundle derivation (schema v2)
#
# Schema v2 makes the tool surface hierarchical: skill → bundles → tools.
# Today the kit ships ONE skill (`SKILL-001-fastapi-production`); federation
# handoff will add more under the same shape (see ADR-0003).
#
# Bundle derivation:
#   - Tools under `adapt/extend/<bundle>/` map to `<bundle>` directly
#     (6 bundles: api_design, auth_access, crud_data, infrastructure,
#     realtime, testing_tools — the six dirs that exist today).
#   - Tools outside `adapt/extend/` (generators/, modules/, core/tools/,
#     adapt/{evolve,operate,proactive,verify}/, etc.) inherit a bundle
#     by their domain affinity. Six bundles cover the ten domains:
#         auth         → auth_access
#         data         → crud_data
#         api          → api_design
#         realtime     → realtime
#         testing      → testing_tools
#         resiliency, observability, compliance, deployment, meta
#                      → infrastructure (the "ops + cross-cutting" bucket)
#
# Bundle tags are a small curated hint set for search; the tag list per
# bundle is fixed at v2 and ⊆ a freeform vocabulary (NOT necessarily
# TAG_VOCABULARY — bundles are coarser than per-tool tags).
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


def _infer_bundle(module_path: Path, domain: str) -> str:
    """Return the bundle name a tool belongs to.

    Path-based for `adapt/extend/<bundle>/...`, domain-based otherwise.
    Every tool resolves to one of the six bundles in `_BUNDLE_NAMES`.
    """
    parts = module_path.parts
    if len(parts) >= 3 and parts[0] == "adapt" and parts[1] == "extend":
        b = parts[2]
        if b in _BUNDLE_NAMES:
            return b
    # Fall back to domain mapping (e.g. generators/, modules/, core/tools/).
    return _DOMAIN_TO_BUNDLE.get(domain, "infrastructure")


def _build_skills(tools: list[ToolEntry]) -> tuple[SkillEntry, ...]:
    """Derive the single SkillEntry from the assembled tool list.

    The skill's bundle list is exactly `_BUNDLE_NAMES` with per-bundle
    `tool_count` = number of tools whose `bundle` field matches. Bundle
    tags come from `_BUNDLE_TAGS`. The skill's own version reads from
    `skills/<SKILL_ID>/VERSION` if present; falls back to "0.0.0".
    """
    skill_version = "0.0.0"
    vfile = SKILL_ROOT / "VERSION"
    if vfile.exists():
        skill_version = vfile.read_text(encoding="utf-8").strip() or skill_version

    counts: dict[str, int] = dict.fromkeys(_BUNDLE_NAMES, 0)
    for t in tools:
        if t.bundle in counts:
            counts[t.bundle] += 1

    bundles = tuple(
        BundleEntry(
            name=name,
            tool_count=counts[name],
            tags=_BUNDLE_TAGS.get(name, ()),
        )
        for name in _BUNDLE_NAMES
    )
    return (
        SkillEntry(
            name=SKILL_ID,
            version=skill_version,
            type="local",
            bundles=bundles,
        ),
    )


# ---------------------------------------------------------------------------
# Tool entry assembly
# ---------------------------------------------------------------------------


def _tool_entries(raw_tools: list[dict], primitive_names: set[str]) -> list[ToolEntry]:
    entries: list[ToolEntry] = []
    errors: list[str] = []
    for meta in raw_tools:
        mcp_name = meta["name"]
        module_path = Path(meta["_path"])
        # Respect an explicit canonical name: `fastapi_<domain>_<verb>_<noun>`.
        # If the author set it that way, trust it — don't re-infer and risk
        # misclassifying (e.g. a file named `compose.py` whose keyword would
        # otherwise resolve to "deployment").
        verb, domain = _parse_canonical_name(mcp_name)
        if verb is None:
            verb = _infer_verb(mcp_name, module_path.stem)
            domain = _infer_domain(module_path, mcp_name)
        tags = _infer_tags(mcp_name, module_path.stem)

        # Validate verb + domain (must be in closed vocab)
        if verb not in VERBS:
            errors.append(f"{mcp_name}: inferred verb {verb!r} not in VERBS")
            continue
        if domain not in DOMAINS:
            errors.append(f"{mcp_name}: inferred domain {domain!r} not in DOMAINS")
            continue
        for t in tags:
            if t not in TAG_VOCABULARY:
                errors.append(f"{mcp_name}: tag {t!r} not in TAG_VOCABULARY")

        canonical = _canonical_tool_name(verb, domain, mcp_name)
        legacy = None if canonical == mcp_name else mcp_name

        description = meta.get("description") or ""
        synopsis = re.sub(r"\s+", " ", description).strip().rstrip(".")[:100]
        when_to_call = description.strip() or synopsis

        declared = tuple(meta.get("imports_primitives") or ())
        primitives_used = _extract_primitive_imports(SKILL_ROOT / module_path, declared=declared)
        # Drop any primitive we reference that isn't actually registered.
        primitives_used = tuple(p for p in primitives_used if p in primitive_names)

        # Collect matching test paths (test_<stem>.py neighbour).
        test_path = module_path.with_name(f"test_{module_path.name}")
        test_paths = (str(test_path),) if (SKILL_ROOT / test_path).exists() else ()

        bundle = _infer_bundle(module_path, domain)

        try:
            entries.append(
                ToolEntry(
                    name=canonical,
                    legacy_name=legacy,
                    verb=verb,
                    domain=domain,
                    skill=SKILL_ID,
                    bundle=bundle,
                    synopsis=synopsis or mcp_name,
                    when_to_call=when_to_call,
                    when_not_to_call="",
                    tags=tags,
                    tier=1 if domain == "meta" else 2,
                    status="stable",
                    since="",
                    module_path=str(module_path),
                    test_paths=test_paths,
                    primitives_used=primitives_used,
                )
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{mcp_name}: {exc}")

    if errors:
        joined = "\n  - ".join(errors[:10])
        raise ManifestError(f"{len(errors)} tool-entry violation(s):\n  - {joined}")

    entries.sort(key=lambda e: (e.domain, e.verb, e.name))
    return entries


# ---------------------------------------------------------------------------
# Top-level builders
# ---------------------------------------------------------------------------


def _git_short_sha() -> str:
    try:
        import subprocess

        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        return (out.stdout or "unknown").strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def build() -> CatalogManifest:
    primitives = _load_primitives()
    primitive_names = {p.name for p in primitives}
    recipes = _extract_recipes(primitives)
    raw_tools = _scan_tools()
    tools = _tool_entries(raw_tools, primitive_names)
    skills = _build_skills(tools)

    # Schema v2 counts (see ADR-0003). `tools_total` replaces the v1
    # `tools` key; `tools_local` + `tools_federated` split the surface
    # so federation handoff can land without re-shaping the catalog.
    tools_local = len(tools)  # everything in this manifest is local today
    tools_federated = 0
    counts = {
        "tools_total": tools_local + tools_federated,
        "tools_local": tools_local,
        "tools_federated": tools_federated,
        "primitives": len(primitives),
        "recipes": len(recipes),
        "skills": len(skills),
        "bundles": sum(len(s.bundles) for s in skills),
    }

    manifest = CatalogManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        kit_commit=_git_short_sha(),
        generated_at=datetime.now(tz=UTC).isoformat(timespec="seconds"),
        verbs=VERBS,  # type: ignore[arg-type]
        domains=DOMAINS,  # type: ignore[arg-type]
        tags=tuple(sorted(TAG_VOCABULARY)),
        skills=skills,
        tools=tuple(tools),
        primitives=tuple(primitives),
        recipes=tuple(recipes),
        counts=counts,
    )
    return manifest


def write(manifest: CatalogManifest, path: Path = CATALOG_PATH) -> str:
    """Write catalog + persist the stable content hash for consumers.

    The hash is computed over catalog content with the two non-deterministic
    fields (`generated_at`, `kit_commit`) stripped, AND with any prior
    `stable_hash` value itself stripped (otherwise the hash would be
    circular: computing it requires the file to not yet contain it).

    Consumers (Forge, agent, CI) read `stable_hash` from the on-disk
    catalog to pin the skill surface for a session / benchmark run.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = manifest.model_dump(mode="json")

    # Compute hash first, over non-hash fields only.
    stable = {
        k: v for k, v in data.items() if k not in ("generated_at", "kit_commit", "stable_hash")
    }
    digest = hashlib.sha256(json.dumps(stable, indent=2, sort_keys=True).encode()).hexdigest()

    # Write catalog WITH the hash embedded so consumers can read it back.
    data["stable_hash"] = digest
    path.write_text(json.dumps(data, indent=2, sort_keys=False), encoding="utf-8")
    return digest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("cmd", choices=("build", "verify"))
    parser.add_argument("--out", type=Path, default=CATALOG_PATH)
    args = parser.parse_args(argv)

    try:
        m = build()
    except ManifestError as exc:
        print(f"manifest build failed:\n{exc}", file=sys.stderr)
        return 1

    h1 = write(m, args.out)
    print(
        f"skills={m.counts['skills']}  bundles={m.counts['bundles']}  "
        f"tools={m.counts['tools_total']}  "
        f"primitives={m.counts['primitives']}  recipes={m.counts['recipes']}"
    )
    try:
        display = args.out.relative_to(SKILL_ROOT)
    except ValueError:
        display = args.out
    print(f"stable_hash={h1[:12]}  written to {display}")

    if args.cmd == "verify":
        m2 = build()
        h2 = write(m2, args.out)
        if h1 != h2:
            print(f"FAIL: hash drift between builds ({h1[:12]} vs {h2[:12]})", file=sys.stderr)
            return 1
        print("idempotent: stable hash matches across two builds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
