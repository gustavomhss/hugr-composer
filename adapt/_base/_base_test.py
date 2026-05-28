"""Unit tests for the shared phase primitives in :mod:`adapt._base`.

These tests are intentionally hermetic: each one builds the smallest possible
on-disk project shape under ``tmp_path`` rather than calling the heavy
``create_fixture_project`` fixture.  That keeps the hexagon's tests fast and
independent of the FastAPI scaffold generator.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from adapt._base import (
    INFRA_SKIP,
    DiscoveredModel,
    FileInventory,
    PatchError,
    ProbeError,
    ProjectProbe,
    TemplateError,
    atomic_write,
    discover_models,
    inventory_existing,
    load_template,
    patch_add_import,
    patch_append_class_body_after_field,
    patch_append_module_block,
    patch_append_router_endpoint,
    probe_project,
    render,
    render_to,
)

# ---------------------------------------------------------------------------
# Tiny project builder — avoids the heavy generator fixture
# ---------------------------------------------------------------------------


def _make_project(
    tmp_path: Path,
    *,
    with_alembic: bool = True,
    extra_models: dict[str, str] | None = None,
) -> Path:
    project = tmp_path / "proj"
    (project / "app" / "core").mkdir(parents=True)
    (project / "app" / "api" / "routes").mkdir(parents=True)
    (project / "app" / "crud").mkdir()
    (project / "app" / "schemas").mkdir()
    (project / "app" / "models").mkdir()

    (project / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
    (project / "app" / "core" / "session.py").write_text(
        "from sqlalchemy.ext.asyncio import AsyncSession\n"
    )
    # Base
    (project / "app" / "models" / "base.py").write_text("class Base: pass\n")
    # Canonical Item model
    (project / "app" / "models" / "item.py").write_text(
        "from app.models.base import Base\n"
        "class Item(Base):\n"
        "    id: int\n"
        "    created_at: int\n"
        "    is_deleted: bool = False\n"
    )
    (project / "app" / "crud" / "item.py").write_text("# crud item\n")
    (project / "app" / "schemas" / "item.py").write_text(
        "from pydantic import BaseModel\n"
        "class ItemsPublic(BaseModel):\n"
        "    data: list = []\n"
        "    count: int = 0\n"
    )
    (project / "app" / "api" / "routes" / "item.py").write_text("# route item\n")

    if extra_models:
        for cls_name, body in extra_models.items():
            stem = cls_name.lower()
            (project / "app" / "models" / f"{stem}.py").write_text(body)
            (project / "app" / "api" / "routes" / f"{stem}.py").write_text("# route\n")

    if with_alembic:
        (project / "alembic" / "versions").mkdir(parents=True)
    return project


# ---------------------------------------------------------------------------
# probe_project
# ---------------------------------------------------------------------------


def test_probe_project_minimal(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    probe = probe_project(project)
    assert isinstance(probe, ProjectProbe)
    assert probe.project_dir == project
    assert probe.app_dir == project / "app"
    assert probe.has_fastapi is True
    assert probe.has_sqlalchemy_async is True
    assert probe.has_alembic is True
    assert probe.versions_dir == project / "alembic" / "versions"
    assert probe.routes_dir == project / "app" / "api" / "routes"


def test_probe_project_missing_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(ProbeError):
        probe_project(tmp_path / "does-not-exist")


def test_probe_project_missing_app_raises(tmp_path: Path) -> None:
    (tmp_path / "no_app").mkdir()
    with pytest.raises(ProbeError):
        probe_project(tmp_path / "no_app")


def test_probe_project_no_alembic(tmp_path: Path) -> None:
    project = _make_project(tmp_path, with_alembic=False)
    probe = probe_project(project)
    assert probe.has_alembic is False
    assert probe.versions_dir is None


def test_probe_read_cache(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    probe = probe_project(project)
    item = project / "app" / "models" / "item.py"
    first = probe.read(item)
    # Mutate the file on disk; cached read should NOT see the change.
    item.write_text("# mutated\n")
    second = probe.read(item)
    assert first == second


def test_probe_read_refuses_outside_project(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    probe = probe_project(project)
    outside = tmp_path / "outside.txt"
    outside.write_text("x")
    with pytest.raises(ProbeError):
        probe.read(outside)


# ---------------------------------------------------------------------------
# discover_models
# ---------------------------------------------------------------------------


def test_discover_models_finds_item(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    probe = probe_project(project)
    models = discover_models(probe)
    assert len(models) == 1
    m = models[0]
    assert isinstance(m, DiscoveredModel)
    assert m.stem == "item"
    assert m.class_name == "Item"
    assert m.has_route is True
    assert m.has_crud is True
    assert m.has_schema is True
    assert m.has_attr_is_deleted is True
    assert m.has_attr_created_at is True


def test_discover_models_skips_infra(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    # Add infra files that should be skipped.
    (project / "app" / "models" / "tenant.py").write_text(
        "from app.models.base import Base\nclass Tenant(Base):\n    id: int\n"
    )
    (project / "app" / "api" / "routes" / "tenant.py").write_text("# route\n")
    probe = probe_project(project)
    models = discover_models(probe)
    stems = {m.stem for m in models}
    assert "tenant" not in stems
    assert "item" in stems


def test_discover_models_multiword(tmp_path: Path) -> None:
    """Regression: vaccinelot.py with class VaccineLot must be picked up."""
    project = _make_project(
        tmp_path,
        extra_models={
            "VaccineLot": (
                "from app.models.base import Base\nclass VaccineLot(Base):\n    id: int\n"
            )
        },
    )
    probe = probe_project(project)
    models = discover_models(probe)
    classes = {m.class_name for m in models}
    assert "VaccineLot" in classes


def test_discover_models_skips_when_no_route(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    (project / "app" / "models" / "ghost.py").write_text(
        "from app.models.base import Base\nclass Ghost(Base):\n    id: int\n"
    )
    # No matching route → must be skipped with require_route=True.
    probe = probe_project(project)
    models = discover_models(probe, require_route=True)
    assert all(m.stem != "ghost" for m in models)


def test_infra_skip_is_frozen() -> None:
    assert isinstance(INFRA_SKIP, frozenset)
    assert {"base", "user", "__init__", "tenant", "mixins"} <= INFRA_SKIP


# ---------------------------------------------------------------------------
# inventory_existing
# ---------------------------------------------------------------------------


def test_inventory_existing_partitions(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    probe = probe_project(project)
    existing = project / "app" / "models" / "item.py"
    new = project / "app" / "core" / "new_module.py"
    outside = tmp_path / "outside.txt"
    inv = inventory_existing(probe, [existing, new, outside])
    assert isinstance(inv, FileInventory)
    assert existing in inv.modified
    assert new in inv.created
    assert any(p == outside for p, _ in inv.skipped)


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------


def _make_template(tmp_path: Path, name: str, body: str) -> Path:
    caller = tmp_path / "tool"
    (caller / "templates").mkdir(parents=True, exist_ok=True)
    (caller / "templates" / name).write_text(body)
    return caller


def test_render_basic(tmp_path: Path) -> None:
    caller = _make_template(tmp_path, "hello.py.tmpl", "x = '$who'\n")
    out = render(caller, "hello.py.tmpl", {"who": "world"})
    assert out == "x = 'world'\n"


def test_render_strict_missing_key(tmp_path: Path) -> None:
    caller = _make_template(tmp_path, "hello.py.tmpl", "x = '$who'\n")
    with pytest.raises(TemplateError):
        render(caller, "hello.py.tmpl", {})


def test_load_template_missing(tmp_path: Path) -> None:
    caller = tmp_path / "tool"
    (caller / "templates").mkdir(parents=True)
    with pytest.raises(TemplateError):
        load_template(caller, "nope.py.tmpl")


def test_render_to_writes_and_creates_parents(tmp_path: Path) -> None:
    caller = _make_template(tmp_path, "hello.py.tmpl", "x = '$who'\n")
    dest = tmp_path / "out" / "deeper" / "hello.py"
    result = render_to(caller, "hello.py.tmpl", dest=dest, substitutions={"who": "w"})
    assert result == dest
    assert dest.read_text() == "x = 'w'\n"


def test_render_to_rejects_unparseable_python(tmp_path: Path) -> None:
    caller = _make_template(tmp_path, "bad.py.tmpl", "def $name(:\n")
    dest = tmp_path / "out" / "bad.py"
    with pytest.raises(TemplateError):
        render_to(caller, "bad.py.tmpl", dest=dest, substitutions={"name": "foo"})
    assert not dest.exists()


# ---------------------------------------------------------------------------
# atomic_write + patchers
# ---------------------------------------------------------------------------


def test_atomic_write_refuses_unparseable(tmp_path: Path) -> None:
    dest = tmp_path / "x.py"
    with pytest.raises(PatchError):
        atomic_write(dest, "def (:\n")
    assert not dest.exists()


def test_atomic_write_replaces_file(tmp_path: Path) -> None:
    dest = tmp_path / "x.py"
    dest.write_text("a = 1\n")
    atomic_write(dest, "a = 2\n")
    assert dest.read_text() == "a = 2\n"


def test_patch_add_import_appends(tmp_path: Path) -> None:
    f = tmp_path / "m.py"
    f.write_text("import os\n\nx = 1\n")
    changed = patch_add_import(f, module="fastapi", name="HTTPException")
    assert changed is True
    src = f.read_text()
    assert "from fastapi import HTTPException" in src
    ast.parse(src)


def test_patch_add_import_idempotent(tmp_path: Path) -> None:
    f = tmp_path / "m.py"
    f.write_text("from fastapi import HTTPException\nx = 1\n")
    assert patch_add_import(f, module="fastapi", name="HTTPException") is False


def test_patch_append_class_body_after_field(tmp_path: Path) -> None:
    f = tmp_path / "schema.py"
    f.write_text(
        "from pydantic import BaseModel\n"
        "class ItemsPublic(BaseModel):\n"
        "    data: list = []\n"
        "    count: int = 0\n"
    )
    changed = patch_append_class_body_after_field(
        f,
        class_name="ItemsPublic",
        after_field="count",
        new_fields=["next_cursor: str | None = None", "has_more: bool = False"],
    )
    assert changed is True
    tree = ast.parse(f.read_text())
    cls = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef))
    names = [
        n.target.id
        for n in cls.body
        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
    ]
    assert names == ["data", "count", "next_cursor", "has_more"]


def test_patch_append_class_body_idempotent(tmp_path: Path) -> None:
    f = tmp_path / "schema.py"
    f.write_text(
        "from pydantic import BaseModel\n"
        "class ItemsPublic(BaseModel):\n"
        "    data: list = []\n"
        "    count: int = 0\n"
        "    next_cursor: str | None = None\n"
        "    has_more: bool = False\n"
    )
    changed = patch_append_class_body_after_field(
        f,
        class_name="ItemsPublic",
        after_field="count",
        new_fields=["next_cursor: str | None = None", "has_more: bool = False"],
    )
    assert changed is False


def test_patch_append_class_body_missing_class_noops(tmp_path: Path) -> None:
    f = tmp_path / "schema.py"
    f.write_text("x = 1\n")
    assert (
        patch_append_class_body_after_field(
            f, class_name="Nope", after_field="count", new_fields=["a: int = 0"]
        )
        is False
    )


def test_patch_append_module_block_fingerprint(tmp_path: Path) -> None:
    f = tmp_path / "m.py"
    f.write_text("x = 1\n")
    changed = patch_append_module_block(
        f, block="def foo() -> int:\n    return 1\n", fingerprint="def foo"
    )
    assert changed is True
    # Idempotent
    assert (
        patch_append_module_block(
            f, block="def foo() -> int:\n    return 1\n", fingerprint="def foo"
        )
        is False
    )


def test_patch_append_router_endpoint_fingerprint(tmp_path: Path) -> None:
    f = tmp_path / "r.py"
    f.write_text("from fastapi import APIRouter\nrouter = APIRouter()\n")
    block = "@router.get('/x')\ndef list_items_cursor():\n    return {}\n"
    assert patch_append_router_endpoint(f, endpoint_block=block, fingerprint="list_items_cursor")
    assert (
        patch_append_router_endpoint(f, endpoint_block=block, fingerprint="list_items_cursor")
        is False
    )


def test_patch_refuses_to_corrupt_source(tmp_path: Path) -> None:
    f = tmp_path / "m.py"
    f.write_text("x = 1\n")
    with pytest.raises(PatchError):
        patch_append_module_block(f, block="def broken(:\n    return\n", fingerprint="broken")
    # File untouched.
    assert f.read_text() == "x = 1\n"
