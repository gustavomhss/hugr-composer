"""Generic tool-contract mutation coverage for add_soft_delete.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_soft_delete.py in the mutation
runner: ``--tests test_add_soft_delete.py test_add_soft_delete_contract.py``.

The ``test_sd_*`` functions below target this tool's bespoke logic — the
SPEC-v2 SoftDeleteMixin inheritance rewrite, the ``__future__`` import
anchoring, and the Alembic migration down-revision chaining — which the generic
preamble checks do not exercise.
"""

import ast
import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.crud_data.add_soft_delete import (
    _insert_after_future,
    _patch_model,
    add_soft_delete,
)
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.crud_data.add_soft_delete import add_soft_delete

    for check in SCAFFOLDABLE_CHECKS:
        check(add_soft_delete, "add_soft_delete")


# ---------------------------------------------------------------------------
# _patch_model — SPEC-v2 SoftDeleteMixin inheritance rewrite & idempotency
#
# Re-anchored from the OLD design, where _patch_model injected an is_deleted/
# deleted_at column literal (plus datetime/Boolean import management) directly
# into every model file. SPEC-v2 (#19) moves the columns onto the emitted
# app/models/mixins.py::SoftDeleteMixin and makes _patch_model only (a) add the
# mixin import and (b) rewrite the class bases to inherit it. The mutation-kill
# targets are now the import-insertion and the base-rewrite, which these tests
# pin precisely; the removed per-model column-injection / datetime-import /
# _ensure_sa_imports helpers no longer exist and have no SPEC-v2 equivalent.
# ---------------------------------------------------------------------------


def _model_src(*, base_import: str = "from app.models.base import Base") -> str:
    """Return a minimal SQLAlchemy model source for mixin-rewrite assertions."""
    head = base_import + "\n" if base_import else ""
    return (
        head
        + "from sqlalchemy import String\n"
        + "from sqlalchemy.orm import Mapped, mapped_column\n\n\n"
        + "class Foo(Base):\n"
        + '    __tablename__ = "foo"\n'
        + "    name: Mapped[str] = mapped_column(String)\n"
    )


def test_sd_patch_model_is_idempotent_when_already_present():
    """Re-patching a model that already inherits SoftDeleteMixin must return
    False and must NOT duplicate the import or the base."""
    d = Path(tempfile.mkdtemp())
    mf = d / "m.py"
    mf.write_text(_model_src())

    first = _patch_model(mf, "Foo")
    assert first is True
    assert mf.read_text().count("SoftDeleteMixin") == 2  # import line + base

    second = _patch_model(mf, "Foo")
    assert second is False, "second patch must be a no-op once the mixin is present"
    assert mf.read_text().count("from app.models.mixins import SoftDeleteMixin") == 1, (
        "mixin import must not be added twice"
    )
    assert mf.read_text().count("class Foo(SoftDeleteMixin") == 1, (
        "the class base must not be rewritten twice"
    )


def test_sd_patch_model_rewrites_class_bases_to_inherit_mixin():
    """The target class's bases gain ``SoftDeleteMixin`` (prepended) so the
    global do_orm_execute filter can key off it — and the original ``Base`` is
    preserved, not replaced."""
    d = Path(tempfile.mkdtemp())
    mf = d / "m.py"
    mf.write_text(_model_src())
    _patch_model(mf, "Foo")

    tree = ast.parse(mf.read_text())
    foo = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "Foo")
    base_names = [b.id for b in foo.bases if isinstance(b, ast.Name)]
    assert "SoftDeleteMixin" in base_names, "Foo must inherit SoftDeleteMixin"
    assert "Base" in base_names, "the original Base must be preserved as a base"
    # Mixin is prepended (MRO order: mixin first so its columns/criteria win).
    assert base_names.index("SoftDeleteMixin") < base_names.index("Base")


