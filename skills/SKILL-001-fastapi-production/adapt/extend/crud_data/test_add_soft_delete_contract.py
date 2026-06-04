"""Generic tool-contract mutation coverage for add_soft_delete.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_soft_delete.py in the mutation
runner: ``--tests test_add_soft_delete.py test_add_soft_delete_contract.py``.

The ``test_sd_*`` functions below target this tool's bespoke logic — the
column-injection placement, sqlalchemy/datetime import management, and the
Alembic migration down-revision chaining — which the generic preamble checks
do not exercise.
"""

import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.crud_data.add_soft_delete import (
    _ensure_sa_imports,
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
# _patch_model — column injection placement & idempotency
# ---------------------------------------------------------------------------


def _model_src(*, datetime_line: str = "from datetime import datetime") -> str:
    """Return a minimal SQLAlchemy model source for placement assertions."""
    head = "from app.models.base import Base\n"
    if datetime_line:
        head = datetime_line + "\n" + head
    return (
        head
        + "from sqlalchemy import String\n"
        + "from sqlalchemy.orm import Mapped, mapped_column\n\n\n"
        + "class Foo(Base):\n"
        + '    __tablename__ = "foo"\n'
        + "    name: Mapped[str] = mapped_column(String)\n"
    )


def test_sd_patch_model_is_idempotent_when_already_present():
    """L204 BoolLiteral False->True: re-patching a model that already carries
    is_deleted must return False (no second injection)."""
    d = Path(tempfile.mkdtemp())
    mf = d / "m.py"
    mf.write_text(_model_src())

    first = _patch_model(mf, "Foo")
    assert first is True
    assert mf.read_text().count("is_deleted") == 1

    second = _patch_model(mf, "Foo")
    assert second is False, "second patch must be a no-op once is_deleted is present"
    assert mf.read_text().count("is_deleted") == 1, "columns must not be injected twice"
    assert mf.read_text().count("deleted_at") == 1


def test_sd_patch_model_inserts_columns_after_last_class_line():
    """L226/L227/L230/L231: columns land inside the class body, immediately
    after the last existing indented member (here the ``name`` column), not at
    file end and not before the class declaration."""
    d = Path(tempfile.mkdtemp())
    mf = d / "m.py"
    mf.write_text(_model_src())
    _patch_model(mf, "Foo")

    text = mf.read_text()
    lines = text.splitlines()
    name_idx = next(i for i, ln in enumerate(lines) if "name: Mapped[str]" in ln)
    isdel_idx = next(i for i, ln in enumerate(lines) if "is_deleted:" in ln)
    class_idx = next(i for i, ln in enumerate(lines) if ln.startswith("class Foo"))

    # Injected after the class declaration and after the last member.
    assert isdel_idx > class_idx
    assert isdel_idx > name_idx
    # And the injected columns are indented members of the class.
    assert lines[isdel_idx].startswith("    is_deleted:")


def test_sd_patch_model_in_class_flag_starts_false():
    """L223 BoolLiteral False->True: a pre-class indented line (e.g. a
    continuation inside a top-level call) must NOT be treated as the class body.
    If in_class started True, the columns would be inserted before the class."""
    d = Path(tempfile.mkdtemp())
    mf = d / "m.py"
    # An indented, non-blank line appears BEFORE the class definition.
    mf.write_text(
        "from app.models.base import Base\n"
        "PRELUDE = (\n"
        '    "indented-before-class"\n'
        ")\n\n\n"
        "class Foo(Base):\n"
        '    __tablename__ = "foo"\n'
    )
    _patch_model(mf, "Foo")

    lines = mf.read_text().splitlines()
    class_idx = next(i for i, ln in enumerate(lines) if ln.startswith("class Foo"))
    isdel_idx = next(i for i, ln in enumerate(lines) if "is_deleted:" in ln)
    assert isdel_idx > class_idx, "columns must be inside the class, not before it"


def test_sd_patch_model_fallback_appends_for_bodyless_class():
    """L230 Compare Eq->NotEq: a class with no indented body (last_class_line
    stays -1) falls back to appending the columns at end of file."""
    d = Path(tempfile.mkdtemp())
    mf = d / "m.py"
    mf.write_text("from app.models.base import Base\nclass Foo(Base): pass\n")
    _patch_model(mf, "Foo")

    text = mf.read_text()
    assert "is_deleted:" in text
    assert "deleted_at:" in text
    # Fallback path appends at the very end.
    assert text.rstrip().endswith("default=None)")


# ---------------------------------------------------------------------------
# datetime import handling (L207 / L209)
# ---------------------------------------------------------------------------


def test_sd_adds_datetime_import_when_absent():
    """L207 Compare NotIn->In: a model with NO datetime import at all must get
    ``from datetime import datetime, timezone`` injected (deleted_at uses
    datetime)."""
    d = Path(tempfile.mkdtemp())
    mf = d / "m.py"
    mf.write_text(_model_src(datetime_line=""))
    _patch_model(mf, "Foo")

    text = mf.read_text()
    assert "from datetime import datetime, timezone" in text


def test_sd_does_not_duplicate_datetime_when_module_imported():
    """L207 BoolOp And->Or: when ``import datetime`` is already present the
    second guard short-circuits the And to False, so NO extra
    ``from datetime import datetime`` line is added."""
    d = Path(tempfile.mkdtemp())
    mf = d / "m.py"
    mf.write_text(_model_src(datetime_line="import datetime"))
    _patch_model(mf, "Foo")

    text = mf.read_text()
    assert "from datetime import datetime" not in text, (
        "must not add a from-import when `import datetime` already covers it"
    )
    assert text.count("import datetime") == 1


def test_sd_upgrades_datetime_import_to_include_timezone():
    """L209 Compare NotIn->In: a model importing datetime WITHOUT timezone and
    without any other 'timezone' token must have its import upgraded to include
    timezone."""
    d = Path(tempfile.mkdtemp())
    mf = d / "m.py"
    # Plain datetime import, no DateTime(timezone=True) anywhere -> 'timezone' absent.
    mf.write_text(
        "from datetime import datetime\n"
        "from app.models.base import Base\n"
        "from sqlalchemy import String\n"
        "from sqlalchemy.orm import Mapped, mapped_column\n\n\n"
        "class Foo(Base):\n"
        '    __tablename__ = "foo"\n'
        "    name: Mapped[str] = mapped_column(String)\n"
    )
    _patch_model(mf, "Foo")

    text = mf.read_text()
    assert "from datetime import datetime, timezone" in text, (
        "existing datetime import must be upgraded to include timezone"
    )


# ---------------------------------------------------------------------------
# _ensure_sa_imports (L250 / L253 / L258)
# ---------------------------------------------------------------------------


def test_sd_ensure_sa_imports_noop_when_all_present():
    """L250 UnaryNot: when no names are missing the source is returned
    unchanged (no spurious empty import line)."""
    src = "from sqlalchemy import Boolean, DateTime\nclass F: pass\n"
    out = _ensure_sa_imports(src, {"Boolean", "DateTime"})
    assert out == src, "no-op expected when all names already imported"
    assert "from sqlalchemy import \n" not in out


def test_sd_ensure_sa_imports_uses_orm_anchor_fallback():
    """L253 BoolOp Or->And: with no ``from sqlalchemy import`` line the tool
    falls back to anchoring before ``from sqlalchemy.orm`` rather than
    prepending at file top."""
    src = "from sqlalchemy.orm import Mapped\nclass F: pass\n"
    out = _ensure_sa_imports(src, {"Boolean"})
    lines = out.splitlines()
    new_idx = next(i for i, ln in enumerate(lines) if ln == "from sqlalchemy import Boolean")
    orm_idx = next(i for i, ln in enumerate(lines) if ln.startswith("from sqlalchemy.orm"))
    assert new_idx == orm_idx - 1, "new import must sit directly before the orm anchor"


def test_sd_ensure_sa_imports_inserts_before_anchor():
    """L258 BinOp Add->Sub: the new import is spliced in immediately before the
    matched ``from sqlalchemy import`` anchor, preserving the anchor line."""
    src = "from sqlalchemy import DateTime, String\nclass F: pass\n"
    out = _ensure_sa_imports(src, {"Boolean"})
    lines = out.splitlines()
    assert lines[0] == "from sqlalchemy import Boolean"
    assert lines[1] == "from sqlalchemy import DateTime, String"


# ---------------------------------------------------------------------------
# _insert_after_future (L266 / L267)
# ---------------------------------------------------------------------------


def test_sd_insert_after_future_places_line_below_future():
    """L266/L267 BinOp Add->Sub: the inserted line lands immediately after the
    __future__ import (with a separating blank line), not before it."""
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
# migration down-revision chaining (L276)
# ---------------------------------------------------------------------------


def test_sd_migration_chains_to_real_head():
    """L276 BoolOp Or->And: the emitted migration's down_revision must chain to
    the discovered Alembic head (0002_baseline_schema in the fixture), proving
    find_migration_head() is used rather than the '0001_initial' fallback."""
    p = create_fixture_project(name="sd_contract_head")
    r = add_soft_delete(ToolInput(project_dir=str(p)))
    assert r.status == "success", r.error

    migs = list((p / "alembic" / "versions").glob("*soft_delete*"))
    assert migs, "no soft_delete migration emitted"
    text = migs[0].read_text()
    assert 'down_revision = "0002_baseline_schema"' in text, (
        "migration must chain to the real head, not the '0001_initial' fallback"
    )
