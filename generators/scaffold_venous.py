"""Copy `core.venous` primitives into a generated project tree.

Implements CONTRACT.md §B1.0 — the copy-in distribution strategy ratified
in ADR 0002 (`/docs/decisions/0002-core-venous-distribution.md`).

Public API
----------
- :func:`copy_primitive` — copy a single primitive directory.
- :func:`copy_adapter` — copy a framework adapter module.
- :func:`ensure_primitives` — idempotently ensure a list of primitives
  (and optional adapters) are present in the target project, recording
  provenance in ``<project_dir>/.venous_manifest.json``.

Design notes
------------
* Only the **production surface** is copied: ``<Name>.py``, ``<Name>.md``,
  ``<Name>.contract.json``, ``invariant_bindings.json``, ``__init__.py``
  (and the ``manifest.json`` when present).  Tests, TLA, audit reports,
  persona reviews, conftest, state machines etc. stay in the skill —
  they are dev-time artefacts, not runtime deps.
* Each copied ``.py`` file gets an MIT attribution footer pointing back
  to the source commit (best-effort; fallback to ``"unknown"`` when
  ``git`` is unavailable).
* Running :func:`ensure_primitives` twice is a no-op: the manifest is
  consulted BEFORE any filesystem work, and the function returns a
  ``Manifest`` whose ``copied`` list is empty on the second call.
* ``compose_with`` entries in the registry are composition hints, not
  dependencies, and are NOT transitively copied.  If a future registry
  gains an explicit ``depends_on`` key it will be resolved here; today
  we require callers to pass names explicitly.

Example::

    from generators.scaffold_venous import ensure_primitives

    manifest = ensure_primitives(
        project_dir="/tmp/myapp",
        names=["core.venous.resiliency.GracefulShutdown"],
    )
    print(manifest.copied)  # first run: one entry; second run: []
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

MCP_TOOL = {
    "name": "fastapi_resiliency_generate_venous",
    "description": (
        "Idempotently copy core.venous primitives (and optional adapters) "
        "into a generated project, recording provenance."
    ),
    "tags": ["generator", "scaffold", "venous"],
    "entry": "ensure_primitives",
    "annotations": {"readOnlyHint": False, "destructiveHint": False},
}


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SKILL_ROOT = Path(__file__).resolve().parent.parent
"""Absolute path to the skill root (``skills/SKILL-001-fastapi-production``)."""

SOURCE_VENOUS = SKILL_ROOT / "core" / "venous"

MANIFEST_FILENAME = ".venous_manifest.json"
MANIFEST_VERSION = 1
LICENSE = "MIT"
SOURCE_SKILL_NAME = "SKILL-001-fastapi-production"

# Files we ship into a generated project. Everything else in a primitive
# directory is dev-only and stays in the skill repo.
_PRIMITIVE_PROD_FILES = frozenset(
    {
        "__init__.py",
        "invariant_bindings.json",
    }
)

# Suffix-based allow list — primitive-name-derived files (e.g. ``Foo.py``,
# ``Foo.md``, ``Foo.contract.json``, ``Foo.manifest.json``).
_PRIMITIVE_PROD_SUFFIXES = (".py", ".md", ".contract.json", ".manifest.json")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CopyResult:
    """Outcome of a single :func:`copy_primitive` invocation.

    Attributes:
        qualified_name: Canonical name ``core.venous.<ns>.<Name>``.
        destination: Absolute path of the destination directory.
        files_written: Absolute paths of files written THIS call.
            Empty when the primitive was already present (idempotency).
        already_present: ``True`` when the destination existed with the
            expected entry-point file before the call.
    """

    qualified_name: str
    destination: str
    files_written: list[str]
    already_present: bool


@dataclass
class Manifest:
    """In-memory view of ``<project>/.venous_manifest.json``.

    Attributes:
        path: Absolute path to the on-disk manifest.
        version: Schema version (see :data:`MANIFEST_VERSION`).
        copied_at: ISO-8601 UTC timestamp of the most recent write.
        primitives: List of dicts — one per primitive ever shipped.
            Each dict has keys ``qualified_name``, ``source_skill``,
            ``source_commit``, ``license``.
        adapters: List of dicts — one per adapter ever shipped. Same
            schema as ``primitives`` with the qualified name under the
            ``_adapters`` namespace.
        copied: Names copied THIS call (useful for callers that want to
            know what actually changed on disk).
    """

    path: str
    version: int = MANIFEST_VERSION
    copied_at: str = ""
    primitives: list[dict] = field(default_factory=list)
    adapters: list[dict] = field(default_factory=list)
    copied: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _source_commit() -> str:
    """Return the git commit hash of the skill repo, or ``"unknown"``."""
    try:
        out = subprocess.run(
            ["git", "-C", str(SKILL_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
        sha = out.stdout.strip()
        return sha if sha else "unknown"
    except (FileNotFoundError, subprocess.SubprocessError):
        return "unknown"


def _source_commit_iso_time() -> str:
    """Return the source commit's author timestamp as ISO-8601, or ``"unknown"``.

    Used as the deterministic value for ``Manifest.copied_at`` so re-running
    the scaffold against the SAME source commit produces byte-identical
    manifests across host clocks. (Wave I-1 generator non-determinism fix.)
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(SKILL_ROOT), "log", "-1", "--format=%aI", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
        iso = out.stdout.strip()
        return iso if iso else "unknown"
    except (FileNotFoundError, subprocess.SubprocessError):
        return "unknown"


