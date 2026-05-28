"""Phase-1 ``discover()`` primitives shared by every compose tool.

Single responsibility: read the emitted FastAPI project tree and return a
typed, frozen description of what's there — never mutate, never write, never
infer beyond what the source files prove.

Public surface (frozen by WP-WAVE0-F1):

* ``ProbeError`` — raised for invalid / unreadable projects (never silent None).
* ``ProjectProbe`` — frozen dataclass with the canonical app/route/crud/schema
  directories.
* ``probe_project(project_dir)`` — build a ``ProjectProbe`` for a project.
* ``INFRA_SKIP`` — frozenset of model stems that are infra-only (skip on discovery).
* ``DiscoveredModel`` — frozen dataclass per model found.
* ``discover_models(probe, ...)`` — return discovered models in a deterministic order.
* ``FileInventory`` + ``inventory_existing(probe, paths)`` — partition paths into
  created / modified / skipped for ``ToolResult`` bookkeeping.

Hard invariants:

* Discovery NEVER touches anything outside ``probe.project_dir``.
* Per-probe in-memory read cache so a tool that calls ``discover_models`` twice
  doesn't re-read every model file.
* Zero ``print`` / logging side-effects.
* ``ProbeError`` on invalid project (missing ``app/`` etc.), NOT silent ``None``.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path


class ProbeError(Exception):
    """Raised when a project cannot be probed (missing layout, unreadable files)."""


# ---------------------------------------------------------------------------
# ProjectProbe
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProjectProbe:
    """Frozen description of a FastAPI project's discoverable layout.

    Attributes:
        project_dir: Absolute path to the project root.
        app_dir: ``<project_dir>/app``.
        has_fastapi: ``True`` if ``app/main.py`` references ``FastAPI(``.
        has_sqlalchemy_async: ``True`` if ``app/core/session.py`` or any model file
            references ``AsyncSession``.
        has_alembic: ``True`` if ``alembic/versions`` exists and is a directory.
        versions_dir: Path to ``alembic/versions`` or ``None`` when absent.
        routes_dir: ``<app_dir>/api/routes``.
        crud_dir: ``<app_dir>/crud``.
        schemas_dir: ``<app_dir>/schemas``.
        models_dir: ``<app_dir>/models``.
    """

    project_dir: Path
    app_dir: Path
    has_fastapi: bool
    has_sqlalchemy_async: bool
    has_alembic: bool
    versions_dir: Path | None
    routes_dir: Path
    crud_dir: Path
    schemas_dir: Path
    models_dir: Path
    # Internal: per-probe read cache (file path -> source). Excluded from repr/eq
    # so the public dataclass remains a pure value object.
    _read_cache: dict[Path, str] = field(
        default_factory=dict, compare=False, repr=False, hash=False
    )

    def read(self, path: Path) -> str:
        """Cached ``path.read_text()`` bound to this probe.

        Args:
            path: Absolute path inside ``self.project_dir``.

        Returns:
            File contents as text.

        Raises:
            ProbeError: When ``path`` falls outside ``project_dir`` (defence in depth).
        """
        try:
            path.resolve().relative_to(self.project_dir.resolve())
        except ValueError as exc:
            raise ProbeError(f"refusing to read outside project_dir: {path}") from exc
        cached = self._read_cache.get(path)
        if cached is not None:
            return cached
        text = path.read_text()
        self._read_cache[path] = text
        return text


def probe_project(project_dir: Path) -> ProjectProbe:
    """Build a :class:`ProjectProbe` for *project_dir*.

    Args:
        project_dir: Absolute path to the project root (contains ``app/``).

    Returns:
        A frozen :class:`ProjectProbe`.

    Raises:
        ProbeError: When ``project_dir`` is missing, not a directory, or has no ``app/``.
    """
    project = Path(project_dir)
    if not project.exists():
        raise ProbeError(f"project_dir does not exist: {project_dir}")
    if not project.is_dir():
        raise ProbeError(f"project_dir is not a directory: {project_dir}")
    app_dir = project / "app"
    if not app_dir.is_dir():
        raise ProbeError(f"app/ directory missing under project_dir: {project_dir}")

    main_py = app_dir / "main.py"
    has_fastapi = main_py.exists() and "FastAPI(" in main_py.read_text(errors="replace")

    session_py = app_dir / "core" / "session.py"
    has_sqlalchemy_async = session_py.exists() and "AsyncSession" in session_py.read_text(
        errors="replace"
    )

    versions_dir = project / "alembic" / "versions"
    has_alembic = versions_dir.is_dir()

    return ProjectProbe(
        project_dir=project,
        app_dir=app_dir,
        has_fastapi=has_fastapi,
        has_sqlalchemy_async=has_sqlalchemy_async,
        has_alembic=has_alembic,
        versions_dir=versions_dir if has_alembic else None,
        routes_dir=app_dir / "api" / "routes",
        crud_dir=app_dir / "crud",
        schemas_dir=app_dir / "schemas",
        models_dir=app_dir / "models",
    )


# ---------------------------------------------------------------------------
# Model discovery
# ---------------------------------------------------------------------------


INFRA_SKIP: frozenset[str] = frozenset({"base", "user", "mixins", "__init__", "tenant"})


@dataclass(frozen=True)
class DiscoveredModel:
    """A model file discovered under ``app/models/``.

    Attributes:
        stem: The actual file stem on disk (e.g. ``"vaccinelot"``).
        class_name: The actual SQLAlchemy class name from AST (e.g. ``"VaccineLot"``).
        file_path: Absolute path to the model file.
        has_route: A matching ``app/api/routes/<stem>.py`` exists.
        has_crud: A matching ``app/crud/<stem>.py`` exists.
        has_schema: A matching ``app/schemas/<stem>.py`` exists.
        has_attr_is_deleted: The model class declares an ``is_deleted`` attribute.
        has_attr_created_at: The model class declares a ``created_at`` attribute.
    """

    stem: str
    class_name: str
    file_path: Path
    has_route: bool
    has_crud: bool
    has_schema: bool
    has_attr_is_deleted: bool
    has_attr_created_at: bool


def _class_has_attr(cls: ast.ClassDef, name: str) -> bool:
    """Return ``True`` if the class body assigns / annotates an attribute ``name``."""
    for node in cls.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == name:
                return True
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return True
    return False


def discover_models(
    probe: ProjectProbe,
    *,
    skip: frozenset[str] = INFRA_SKIP,
    require_route: bool = True,
    require_base_subclass: bool = True,
) -> list[DiscoveredModel]:
    """Discover SQLAlchemy models declared under ``app/models/``.

    Mirrors the canonical filter used by the legacy per-tool discovery loops:

    * Skip any stem in *skip*.
    * Require a matching route file under ``app/api/routes/`` when *require_route*.
    * Only collect classes that inherit from ``Base`` (or ``something.Base``) when
      *require_base_subclass*.
    * Keep only the class whose ``class_name.lower() == stem`` to avoid multi-class
      files producing N spurious entries (preserves the legacy "vaccinelot.py ->
      class VaccineLot" multi-word fix).

    Args:
        probe: A :class:`ProjectProbe` for the target project.
        skip: Stems to skip outright (infra files, ``__init__``, etc.).
        require_route: When ``True``, drop models without a matching route file.
        require_base_subclass: When ``True``, drop classes that don't inherit from ``Base``.

    Returns:
        Deterministically-sorted list of :class:`DiscoveredModel`.
    """
    if not probe.models_dir.is_dir():
        return []

    available_routes: set[str] = set()
    if probe.routes_dir.is_dir():
        for r in probe.routes_dir.glob("*.py"):
            if r.stem != "__init__":
                available_routes.add(r.stem)

    found: list[DiscoveredModel] = []
    for f in sorted(probe.models_dir.glob("*.py")):
        stem = f.stem
        if stem in skip:
            continue
        if require_route and stem not in available_routes:
            continue
        try:
            tree = ast.parse(probe.read(f))
        except SyntaxError:
            continue

        classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        if require_base_subclass:
            classes = [
                c
                for c in classes
                if any(
                    (isinstance(b, ast.Name) and b.id == "Base")
                    or (isinstance(b, ast.Attribute) and b.attr == "Base")
                    for b in c.bases
                )
            ]
        # Keep only the canonical class for this file (class_name.lower() == stem).
        # This preserves the multi-word model fix (vaccinelot.py -> VaccineLot).
        classes = [c for c in classes if c.name.lower() == stem]
        for cls in classes:
            found.append(
                DiscoveredModel(
                    stem=stem,
                    class_name=cls.name,
                    file_path=f,
                    has_route=stem in available_routes,
                    has_crud=(probe.crud_dir / f"{stem}.py").exists(),
                    has_schema=(probe.schemas_dir / f"{stem}.py").exists(),
                    has_attr_is_deleted=_class_has_attr(cls, "is_deleted"),
                    has_attr_created_at=_class_has_attr(cls, "created_at"),
                )
            )
    return found


# ---------------------------------------------------------------------------
# File inventory
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FileInventory:
    """Partition of a path iterable into created / modified / skipped buckets.

    Attributes:
        created: Paths that did not exist at probe time.
        modified: Paths that exist and are inside the project.
        skipped: ``(path, reason)`` pairs for entries dropped (outside project,
            non-file, etc.).
    """

    created: list[Path]
    modified: list[Path]
    skipped: list[tuple[Path, str]]


def inventory_existing(probe: ProjectProbe, paths: Iterable[Path]) -> FileInventory:
    """Partition *paths* by existence + containment in ``probe.project_dir``.

    Args:
        probe: Project probe (used for project-root containment check).
        paths: Iterable of absolute paths to classify.

    Returns:
        A :class:`FileInventory`.
    """
    created: list[Path] = []
    modified: list[Path] = []
    skipped: list[tuple[Path, str]] = []
    root = probe.project_dir.resolve()
    for p in paths:
        try:
            p.resolve().relative_to(root)
        except ValueError:
            skipped.append((p, "outside project_dir"))
            continue
        if p.exists():
            if p.is_file():
                modified.append(p)
            else:
                skipped.append((p, "not a regular file"))
        else:
            created.append(p)
    return FileInventory(created=created, modified=modified, skipped=skipped)