def test_sd_patch_model_inserts_mixin_import_after_base_import():
    """The ``from app.models.mixins import SoftDeleteMixin`` line is anchored
    immediately after the ``from app.models.base import Base`` line, not at file
    top and not after the class."""
    d = Path(tempfile.mkdtemp())
    mf = d / "m.py"
    mf.write_text(_model_src())
    _patch_model(mf, "Foo")

    lines = mf.read_text().splitlines()
    base_idx = next(i for i, ln in enumerate(lines) if ln == "from app.models.base import Base")
    mixin_idx = next(
        i for i, ln in enumerate(lines) if ln == "from app.models.mixins import SoftDeleteMixin"
    )
    class_idx = next(i for i, ln in enumerate(lines) if ln.startswith("class Foo"))
    assert mixin_idx == base_idx + 1, "mixin import must sit directly after the base import"
    assert mixin_idx < class_idx, "mixin import must precede the class definition"


def test_sd_patch_model_falls_back_to_future_anchor_without_base_import():
    """With no ``from app.models.base import Base`` line, the mixin import is
    anchored after the ``__future__`` import instead (via _insert_after_future)."""
    d = Path(tempfile.mkdtemp())
    mf = d / "m.py"
    mf.write_text(
        "from __future__ import annotations\n"
        "from sqlalchemy import String\n"
        "from sqlalchemy.orm import Mapped, mapped_column\n\n\n"
        "class Foo(Base):\n"
        '    __tablename__ = "foo"\n'
        "    name: Mapped[str] = mapped_column(String)\n"
    )
    _patch_model(mf, "Foo")

    lines = mf.read_text().splitlines()
    fut_idx = next(i for i, ln in enumerate(lines) if ln.startswith("from __future__"))
    mixin_idx = next(
        i for i, ln in enumerate(lines) if ln == "from app.models.mixins import SoftDeleteMixin"
    )
    class_idx = next(i for i, ln in enumerate(lines) if ln.startswith("class Foo"))
    assert mixin_idx > fut_idx, "mixin import must land after the __future__ import"
    assert mixin_idx < class_idx, "mixin import must still precede the class"
    # And the class is still rewritten to inherit the mixin.
    assert "class Foo(SoftDeleteMixin, Base)" in mf.read_text()


def test_sd_patch_model_noop_when_no_matching_class():
    """When the named class is absent, _patch_model rewrites nothing and the
    file's class definitions are unchanged (returns False)."""
    d = Path(tempfile.mkdtemp())
    mf = d / "m.py"
    mf.write_text(_model_src())  # defines Foo, not Bar
    result = _patch_model(mf, "Bar")
    assert result is False, "no matching class -> no-op"
    assert "SoftDeleteMixin" not in mf.read_text(), (
        "must not rewrite/import when the target class is not found"
    )


# ---------------------------------------------------------------------------
# _insert_after_future
# ---------------------------------------------------------------------------


def test_sd_insert_after_future_places_line_below_future():
    """The inserted line lands immediately after the __future__ import
    (with a separating blank line), not before it."""
    src = "from __future__ import annotations\nimport os\n"
    out = _insert_after_future(src, "INSERTED\n")
    lines = out.splitlines()
    fut_idx = next(i for i, ln in enumerate(lines) if ln.startswith("from __future__"))
    ins_idx = next(i for i, ln in enumerate(lines) if ln == "INSERTED")
    assert ins_idx > fut_idx, "must insert AFTER the __future__ import"


def test_sd_insert_after_future_prepends_when_no_future():
    """No __future__ import -> the line is prepended to the source."""
    src = "import os\nx = 1\n"
    out = _insert_after_future(src, "INSERTED\n")
    assert out.splitlines()[0] == "INSERTED"


# ---------------------------------------------------------------------------
# migration down-revision chaining
# ---------------------------------------------------------------------------


def test_sd_migration_chains_to_real_head():
    """The emitted migration's down_revision must chain to the discovered Alembic
    head (0002_baseline_schema in the fixture), proving find_migration_head() is
    used rather than the '0001_initial' fallback."""
    p = create_fixture_project(name="sd_contract_head")
    r = add_soft_delete(ToolInput(project_dir=str(p)))
    assert r.status == "success", r.error

    migs = list((p / "alembic" / "versions").glob("*soft_delete*"))
    assert migs, "no soft_delete migration emitted"
    text = migs[0].read_text()
    assert 'down_revision = "0002_baseline_schema"' in text, (
        "migration must chain to the real head, not the '0001_initial' fallback"
    )