def _parse_qualified_name(qualified_name: str) -> tuple[str, str]:
    """Split ``core.venous.<ns>.<Name>`` into ``(<ns>, <Name>)``.

    Raises:
        ValueError: If *qualified_name* does not start with
            ``core.venous.`` or has a missing namespace / name.
    """
    prefix = "core.venous."
    if not qualified_name.startswith(prefix):
        raise ValueError(
            f"Expected qualified name 'core.venous.<ns>.<Name>', got {qualified_name!r}"
        )
    tail = qualified_name[len(prefix):]
    parts = tail.split(".")
    if len(parts) != 2 or not all(parts):
        raise ValueError(
            f"Expected 'core.venous.<ns>.<Name>' with exactly one namespace, got {qualified_name!r}"
        )
    return parts[0], parts[1]


def _parse_adapter_name(qualified_name: str) -> tuple[str, str]:
    """Split ``core.venous._adapters.<framework>.<Module>`` into parts.

    Returns:
        Tuple ``(framework, module)`` where ``module`` is the bare file
        name without the ``.py`` suffix.
    """
    prefix = "core.venous._adapters."
    if not qualified_name.startswith(prefix):
        raise ValueError(
            f"Expected adapter name 'core.venous._adapters.<framework>.<Module>', got {qualified_name!r}"
        )
    tail = qualified_name[len(prefix):]
    parts = tail.split(".")
    if len(parts) != 2 or not all(parts):
        raise ValueError(
            f"Expected 'core.venous._adapters.<framework>.<Module>', got {qualified_name!r}"
        )
    return parts[0], parts[1]


def _is_prod_file(path: Path) -> bool:
    """Return ``True`` if *path* is part of the primitive's production surface."""
    if path.name in _PRIMITIVE_PROD_FILES:
        return True
    if path.name.endswith(_PRIMITIVE_PROD_SUFFIXES):
        # Exclude obvious dev-only suffixes.
        dev_markers = (
            "test_",
            "behavioral_",
            "chaos_",
            "concurrent_",
            "metamorphic_",
            "observability_",
            "state_machine_",
            "conftest",
            "_origin",
            "_provenance",
            "_t0_report",
            "dashboard",
            "persona_reviews",
            "proposed_invariants",
            "observability_schema",
        )
        if any(path.name.startswith(m) or path.stem == m.rstrip("_") for m in dev_markers):
            return False
        return True
    return False


def _attribution_footer(source_rel: str, commit: str) -> str:
    """Return the MIT attribution footer to append to copied ``.py`` files."""
    return (
        "\n\n# ---------------------------------------------------------------------------\n"
        f"# Copied from HuGR Arsenal {commit} under {LICENSE} license.\n"
        f"# Source: skills/{SOURCE_SKILL_NAME}/{source_rel}\n"
        "# Do not hand-edit — regenerate via the scaffold_venous mechanism.\n"
        "# ---------------------------------------------------------------------------\n"
    )


def _ensure_namespace_init(dest_dir: Path, docstring: str) -> Path | None:
    """Create ``dest_dir/__init__.py`` with *docstring* if missing.

    Returns:
        The ``__init__.py`` path when newly written, else ``None``.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    init = dest_dir / "__init__.py"
    if init.exists():
        return None
    init.write_text(f'"""{docstring}"""\n')
    return init


def _load_manifest(project_dir: Path) -> Manifest:
    """Load ``<project>/.venous_manifest.json`` if present, else return fresh."""
    path = project_dir / MANIFEST_FILENAME
    if not path.exists():
        return Manifest(path=str(path))
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return Manifest(path=str(path))
    return Manifest(
        path=str(path),
        version=int(data.get("version", MANIFEST_VERSION)),
        copied_at=str(data.get("copied_at", "")),
        primitives=list(data.get("primitives", [])),
        adapters=list(data.get("adapters", [])),
    )


def _write_manifest(manifest: Manifest) -> None:
    """Persist *manifest* to disk with stable key ordering."""
    payload = {
        "version": manifest.version,
        "copied_at": manifest.copied_at,
        "primitives": manifest.primitives,
        "adapters": manifest.adapters,
    }
    Path(manifest.path).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def copy_primitive(project_dir: str, qualified_name: str) -> CopyResult:
    """Copy a single primitive's production surface into *project_dir*.

    Only ships ``<Name>.py``, ``<Name>.md``, ``<Name>.contract.json``,
    ``<Name>.manifest.json`` (when present), ``invariant_bindings.json``,
    and ``__init__.py``.  Everything else in the primitive's source
    directory (tests, TLA specs, persona reviews, audit artefacts) stays
    in the skill repo.

    Args:
        project_dir: Root of the generated project.
        qualified_name: Canonical primitive name, e.g.
            ``core.venous.resiliency.GracefulShutdown``.

    Returns:
        A :class:`CopyResult` describing what was written.

    Raises:
        FileNotFoundError: If the source primitive directory is missing.
        ValueError: If *qualified_name* is malformed.
    """
    ns, name = _parse_qualified_name(qualified_name)
    src_dir = SOURCE_VENOUS / ns / name
    if not src_dir.is_dir():
        raise FileNotFoundError(f"primitive source not found: {src_dir}")

    project = Path(project_dir)
    dest_dir = project / "core" / "venous" / ns / name
    entry_point = dest_dir / f"{name}.py"

    if entry_point.exists():
        return CopyResult(
            qualified_name=qualified_name,
            destination=str(dest_dir),
            files_written=[],
            already_present=True,
        )

    # Ensure namespace __init__ chain exists.
    written: list[Path] = []
    for nested, doc in (
        (project / "core", "Top-level package for HuGR-shipped primitives."),
        (project / "core" / "venous", "Framework-agnostic primitives copied from HuGR Arsenal."),
        (project / "core" / "venous" / ns, f"Primitives in the `{ns}` concern namespace."),
    ):
        created = _ensure_namespace_init(nested, doc)
        if created:
            written.append(created)

    dest_dir.mkdir(parents=True, exist_ok=True)
    commit = _source_commit()
    for src in sorted(src_dir.iterdir()):
        if not src.is_file() or not _is_prod_file(src):
            continue
        dst = dest_dir / src.name
        if dst.exists():
            continue
        if src.suffix == ".py":
            body = src.read_text()
            source_rel = f"core/venous/{ns}/{name}/{src.name}"
            body += _attribution_footer(source_rel, commit)
            dst.write_text(body)
        else:
            shutil.copy2(src, dst)
        written.append(dst)

    return CopyResult(
        qualified_name=qualified_name,
        destination=str(dest_dir),
        files_written=[str(p) for p in written],
        already_present=False,
    )


def copy_adapter(project_dir: str, qualified_name: str) -> CopyResult:
    """Copy a single framework adapter module into *project_dir*.

    Adapters live under ``core/venous/_adapters/<framework>/`` in the
    skill repo; they carry no tests or state-machine artefacts so the
    whole file is shipped as-is (with the attribution footer).

    Args:
        project_dir: Root of the generated project.
        qualified_name: Canonical adapter name, e.g.
            ``core.venous._adapters.fastapi.GracefulShutdownAdapter``.

    Returns:
        A :class:`CopyResult`.
    """
    framework, module = _parse_adapter_name(qualified_name)
    src_file = SOURCE_VENOUS / "_adapters" / framework / f"{module}.py"
    if not src_file.is_file():
        raise FileNotFoundError(f"adapter source not found: {src_file}")

    project = Path(project_dir)
    dest_dir = project / "core" / "venous" / "_adapters" / framework
    dest_file = dest_dir / f"{module}.py"

    if dest_file.exists():
        return CopyResult(
            qualified_name=qualified_name,
            destination=str(dest_dir),
            files_written=[],
            already_present=True,
        )

    written: list[Path] = []
    # Only create a placeholder __init__.py for chain ancestors that lack one.
    # The framework-specific __init__.py is copied from source below (if
    # present) so adapter package-level re-exports travel with the adapter.
    for nested, doc in (
        (project / "core", "Top-level package for HuGR-shipped primitives."),
        (project / "core" / "venous", "Framework-agnostic primitives copied from HuGR Arsenal."),
        (project / "core" / "venous" / "_adapters", "Framework adapters over framework-agnostic primitives."),
    ):
        created = _ensure_namespace_init(nested, doc)
        if created:
            written.append(created)

    commit = _source_commit()
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Ship the framework's __init__.py from source so package-level imports
    # like `from core.venous._adapters.stripe import StripeBillingAdapter`
    # resolve. If the source has no __init__.py, fall back to the bare
    # docstring placeholder (matches the pre-Rails behaviour).
    framework_init_dst = dest_dir / "__init__.py"
    if not framework_init_dst.exists():
        framework_init_src = SOURCE_VENOUS / "_adapters" / framework / "__init__.py"
        if framework_init_src.is_file():
            init_body = framework_init_src.read_text()
            init_rel = f"core/venous/_adapters/{framework}/__init__.py"
            init_body += _attribution_footer(init_rel, commit)
            framework_init_dst.write_text(init_body)
        else:
            framework_init_dst.write_text(f'"""{framework} adapters."""\n')
        written.append(framework_init_dst)

    body = src_file.read_text()
    source_rel = f"core/venous/_adapters/{framework}/{module}.py"
    body += _attribution_footer(source_rel, commit)
    dest_file.write_text(body)
    written.append(dest_file)

    return CopyResult(
        qualified_name=qualified_name,
        destination=str(dest_dir),
        files_written=[str(p) for p in written],
        already_present=False,
    )


def ensure_primitives(
    project_dir: str,
    names: list[str],
    *,
    adapters: list[str] | None = None,
) -> Manifest:
    """Ensure *names* (and optionally *adapters*) are shipped to *project_dir*.

    Idempotent: running twice writes nothing new and returns a manifest
    with ``copied == []`` on the second call.

    Args:
        project_dir: Root of the generated project.
        names: Canonical primitive names
            (``core.venous.<ns>.<Name>``).
        adapters: Optional canonical adapter names
            (``core.venous._adapters.<framework>.<Module>``).

    Returns:
        The :class:`Manifest` as of the end of this call.
    """
    project = Path(project_dir)
    project.mkdir(parents=True, exist_ok=True)
    manifest = _load_manifest(project)
    commit = _source_commit()
    copied: list[str] = []

    existing_primitives = {p["qualified_name"] for p in manifest.primitives}
    for qualified in names:
        result = copy_primitive(project_dir, qualified)
        if not result.already_present and qualified not in existing_primitives:
            manifest.primitives.append(
                {
                    "qualified_name": qualified,
                    "source_skill": SOURCE_SKILL_NAME,
                    "source_commit": commit,
                    "license": LICENSE,
                }
            )
            copied.append(qualified)
            existing_primitives.add(qualified)
        elif qualified not in existing_primitives:
            # Files were already on disk from an earlier run; still
            # register them in the manifest so provenance is complete.
            manifest.primitives.append(
                {
                    "qualified_name": qualified,
                    "source_skill": SOURCE_SKILL_NAME,
                    "source_commit": commit,
                    "license": LICENSE,
                }
            )
            existing_primitives.add(qualified)

    existing_adapters = {a["qualified_name"] for a in manifest.adapters}
    for qualified in adapters or []:
        result = copy_adapter(project_dir, qualified)
        if not result.already_present and qualified not in existing_adapters:
            manifest.adapters.append(
                {
                    "qualified_name": qualified,
                    "source_skill": SOURCE_SKILL_NAME,
                    "source_commit": commit,
                    "license": LICENSE,
                }
            )
            copied.append(qualified)
            existing_adapters.add(qualified)
        elif qualified not in existing_adapters:
            manifest.adapters.append(
                {
                    "qualified_name": qualified,
                    "source_skill": SOURCE_SKILL_NAME,
                    "source_commit": commit,
                    "license": LICENSE,
                }
            )
            existing_adapters.add(qualified)

    # Pin copied_at to the SOURCE COMMIT's author timestamp, not host wall-clock,
    # so generator output is byte-deterministic for a fixed source commit.
    # Wave I-1 fix for the .venous_manifest.json drift surfaced by
    # evidence/_harness/generator_idempotence.py.
    commit_iso = _source_commit_iso_time()
    if commit_iso == "unknown":
        # Fallback: use HEAD truncated SHA as a pseudo-timestamp seed
        # so the field is still deterministic even outside a git checkout.
        manifest.copied_at = f"commit:{_source_commit()[:12]}"
    else:
        manifest.copied_at = commit_iso
    manifest.copied = copied
    _write_manifest(manifest)
    return manifest
