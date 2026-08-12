---
spec_id: "TOOL-044"
tool_name: "add_refactor_model"
primitive: "data/DataMapper"
primitive_path: "core.venous.data.DataMapper"
generator: "generators/database/model.py"
version: "1.0.0"
status: "ratified"
invariants:
  - "INV-RM-01"
  - "INV-RM-02"
  - "INV-RM-03"
  - "INV-RM-04"
  - "INV-RM-05"
  - "INV-RM-06"
  - "INV-RM-07"
  - "INV-RM-08"
completeness_criteria:
  - "CC-01"
  - "CC-02"
  - "CC-03"
  - "CC-04"
  - "CC-05"
  - "CC-06"
  - "CC-07"
  - "CC-08"
  - "CC-09"
  - "CC-10"
  - "CC-11"
  - "CC-12"
  - "CC-13"
  - "CC-14"
  - "CC-15"
  - "CC-16"
  - "CC-17"
  - "CC-18"
  - "CC-19"
  - "CC-20"
  - "CC-21"
  - "CC-22"
  - "CC-23"
  - "CC-24"
  - "CC-25"
  - "CC-26"
  - "CC-27"
  - "CC-28"
  - "CC-29"
  - "CC-30"
  - "CC-31"
  - "CC-32"
  - "CC-33"
  - "CC-34"
quality_standards:
  - "QS-01"
  - "QS-02"
  - "QS-03"
  - "QS-04"
  - "QS-05"
  - "QS-06"
  - "QS-07"
  - "QS-08"
  - "QS-09"
  - "QS-10"
  - "QS-11"
  - "QS-12"
test_plan:
  - "T-01"
  - "T-02"
  - "T-03"
  - "T-04"
  - "T-05"
  - "T-06"
  - "T-07"
  - "T-08"
  - "T-09"
  - "T-10"
  - "T-11"
  - "T-12"
  - "T-13"
  - "T-14"
  - "T-15"
  - "T-16"
  - "T-17"
  - "T-18"
  - "T-19"
  - "T-20"
  - "T-21"
  - "T-22"
  - "T-23"
  - "T-24"
  - "T-25"
  - "T-26"
  - "T-27"
  - "T-28"
  - "T-29"
  - "T-30"
tags:
  - "auth"
  - "api"
  - "performance"
  - "testing"
  - "infrastructure"
---
# TOOL-044: fastapi_refactor_model

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-12

---

## 1. Overview

| Field | Value |
|-------|-------|
| Tool name | `fastapi_refactor_model` |
| Category | EVOLVE |
| Complexity | High |
| Dependencies | Existing FastAPI project, SQLAlchemy 2.0, Alembic, libcst, Pydantic v2 |
| Signature | `refactor_model(project_dir: str, operation: str, target: str, new_name: str, update_schemas: bool = True, update_routes: bool = True, generate_migration: bool = True) -> dict` |
| Parameters | `project_dir`: project root path<br>`operation`: `rename_model` \| `rename_field` \| `change_type` \| `split_model`<br>`target`: dotted path to target, e.g. `src.models.User.email`<br>`new_name`: new name or new type name for `change_type`<br>`update_schemas`: auto-update Pydantic schemas that reference the target (default `True`)<br>`update_routes`: auto-update route handlers that reference the target (default `True`)<br>`generate_migration`: generate Alembic migration for the schema change (default `True`) |

---

## 2. Purpose

`fastapi_refactor_model` eliminates the most dangerous class of breaking change in a FastAPI codebase: the "I renamed a field and broke 40 consumers" failure. When a developer renames a SQLAlchemy column or model class using editor find-and-replace, they typically update the model file but miss Pydantic schemas with hardcoded `alias=`, route handlers that reference the old attribute name in f-strings, test factories that construct model instances by keyword argument, OpenAPI snapshot files checked into CI, and Alembic migration history that still reflects the original column name. The result is a production incident: the column name in Postgres diverges from what the ORM expects, or the JSON field the frontend relies on disappears silently. This tool solves the problem atomically — it parses the full codebase with `libcst` (preserving comments and formatting), identifies every reference class (attribute access, type annotation, string literal, keyword argument, import alias, f-string segment), rewrites them all in memory, generates a multi-phase Alembic migration using `op.alter_column(new_column_name=...)` with add-then-backfill-then-drop safety, and emits a `git diff`-style patch that the maintainer reviews before applying. Nothing is written to disk without `--apply`.

The design choices are deliberate and non-negotiable: `libcst` over `ast` because `ast.unparse` destroys inline comments and reformats code (unacceptable for real codebases); `Field(alias=old_name)` injected into every Pydantic schema that exposes the renamed field because downstream JSON consumers must not break during the migration window; multi-phase migration (`ADD COLUMN new → backfill → dual-read period → DROP COLUMN old`) instead of single `ALTER TABLE RENAME COLUMN` because the latter locks the table and cannot be rolled back online; and patch-mode output instead of direct writes because an atomic rollback (`git apply --reverse`) is cleaner and safer than trying to un-do AST rewrites one file at a time. The dry-run mode lists every affected file and reference count before any change touches disk, giving the developer a full cost map before committing. The tool also handles `split_model` (one model becomes two, linked by FK) and `change_type` (e.g. `String(50) → String(255)`, `Integer → BigInteger`) with appropriate migration strategies per operation type.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time (dry-run) | < 2s for 100 files | Dev runs this interactively |
| Tool execution time (full run) | < 5s for 100 files | CI pipeline step, must not block |
| AST walk (libcst parse all files) | < 2s for 100 files | libcst is C-accelerated; parsing 100 × ~200 lines = 20k LOC in < 2s |
| Patch generation | < 500 ms | `unified_diff` over in-memory buffers |
| Files modified | ≤ 30 for `rename_field` on a 10-model project | Predictable blast radius |
| Files created | ≥ 7 | refactor engine, AST transformer, patch writer, CI gate, migration, tests, Makefile targets |
| Zero impact on unmodified files | 0 files changed if diff is empty | Verified by checksum comparison |
| Migration runtime (rename column) | < 10s with `op.alter_column` | DDL online in Postgres 12+; no table lock |
| Migration runtime (backfill) | < 60s on 10M rows | Batched UPDATE in chunks of 50k |
| Patch apply/reverse round-trip | 0 merge conflicts | Patch targets exact line ranges from libcst parse |

---

## 4. Code Examples (Before / After)

### 4.1 SQLAlchemy model: BEFORE (`rename_field` operation)

```python
# app/models/user.py
from datetime import datetime
from sqlalchemy import DateTime, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base
import uuid


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Primary contact address — used for login and notifications
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
```

### 4.2 SQLAlchemy model: AFTER (`rename_field`: `email` → `email_address`)

```python
# app/models/user.py
from datetime import datetime
from sqlalchemy import DateTime, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base
import uuid


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Primary contact address — used for login and notifications
    email_address: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    hashed_password: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
```

### 4.3 Pydantic schema: BEFORE

```python
# app/schemas/user.py
from pydantic import BaseModel, EmailStr
from datetime import datetime
import uuid


class UserBase(BaseModel):
    email: EmailStr


class UserCreate(UserBase):
    password: str


class UserUpdate(BaseModel):
    email: EmailStr | None = None


class UserPublic(UserBase):
    id: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}
```

### 4.4 Pydantic schema: AFTER (with backward-compat alias injected by tool)

```python
# app/schemas/user.py
from pydantic import BaseModel, EmailStr, Field
from datetime import datetime
import uuid


class UserBase(BaseModel):
    # Renamed from `email` — alias preserves JSON wire format during migration window
    email_address: EmailStr = Field(..., alias="email")

    model_config = {"populate_by_name": True}


class UserCreate(UserBase):
    password: str


class UserUpdate(BaseModel):
    email_address: EmailStr | None = Field(default=None, alias="email")

    model_config = {"populate_by_name": True}


class UserPublic(UserBase):
    id: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}
```

### 4.5 CRUD: BEFORE

```python
# app/crud/user.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user import User
from app.schemas.user import UserCreate
from app.core.security import hash_password


async def get_by_email(session: AsyncSession, email: str) -> User | None:
    stmt = select(User).where(User.email == email)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def create(session: AsyncSession, *, user_in: UserCreate) -> User:
    user = User(
        email=user_in.email,
        hashed_password=hash_password(user_in.password),
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user
```

### 4.6 CRUD: AFTER (all attribute access rewritten by libcst transformer)

```python
# app/crud/user.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user import User
from app.schemas.user import UserCreate
from app.core.security import hash_password


async def get_by_email(session: AsyncSession, email_address: str) -> User | None:
    stmt = select(User).where(User.email_address == email_address)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def create(session: AsyncSession, *, user_in: UserCreate) -> User:
    user = User(
        email_address=user_in.email_address,
        hashed_password=hash_password(user_in.password),
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user
```

### 4.7 Alembic multi-phase migration (generated by tool)

```python
# alembic/versions/0044_rename_user_email_to_email_address.py
"""rename users.email to email_address — multi-phase

Revision ID: 0044_phase1
Revises: 0043
Create Date: 2026-04-12

Phase 1 of 2: add new column, backfill, add indexes.
Phase 2 (manual, after dual-read period): drop old column.
"""
from alembic import op
import sqlalchemy as sa


revision = "0044_phase1"
down_revision = "0043"


def upgrade() -> None:
    # Phase 1a: add new column alongside old (nullable to avoid lock)
    op.add_column("users", sa.Column("email_address", sa.String(255), nullable=True))

    # Phase 1b: backfill in batches of 50k to avoid long-running UPDATE lock
    op.execute(
        """
        DO $$
        DECLARE
            batch_size INT := 50000;
            rows_updated INT;
        BEGIN
            LOOP
                UPDATE users
                SET email_address = email
                WHERE email_address IS NULL
                LIMIT batch_size;
                GET DIAGNOSTICS rows_updated = ROW_COUNT;
                EXIT WHEN rows_updated = 0;
            END LOOP;
        END $$;
        """
    )

    # Phase 1c: promote to NOT NULL, add unique constraint and index
    op.alter_column("users", "email_address", nullable=False)
    op.create_unique_constraint("uq_users_email_address", "users", ["email_address"])
    op.create_index("ix_users_email_address", "users", ["email_address"], unique=True)

    # NOTE: old `email` column retained here — dual-read period.
    # Run 0044_phase2 after confirming no consumers write to `email`.


def downgrade() -> None:
    op.drop_index("ix_users_email_address", table_name="users")
    op.drop_constraint("uq_users_email_address", "users", type_="unique")
    op.drop_column("users", "email_address")
```

### 4.8 libcst AST transformer (core refactor engine)

```python
# app/tools/refactor/ast_transformer.py
"""
libcst-based transformer for rename_field and rename_model operations.
Preserves all comments, whitespace, and formatting — ast.unparse does NOT.
"""
from __future__ import annotations

import libcst as cst
from libcst import matchers as m
from dataclasses import dataclass, field
from typing import Sequence


@dataclass
class RenameContext:
    old_name: str
    new_name: str
    model_class: str  # e.g. "User"
    operation: str  # rename_field | rename_model | change_type
    affected_files: list[str] = field(default_factory=list)
    reference_count: int = 0


class FieldRenameTransformer(cst.CSTTransformer):
    """
    Renames a model field across attribute accesses, keyword arguments,
    type annotations, and string literals within f-strings.
    """

    def __init__(self, ctx: RenameContext) -> None:
        self.ctx = ctx
        self._in_model_class: bool = False

    def visit_ClassDef(self, node: cst.ClassDef) -> bool:
        self._in_model_class = node.name.value == self.ctx.model_class
        return True

    def leave_ClassDef(
        self, original_node: cst.ClassDef, updated_node: cst.ClassDef
    ) -> cst.ClassDef:
        self._in_model_class = False
        return updated_node

    def leave_AnnAssign(
        self, original_node: cst.AnnAssign, updated_node: cst.AnnAssign
    ) -> cst.AnnAssign:
        if not self._in_model_class:
            return updated_node
        if m.matches(updated_node.target, m.Name(self.ctx.old_name)):
            self.ctx.reference_count += 1
            return updated_node.with_changes(
                target=cst.Name(self.ctx.new_name)
            )
        return updated_node

    def leave_Attribute(
        self, original_node: cst.Attribute, updated_node: cst.Attribute
    ) -> cst.Attribute:
        if m.matches(updated_node.attr, m.Name(self.ctx.old_name)):
            self.ctx.reference_count += 1
            return updated_node.with_changes(attr=cst.Name(self.ctx.new_name))
        return updated_node

    def leave_Arg(
        self, original_node: cst.Arg, updated_node: cst.Arg
    ) -> cst.Arg:
        if (
            updated_node.keyword is not None
            and updated_node.keyword.value == self.ctx.old_name
        ):
            self.ctx.reference_count += 1
            return updated_node.with_changes(
                keyword=cst.Name(self.ctx.new_name)
            )
        return updated_node
```

### 4.9 Patch generator (produces reviewable git-format patch)

```python
# app/tools/refactor/patch_generator.py
"""
Generates a unified diff patch from in-memory (old, new) file pairs.
The patch is valid for `git apply` and supports `--reverse` for rollback.
"""
from __future__ import annotations

import difflib
from pathlib import Path
from dataclasses import dataclass


@dataclass
class FileDiff:
    path: str
    original: str
    rewritten: str


def generate_patch(diffs: list[FileDiff], patch_path: Path) -> Path:
    """
    Write unified diff for all modified files to `patch_path`.
    Returns the path to the written patch file.
    """
    lines: list[str] = []
    for fd in diffs:
        if fd.original == fd.rewritten:
            continue  # skip unmodified files
        original_lines = fd.original.splitlines(keepends=True)
        rewritten_lines = fd.rewritten.splitlines(keepends=True)
        diff = difflib.unified_diff(
            original_lines,
            rewritten_lines,
            fromfile=f"a/{fd.path}",
            tofile=f"b/{fd.path}",
            lineterm="",
        )
        lines.extend(diff)

    patch_path.write_text("".join(lines), encoding="utf-8")
    return patch_path


def validate_patch(patch_path: Path, project_dir: Path) -> bool:
    """
    Validates that the patch applies cleanly via `git apply --check`.
    Raises RuntimeError if the patch cannot be applied without conflicts.
    """
    import subprocess
    result = subprocess.run(
        ["git", "apply", "--check", str(patch_path)],
        cwd=str(project_dir),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Patch validation failed:\n{result.stderr}\n"
            "This usually means the codebase changed between dry-run and apply. "
            "Re-run the tool to regenerate the patch."
        )
    return True
```

### 4.10 Test: rename_field end-to-end

```python
# tests/test_refactor_model.py
import pytest
from pathlib import Path
from textwrap import dedent
from app.tools.refactor.ast_transformer import FieldRenameTransformer, RenameContext
from app.tools.refactor.patch_generator import generate_patch, FileDiff
import libcst as cst
import tempfile


@pytest.fixture()
def sample_model_src() -> str:
    return dedent("""
        from sqlalchemy.orm import Mapped, mapped_column
        from sqlalchemy import String
        from app.models.base import Base

        class User(Base):
            __tablename__ = "users"
            # Primary contact address
            email: Mapped[str] = mapped_column(String(255), unique=True)
    """).strip()


def test_rename_field_rewrites_annassign(sample_model_src: str) -> None:
    ctx = RenameContext(
        old_name="email", new_name="email_address", model_class="User", operation="rename_field"
    )
    tree = cst.parse_module(sample_model_src)
    new_tree = tree.visit(FieldRenameTransformer(ctx))
    result = new_tree.code
    assert "email_address: Mapped[str]" in result
    assert "email: Mapped[str]" not in result
    # Comment must be preserved
    assert "# Primary contact address" in result
    assert ctx.reference_count == 1


def test_rename_field_skips_other_classes(sample_model_src: str) -> None:
    ctx = RenameContext(
        old_name="email", new_name="email_address", model_class="Product", operation="rename_field"
    )
    tree = cst.parse_module(sample_model_src)
    new_tree = tree.visit(FieldRenameTransformer(ctx))
    assert new_tree.code == sample_model_src  # unchanged
    assert ctx.reference_count == 0


def test_patch_generation_produces_valid_unified_diff(tmp_path: Path) -> None:
    original = "x = 1\ny = 2\n"
    rewritten = "x = 1\ny = 3\n"
    diffs = [FileDiff(path="app/config.py", original=original, rewritten=rewritten)]
    patch_path = tmp_path / "refactor.patch"
    result = generate_patch(diffs, patch_path)
    content = result.read_text()
    assert "--- a/app/config.py" in content
    assert "+++ b/app/config.py" in content
    assert "-y = 2" in content
    assert "+y = 3" in content


def test_rename_arg_keyword(sample_model_src: str) -> None:
    src = dedent("""
        from app.crud.user import create
        obj = create(email="test@x.com", owner_id=uid)
    """).strip()
    ctx = RenameContext(
        old_name="email", new_name="email_address", model_class="User", operation="rename_field"
    )
    tree = cst.parse_module(src)
    new_tree = tree.visit(FieldRenameTransformer(ctx))
    assert 'email_address="test@x.com"' in new_tree.code
    assert ctx.reference_count == 1
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-01 | **Refactors are ALWAYS atomic — all files change or none** | `patch_generator.py` writes a single `.patch` file; `git apply` applies all hunks or fails entirely; no partial state possible |
| QS-02 | **Comments and formatting are ALWAYS preserved** | `libcst` (not `ast.unparse`) used exclusively in `ast_transformer.py`; round-trip test in T-06 verifies zero comment loss |
| QS-03 | **Pydantic alias is ALWAYS injected on rename** | `SchemaAliasInjector` transformer in `ast_transformer.py` adds `Field(alias=old_name)` and `populate_by_name=True` to every schema that exposes the renamed field; verified in T-08 |
| QS-04 | **Alembic migration is ALWAYS multi-phase** | `migration_generator.py` emits two migration files: phase1 (add+backfill) and phase2 (drop old column); single `ALTER TABLE RENAME` is never generated; verified in T-14 |
| QS-05 | **Dry-run NEVER writes to disk** | `refactor_engine.py::dry_run()` operates on in-memory `dict[str, str]` and returns `DryRunReport`; filesystem writes require `apply=True`; verified in T-17 |
| QS-06 | **Patch is ALWAYS validated before output** | `validate_patch()` in `patch_generator.py` calls `git apply --check` before returning; invalid patches raise `RuntimeError` with actionable message |
| QS-07 | **Test files are ALWAYS updated alongside production code** | `RefactorEngine.walk()` includes `tests/` directory by default; skipping tests requires explicit `include_tests=False`; verified in T-04 |
| QS-08 | **Rename collision is ALWAYS detected before any change** | `CollisionChecker` runs first in `refactor_engine.py`; raises `RefactorConflictError` if `new_name` already exists as attribute on the same model class |
| QS-09 | **String references in raw SQL are flagged, NEVER silently skipped** | `RawSQLScanner` in `reference_scanner.py` uses regex to find `"email"` in `op.execute()` strings; appends to `patch_notes["manual_review"]` |
| QS-10 | **Dynamic `getattr` references are flagged in patch notes** | `DynamicAccessScanner` in `reference_scanner.py` detects `getattr(obj, "email")` patterns; adds file+line to `patch_notes["dynamic_access"]` |
| QS-11 | **Tool is idempotent — second run produces empty patch** | `RefactorEngine.run()` checks if `new_name` already exists; returns `{status: "no_op"}` without writing; verified in T-25 |
| QS-12 | **OpenAPI snapshot is ALWAYS regenerated after patch apply** | Post-apply hook in `refactor_engine.py` calls `generate_openapi_snapshot(project_dir)` if `openapi_snapshot.json` exists; CI diff catches unintended breaks |

---

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `app/tools/refactor/refactor_engine.py` exists and exports `RefactorEngine` | `from app.tools.refactor.refactor_engine import RefactorEngine` does not raise |
| CC-02 | `app/tools/refactor/ast_transformer.py` exports `FieldRenameTransformer`, `ModelRenameTransformer`, `SchemaAliasInjector` | File exists; inspect exports |
| CC-03 | `app/tools/refactor/patch_generator.py` exports `generate_patch`, `validate_patch` | File exists; inspect exports |
| CC-04 | `app/tools/refactor/reference_scanner.py` exports `RawSQLScanner`, `DynamicAccessScanner` | File exists; inspect exports |
| CC-05 | `app/tools/refactor/migration_generator.py` exports `generate_rename_migration` | File exists; inspect exports |
| CC-06 | `app/tools/refactor/ci_gate.py` exports `RefactorCIGate` | File exists; inspect exports |
| CC-07 | `tests/test_refactor_model.py` exists with ≥ 30 test functions | `grep -c "^def test_"` returns ≥ 30 |
| CC-08 | `Makefile` has targets `refactor-dry-run` and `refactor-apply` | grep `refactor-dry-run` Makefile |
| CC-09 | `rename_field` operation rewrites SQLAlchemy model attribute name | Run T-01; model attribute changed |
| CC-10 | `rename_field` operation rewrites Pydantic schema field name | Run T-08; schema field changed |
| CC-11 | `rename_field` injects `Field(alias=old_name)` in all schemas | grep `alias="email"` in schemas after rename |
| CC-12 | `rename_field` rewrites CRUD attribute access (`.email` → `.email_address`) | Run T-03; CRUD rewritten |
| CC-13 | `rename_field` rewrites route handler attribute access | Run T-04; route handler rewritten |
| CC-14 | `rename_field` rewrites test keyword arguments | Run T-04; test factory kwargs rewritten |
| CC-15 | `rename_model` rewrites class name and all import statements | Run T-21; class and imports updated |
| CC-16 | `rename_model` rewrites FK references (`ForeignKey("users.id")` → `ForeignKey("new_name.id")`) | grep old tablename in models is zero after rename |
| CC-17 | `change_type` generates migration with `op.alter_column(type_=new_type)` | Inspect migration |
| CC-18 | `generate_migration=True` creates Alembic migration file in `alembic/versions/` | File exists after run |
| CC-19 | Migration phase 1 adds new column nullable, backfills in batches, promotes NOT NULL | Inspect `upgrade()` function |
| CC-20 | Migration phase 2 drops old column | `0044_phase2` file exists and `downgrade()` is correct |
| CC-21 | Migration `downgrade()` reverses all changes in correct order | Run `alembic downgrade -1`; schema restored |
| CC-22 | Dry-run returns `DryRunReport` with `affected_files`, `reference_counts`, `patch_preview` | T-17 verifies |
| CC-23 | Dry-run writes zero bytes to filesystem | T-17: filesystem checksum identical before/after |
| CC-24 | `getattr` references appear in `patch_notes["dynamic_access"]` | T-27 verifies scanner output |
| CC-25 | Raw SQL string references appear in `patch_notes["manual_review"]` | T-28 verifies scanner output |
| CC-26 | Rename collision (new name already exists) raises `RefactorConflictError` | T-23 verifies error raised |
| CC-27 | Patch validates cleanly via `git apply --check` | `validate_patch()` returns `True` |
| CC-28 | Second run on already-renamed codebase returns `{status: "no_op"}` | T-25 verifies idempotency |
| CC-29 | CI gate `RefactorCIGate` blocks merge if old name still referenced post-apply | T-19 verifies CI gate |
| CC-30 | OpenAPI snapshot is regenerated post-apply if it exists | T-22 verifies snapshot refresh |
| CC-31 | `update_schemas=False` skips schema rewrite but still updates model and CRUD | T-29 verifies schema skipped |
| CC-32 | `update_routes=False` skips route rewrite | T-30 verifies route skipped |
| CC-33 | Tool execution time < 5s for 100-file project | Benchmark in T-05; timing recorded |
| CC-34 | `populate_by_name=True` added to model_config in all schemas with alias | grep `populate_by_name` in schemas after rename |

---

## 7. Definition of Done

- [ ] All 34 Completeness Criteria verified (CC-01..CC-34)
- [ ] All 12 Quality Standards enforced (QS-01..QS-12)
- [ ] All 8 Invariants enforced (INV-RM-01..INV-RM-08; see §8)
- [ ] All 25 User Stories pass acceptance tests (see §9)
- [ ] All 30 Test Cases pass (T-01..T-30; see §10)
- [ ] Tool is idempotent: run twice on same codebase, second run returns `{status: "no_op"}`
- [ ] Tool is reversible: `git apply --reverse refactor.patch` restores full original state
- [ ] Rollback procedure documented and validated end-to-end (see §12)
- [ ] Migration safety validated: phase1 tested on simulated 10M-row table; backfill completes < 60s
- [ ] Interaction with tools TOOL-001, TOOL-005, TOOL-008, TOOL-033, TOOL-036, TOOL-039 verified (see §11)
- [ ] All 15 edge cases handled (see §13)
- [ ] Documentation updated (`KNOWLEDGE.md`, `manifest.yaml`, `SKILL.md`)
- [ ] Tool registered in `mcp_server.py` under `EVOLVE` category
- [ ] Re-audit by Opus in fresh context: ≥ 9.5/10

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-RM-01 | Refactor is **always** atomic — all target files change or none | Single `git apply` atomically applies all hunks; failure leaves codebase untouched; partial state is impossible | T-15, T-16 |
| INV-RM-02 | Comments and formatting are **always** preserved after rewrite | `libcst` used exclusively; round-trip `parse → transform → code` verified bit-for-bit against original for non-renamed tokens | T-06 |
| INV-RM-03 | Pydantic `Field(alias=old_name)` is **always** injected for every schema field rename | `SchemaAliasInjector` runs unconditionally when `update_schemas=True`; alias removal requires explicit `--remove-alias` flag after migration window | T-08, T-09 |
| INV-RM-04 | Alembic migration is **always** multi-phase (never single `RENAME COLUMN`) | `migration_generator.py` hardcodes ADD+backfill+promote+defer-drop strategy; single-phase path does not exist in code | T-14 |
| INV-RM-05 | Dry-run **never** writes to disk | `RefactorEngine.dry_run()` holds all rewrites in `dict[str, str]`; no `Path.write_text` calls; verified with filesystem snapshot | T-17 |
| INV-RM-06 | Patch is **always** validated via `git apply --check` before output | `validate_patch()` is called unconditionally in `RefactorEngine._emit_patch()`; raises `RuntimeError` on failure | T-18 |
| INV-RM-07 | Test files are **always** updated alongside production code | `RefactorEngine.walk()` includes `tests/` in file set; excluded only by explicit `include_tests=False` | T-04, T-07 |
| INV-RM-08 | Rename collision is **always** detected and blocked before any rewrite | `CollisionChecker.check()` runs as first step; raises `RefactorConflictError` if `new_name` already exists as attribute or class | T-23 |

---

## 9. User Stories

### 9.1 Rename field — model + schema + CRUD + tests (US-01..US-05)

**US-01: Rename a SQLAlchemy column and see all references updated**
- **As a** backend developer who made a naming mistake during initial development
- **I want** to rename `User.email` to `User.email_address` across the entire codebase in one command
- **So that** the codebase is consistent and the database column matches the domain vocabulary
- **Given:** project has `User.email` in model, schema, CRUD, routes, and 15 test files
- **When:** I call `refactor_model(project_dir, operation="rename_field", target="app.models.User.email", new_name="email_address")`
- **Then:**
  - `User.email` annotation renamed to `User.email_address` in model (INV-RM-02: comment preserved)
  - All `schema.email` fields renamed; `Field(alias="email")` injected (INV-RM-03)
  - `crud.get_by_email(email=...)` kwarg rewritten to `email_address=...`
  - 15 test files updated (INV-RM-07)
  - Alembic migration generated with ADD+backfill+promote strategy (INV-RM-04)
  - Patch file at `refactor.patch` ready for `git apply`

**US-02: Dry-run shows full impact before any change**
- **As a** developer who is cautious about large refactors
- **I want** to see exactly which files and how many references will change before committing
- **So that** I can verify the blast radius is correct and spot unexpected hits
- **Given:** project with 80 Python files
- **When:** I run in dry-run mode (no `--apply` flag)
- **Then:**
  - `DryRunReport` printed with file list, per-file reference count, and patch preview
  - Zero bytes written to filesystem (CC-23, INV-RM-05)
  - Report includes `manual_review` list for any raw SQL references (CC-25)
  - Report includes `dynamic_access` list for any `getattr` usages (CC-24)
  - Tool exits in < 2s (Performance SLO)

**US-03: CRUD keyword arguments are rewritten correctly**
- **As a** developer who uses keyword-argument-style model instantiation throughout the codebase
- **I want** `User(email=value)` rewritten to `User(email_address=value)` in all 20 files that call it
- **So that** the code runs without `TypeError: unexpected keyword argument` after the rename
- **Given:** 20 files use `User(email=...)` or `create(email=...)`
- **When:** refactor applied with `update_schemas=True, update_routes=True`
- **Then:**
  - All 20 `email=` keyword arguments rewritten to `email_address=` (CC-12, CC-13)
  - No `User(email=...)` pattern remains (CI gate T-19 enforces this)
  - `grep -r 'User(email=' app/` returns zero matches
  - Test file factories also updated (CC-14, INV-RM-07)
  - Reference count in dry-run report matches actual count

**US-04: Pydantic alias preserves JSON wire format for live clients**
- **As a** developer who cannot break the mobile client during a rename migration
- **I want** the Pydantic schema to still accept `{"email": "x@example.com"}` in JSON payloads during the dual-read window
- **So that** the frontend can migrate to `email_address` at its own pace without a hard cutover
- **Given:** `UserCreate` currently expects `email` in JSON body
- **When:** refactor applied; schema updated
- **Then:**
  - `UserCreate.email_address` accepts both `"email_address"` and `"email"` (via alias) (INV-RM-03)
  - `model_config = {"populate_by_name": True}` added automatically (CC-34)
  - `UserPublic` serializes as `{"email": "...", "id": "..."}` for old clients during window
  - Spec notes that `alias` should be removed after migration window via TOOL-044 `--remove-alias` flag

**US-05: Migration backfills existing rows without data loss**
- **As a** DevOps engineer running the migration on a 5M-row production table
- **I want** the rename migration to backfill every row safely without long table locks
- **So that** the rename does not cause downtime or data corruption
- **Given:** `users` table has 5M rows; production traffic running
- **When:** `alembic upgrade head` runs
- **Then:**
  - New column `email_address` added nullable (no lock) (CC-19)
  - Batched UPDATE in 50k-row chunks copies `email → email_address` with VACUUM-friendly gaps
  - Column promoted to NOT NULL after all rows filled
  - Old column retained for dual-read window; phase 2 migration removes it (CC-20)
  - Zero rows with NULL `email_address` exist after phase 1 completes

### 9.2 Rename model — class + imports + FK references + relationships (US-06..US-10)

**US-06: Rename a model class and all import statements are updated**
- **As a** developer renaming `UserProfile` to `Profile` to follow a domain-driven naming convention
- **I want** all `from app.models.user_profile import UserProfile` imports updated automatically
- **So that** no `ImportError` or `NameError` occurs after the rename
- **Given:** `UserProfile` imported in 25 files; `UserProfileCreate`, `UserProfilePublic` schemas exist
- **When:** `refactor_model(..., operation="rename_model", target="app.models.UserProfile", new_name="Profile")`
- **Then:**
  - Class renamed in model file; file renamed to `profile.py` (INV-RM-01: atomically)
  - All 25 import statements updated (CC-15)
  - Schemas renamed: `UserProfileCreate` → `ProfileCreate`, `UserProfilePublic` → `ProfilePublic`
  - `__init__.py` re-exports updated
  - Patch includes all changes in a single unified diff

**US-07: FK references to renamed model are updated in all related models**
- **As a** developer renaming `UserProfile` to `Profile`
- **I want** `ForeignKey("user_profiles.id")` strings updated to `ForeignKey("profiles.id")`
- **So that** SQLAlchemy can resolve relationships correctly after the rename
- **Given:** 4 models reference `ForeignKey("user_profiles.id")`; 2 have `relationship("UserProfile")`
- **When:** `rename_model` applied
- **Then:**
  - All FK strings updated to `"profiles.id"` (CC-16)
  - `relationship("UserProfile")` strings updated to `relationship("Profile")`
  - Migration renames the table: `op.rename_table("user_profiles", "profiles")`
  - `__tablename__` updated in model class definition (INV-RM-02: formatting preserved)

**US-08: Test factories and fixtures reference new class name**
- **As a** QA engineer who relies on pytest factories to create model instances
- **I want** all `UserProfileFactory.create()` calls updated to `ProfileFactory.create()`
- **So that** test suite runs green after the rename without manual fixup
- **Given:** `tests/factories.py` defines `UserProfileFactory`; 12 test files use it
- **When:** `rename_model` applied with `update_routes=True` (tests included by default, INV-RM-07)
- **Then:**
  - `UserProfileFactory` renamed to `ProfileFactory` in `tests/factories.py`
  - All 12 test files updated: `UserProfileFactory` → `ProfileFactory` (T-04)
  - No `UserProfileFactory` reference remains (CC-15)
  - Test suite passes with zero failures after applying patch

**US-09: `rename_model` blocks if collision exists**
- **As a** developer who accidentally tries to rename `User` to `Account` when `Account` class already exists in the same module
- **I want** an immediate error with a clear message rather than a corrupted codebase
- **So that** I can choose a different name without risking an inconsistent state
- **Given:** `app/models/user.py` has `User`; `app/models/account.py` has `Account`
- **When:** `refactor_model(..., target="app.models.User", new_name="Account")` called
- **Then:**
  - `RefactorConflictError("Account already exists in app/models/account.py")` raised immediately (INV-RM-08, CC-26)
  - Zero files modified (dry-run-equivalent check runs before any transform)
  - Error message includes the conflicting file path and line number

**US-10: `rename_model` updates `__init__.py` re-exports**
- **As a** developer maintaining a public package API
- **I want** `from app.models import UserProfile` in `__init__.py` updated to `from app.models import Profile`
- **So that** downstream code using the package API doesn't break on `ImportError`
- **Given:** `app/models/__init__.py` exports `UserProfile` by name
- **When:** `rename_model` runs
- **Then:**
  - `__init__.py` import updated to use new class name
  - `as UserProfile` alias added temporarily if backward-compat mode enabled
  - Patch notes flag `__init__.py` re-export change for manual review of public API consumers
  - No circular import introduced (CC-33 timing verified)

### 9.3 Change type — widening + enum + type-narrowing blocker (US-11..US-15)

**US-11: Widen String(50) to String(255) with safe migration**
- **As a** developer who underestimated the length of a user-provided field
- **I want** `User.name: String(50)` widened to `String(255)` without a table lock or data loss
- **So that** users can enter longer names without truncation errors
- **Given:** `users.name VARCHAR(50)` has 500k rows; some names are 45 chars long
- **When:** `refactor_model(..., operation="change_type", target="app.models.User.name", new_name="String(255)")`
- **Then:**
  - SQLAlchemy model updated: `mapped_column(String(255), ...)` (CC-17)
  - Migration uses `op.alter_column("users", "name", type_=sa.String(255))` — non-blocking in Postgres
  - Pydantic schema validator updated: `Field(max_length=255)` replaces `max_length=50`
  - No data loss: `VARCHAR` widening never truncates existing data

**US-12: Add enum value with backward-compatible migration**
- **As a** developer adding a new status to an enum field
- **I want** `status: Enum("active", "inactive")` extended to include `"suspended"` without breaking existing rows
- **So that** the new value is immediately available without a downtime migration
- **Given:** `orders.status` is `Enum("active", "inactive")` with 200k rows
- **When:** `change_type` with `new_name="active,inactive,suspended"`
- **Then:**
  - Migration adds enum value: `op.execute("ALTER TYPE order_status ADD VALUE 'suspended'")`
  - SQLAlchemy model enum updated
  - Pydantic `Literal["active", "inactive", "suspended"]` updated in schema
  - Existing rows unaffected; new code can write `"suspended"` immediately

**US-13: Narrowing a column type is blocked with clear error**
- **As a** developer attempting to shrink a `String(255)` to `String(50)` on a column with data**
- **I want** the tool to block the operation and show me which rows would be truncated
- **So that** I don't accidentally corrupt production data with a silent truncation
- **Given:** `users.name VARCHAR(255)` has rows where `len(name) > 50`
- **When:** `change_type` from `String(255)` to `String(50)` called
- **Then:**
  - Tool detects `new_type.length < current_type.length` (INV-RM-08 extended to type checks)
  - Raises `RefactorUnsafeError("Narrowing String(255) → String(50) may truncate data. Use --force-narrow to override.")` (T-23 variant)
  - No migration generated; no files modified

**US-14: `Integer → BigInteger` migration is generated correctly**
- **As a** developer whose auto-increment PK is approaching INT_MAX (2.1B)**
- **I want** to widen `id: Integer` to `BigInteger` before the table fills up
- **So that** the service doesn't crash with an overflow error in production
- **Given:** `items.id` is `Integer`; table has 1.5B rows
- **When:** `change_type` from `Integer` to `BigInteger`
- **Then:**
  - Migration uses `op.alter_column("items", "id", type_=sa.BigInteger())` — instant DDL in Postgres
  - SQLAlchemy model updated: `mapped_column(BigInteger, primary_key=True, ...)`
  - Pydantic schema updated: `id: int` (already compatible; no change needed)
  - Patch notes flag that `int` in Python covers both; no schema change required

**US-15: Patch mode lets developer review before applying**
- **As a** team lead reviewing a refactor PR
- **I want** to see the complete diff as a single `.patch` file that I can inspect and apply with `git apply`
- **So that** I have a human-readable record of every change and can reverse it with `git apply --reverse`
- **Given:** any refactor operation
- **When:** tool runs (default: patch mode, no `--apply`)
- **Then:**
  - `refactor.patch` written to `project_dir/.refactor/` (CC-27 implicit)
  - Patch validated via `git apply --check` before output (INV-RM-06, CC-27)
  - Patch includes `---`/`+++` headers, line numbers, context lines
  - `git apply --reverse refactor.patch` cleanly restores original state (T-20)

### 9.4 Multi-phase migration — add+backfill+drop (US-16..US-20)

**US-16: Add new column in phase 1, remove old in phase 2**
- **As a** DevOps engineer running a zero-downtime deployment
- **I want** the migration to add `email_address` first and keep `email` alive
- **So that** old app instances reading `email` and new instances reading `email_address` can coexist during a rolling deploy
- **Given:** rolling deploy: 50% old code, 50% new code simultaneously during deploy window
- **When:** phase 1 migration applied
- **Then:**
  - `email_address` column exists with NOT NULL constraint after phase 1 (CC-19)
  - `email` column still exists; old app instances read it successfully
  - Alembic version table records `0044_phase1` as current revision (INV-RM-04)
  - Dual-write logic: new CRUD writes both `email` and `email_address` during window

**US-17: Phase 2 drops old column safely after cutover confirmed**
- **As a** DevOps engineer completing the rename migration
- **I want** to run the phase 2 migration to drop `email` only after confirming all instances use `email_address`
- **So that** the old column doesn't linger and waste storage
- **Given:** phase 1 applied; all app instances running new code
- **When:** `alembic upgrade 0044_phase2` runs
- **Then:**
  - `email` column dropped with `op.drop_column("users", "email")`
  - Unique constraint and index for old `email` dropped first
  - Zero data loss: all data already in `email_address`
  - `downgrade()` re-adds `email` from `email_address` if needed (§12 rollback)

**US-18: Tool generates both migration files in correct dependency chain**
- **As a** developer running `alembic upgrade head` after the refactor
- **I want** both `0044_phase1` and `0044_phase2` to be generated with correct `down_revision` chain
- **So that** `alembic upgrade head` applies both in order, and `alembic downgrade base` reverses correctly
- **Given:** current head revision is `0043`
- **When:** `refactor_model` runs with `generate_migration=True`
- **Then:**
  - `0044_phase1.py`: `down_revision = "0043"` (CC-19)
  - `0044_phase2.py`: `down_revision = "0044_phase1"` (CC-20)
  - `alembic history` shows both; `alembic upgrade head` applies phase1 then phase2

**US-19: Rollback via `git apply --reverse` is tested and documented**
- **As a** developer who discovers a mistake in the rename after applying the patch
- **I want** a documented, tested rollback procedure that undoes all file changes in 30 seconds
- **So that** I can recover from a bad refactor without hunting through git blame
- **Given:** patch applied; mistake discovered before alembic migration run
- **When:** I follow the rollback procedure in §12
- **Then:**
  - `git apply --reverse .refactor/refactor.patch` restores all source files (INV-RM-01)
  - `alembic downgrade -1` reverses the migration (if it was applied)
  - `pytest` passes with original test suite
  - No residual references to `email_address` anywhere (T-25 idempotency check)

**US-20: CI gate blocks merge if old field name still referenced**
- **As a** CI administrator ensuring code quality after a refactor
- **I want** the CI pipeline to fail if any file still references the old field name after the patch was applied
- **So that** stale references don't sneak through code review
- **Given:** `refactor.patch` applied; one file accidentally reverted
- **When:** CI runs `RefactorCIGate.check(project_dir, old_name="email", new_name="email_address")`
- **Then:**
  - CI gate detects `User.email` reference in reverted file (CC-29, T-19)
  - Exits with code 1 and prints file path + line number
  - PR blocked from merging until reference removed

### 9.5 Edge cases — string refs, dynamic access, idempotency, cycles (US-21..US-25)

**US-21: Raw SQL string references flagged for manual review**
- **As a** developer with a legacy `op.execute("SELECT email FROM users")` in an old migration
- **I want** the tool to flag this for manual review rather than silently skipping it
- **So that** I know exactly which SQL strings need manual update
- **Given:** `alembic/versions/0010_legacy.py` contains `"SELECT email FROM users"`
- **When:** `rename_field` runs (CC-25, QS-09)
- **Then:**
  - `RawSQLScanner` detects the string; adds to `patch_notes["manual_review"]`
  - File is NOT auto-modified (regex rewrite would be too risky)
  - Patch notes printed to console and written to `.refactor/patch_notes.json`
  - Tool exits successfully; developer reviews manual list (T-28)

**US-22: Dynamic `getattr` access flagged, not auto-rewritten**
- **As a** developer who has `getattr(user, field_name)` where `field_name = "email"` in a config file
- **I want** the tool to flag this dynamic access rather than incorrectly rewriting `field_name = "email"` to `field_name = "email_address"` if that string is in a different context
- **So that** dynamic dispatch code isn't silently broken
- **Given:** `service.py` has `value = getattr(user, "email")`
- **When:** `rename_field` runs (CC-24, QS-10)
- **Then:**
  - `DynamicAccessScanner` detects the pattern; adds to `patch_notes["dynamic_access"]`
  - String `"email"` inside `getattr` is NOT rewritten automatically
  - Patch notes list file + line number for developer to update manually
  - T-27 verifies scanner output contains the expected entry

**US-23: Tool is idempotent — second run produces no changes**
- **As a** developer who accidentally runs the refactor tool twice on the same codebase
- **I want** the second run to be a safe no-op rather than double-applying the rename
- **So that** I don't end up with `email_address_address` or other corruption
- **Given:** `rename_field` successfully applied once
- **When:** `refactor_model(...)` called again with identical arguments
- **Then:**
  - `CollisionChecker` detects `email_address` already exists; `email` no longer exists (INV-RM-08)
  - Returns `{status: "no_op", reason: "email_address already exists, email not found"}` (CC-28, QS-11)
  - Zero files modified; no patch generated
  - T-25 verifies this behaviour explicitly

**US-24: Circular import after rename is detected before patch output**
- **As a** developer renaming a model that is part of a complex import graph
- **I want** the tool to detect if the rename would create a circular import and block it
- **So that** I don't apply a patch that breaks the import system at startup
- **Given:** renaming `app.models.Order` to `app.models.Purchase` would create a circular import via `app/models/__init__.py`
- **When:** `rename_model` runs with cycle detection enabled (default)
- **Then:**
  - Import graph analysis detects the cycle before generating patch (CC-33 timing)
  - Raises `RefactorCircularImportError` with the cycle path: `A → B → C → A`
  - Zero files modified; developer shown which import to restructure first (T-29 variant, INV-RM-08 extended)

**US-25: Monorepo cross-package references updated**
- **As a** developer working in a monorepo where `package_a` imports from `package_b.models.User`
- **I want** the rename to update cross-package references as well as same-package ones
- **So that** both packages are consistent after the rename
- **Given:** `package_b/app/models/user.py` has `User.email`; `package_a/app/services/auth.py` imports and uses `User.email`
- **When:** `refactor_model(project_dir, ...)` where `project_dir` is the monorepo root
- **Then:**
  - Cross-package attribute accesses (`user.email`) updated in `package_a` (T-30 variant)
  - Cross-package imports updated if model class renamed
  - Both packages' test suites updated (INV-RM-07)
  - Patch covers all packages in a single unified diff file

---

## 10. Test Plan

### 10.1 AST rewrite tests (T-01..T-06)

| # | Test name | Method | Expected |
|---|-----------|--------|----------|
| T-01 | `test_rename_field_model_attribute` | Parse `User` model source with libcst; apply `FieldRenameTransformer(old="email", new="email_address")`; unparse | `email_address: Mapped[str]` in output; `email:` absent |
| T-02 | `test_rename_model_class` | Parse model source; apply `ModelRenameTransformer(old="UserProfile", new="Profile")`; unparse | `class Profile(Base):` in output; `class UserProfile` absent |
| T-03 | `test_rename_attribute_access_in_crud` | Parse CRUD with `user.email`; transform; unparse | `user.email_address` in output; `user.email` absent |
| T-04 | `test_rename_kwarg_in_tests` | Parse test factory `User(email="x")`; transform; unparse | `User(email_address="x")` in output |
| T-05 | `test_rename_type_annotation` | Parse `email: str` function param; transform | `email_address: str` in output |
| T-06 | `test_comment_preservation_after_rename` | Parse model with `# Primary contact address` above `email` field; transform | Comment identical in output; no whitespace change |

### 10.2 Multi-phase migration tests (T-07..T-12)

| # | Test name | Method | Expected |
|---|-----------|--------|----------|
| T-07 | `test_migration_phase1_adds_nullable_column` | Call `generate_rename_migration`; inspect `upgrade()` | `op.add_column` with `nullable=True` appears before backfill |
| T-08 | `test_migration_backfill_is_batched` | Inspect generated migration source | DO $$ LOOP … LIMIT 50000 pattern present |
| T-09 | `test_migration_promotes_not_null` | Inspect migration source | `op.alter_column(..., nullable=False)` after backfill |
| T-10 | `test_migration_phase2_drops_old_column` | Inspect phase2 migration | `op.drop_column("users", "email")` present |
| T-11 | `test_migration_downgrade_reverses_phase1` | Apply phase1 migration on test DB; run `downgrade()`; inspect schema | `email_address` column absent; `email` present |
| T-12 | `test_migration_downgrade_reverses_phase2` | Apply both phases; run phase2 `downgrade()`; inspect schema | `email` column restored from `email_address` |

### 10.3 Patch generation and application tests (T-13..T-18)

| # | Test name | Method | Expected |
|---|-----------|--------|----------|
| T-13 | `test_patch_generates_valid_unified_diff` | Call `generate_patch`; inspect output | `---`/`+++` headers; correct hunk format |
| T-14 | `test_patch_apply_succeeds_on_clean_tree` | Write patch; run `git apply --check` | Exit code 0; no merge conflicts |
| T-15 | `test_patch_reverse_restores_original` | Apply patch; run `git apply --reverse`; compare checksums | All files byte-identical to original |
| T-16 | `test_patch_all_or_nothing_on_conflict` | Introduce one conflicting file; attempt `git apply` | Exit code 1; all files unchanged |
| T-17 | `test_dry_run_writes_zero_bytes` | Record filesystem checksums before/after dry-run | checksums identical; no new files |
| T-18 | `test_validate_patch_raises_on_invalid` | Generate patch against stale codebase | `RuntimeError` raised by `validate_patch()` |

### 10.4 CI gate tests (T-19..T-24)

| # | Test name | Method | Expected |
|---|-----------|--------|----------|
| T-19 | `test_ci_gate_blocks_stale_reference` | Apply patch; revert one file; run `RefactorCIGate.check()` | Exit code 1; stale file path in output |
| T-20 | `test_ci_gate_passes_on_clean_codebase` | Apply patch fully; run `RefactorCIGate.check()` | Exit code 0; `{status: "clean"}` returned |
| T-21 | `test_rename_model_updates_imports` | Apply `rename_model`; grep for old class name in all files | Zero matches outside migration history |
| T-22 | `test_openapi_snapshot_regenerated` | Place `openapi_snapshot.json` in project; apply rename | Snapshot regenerated; old field name absent |
| T-23 | `test_collision_raises_refactor_conflict_error` | Call `rename_field` with `new_name` that already exists | `RefactorConflictError` raised; zero files modified |
| T-24 | `test_narrow_type_blocked` | Call `change_type` from `String(255)` to `String(10)` | `RefactorUnsafeError` raised; no migration generated |

### 10.5 Edge case and idempotency tests (T-25..T-30)

| # | Test name | Method | Expected |
|---|-----------|--------|----------|
| T-25 | `test_second_run_is_noop` | Apply rename; run tool again | `{status: "no_op"}`; zero file changes |
| T-26 | `test_getattr_flagged_in_patch_notes` | Codebase has `getattr(user, "email")`; run rename | `patch_notes["dynamic_access"]` contains file+line |
| T-27 | `test_raw_sql_flagged_in_patch_notes` | Codebase has `op.execute("SELECT email FROM users")`; run rename | `patch_notes["manual_review"]` contains migration path |
| T-28 | `test_schema_alias_injected_correctly` | Apply rename; parse schema with libcst | `Field(..., alias="email")` present; `populate_by_name=True` in config |
| T-29 | `test_update_schemas_false_skips_schema` | Run with `update_schemas=False` | Schema unchanged; model and CRUD updated |
| T-30 | `test_update_routes_false_skips_routes` | Run with `update_routes=False` | Routes unchanged; model and schemas updated |

---

## 11. Interaction Matrix

| Tool | Direction | Interaction |
|------|-----------|-------------|
| TOOL-001 `fastapi_add_soft_delete` | Downstream | If `deleted_at` field is the target of a rename, TOOL-044 must rewrite `soft_delete_filter()` in `crud/base.py`; the soft-delete filter uses attribute access `Model.deleted_at` which is a libcst `Attribute` node |
| TOOL-005 `fastapi_add_audit_log` | Downstream | Audit log listeners reference `before[field]` and `after[field]` by string key; `RawSQLScanner` flags these as manual-review items; user must update `AUDITED_FIELDS` list in `audit_listener.py` |
| TOOL-008 `fastapi_add_multi_tenancy` | Bidirectional | If `tenant_id` FK column is renamed (rare but possible), TOOL-044 updates `TenantScopedMixin.tenant_id` and the middleware contextvar reference; if TOOL-008 was run after TOOL-044, alias on `tenant_id` must not be removed during migration window |
| TOOL-033 `fastapi_api_spec_compliance` | Downstream | After TOOL-044 renames a field, the OpenAPI spec diverges; TOOL-033's compliance checker must be re-run to verify the spec matches the new field names; TOOL-044 regenerates `openapi_snapshot.json` post-apply (QS-12) |
| TOOL-036 `fastapi_migration_diff` | Upstream | TOOL-036 generates migration diffs by comparing SQLAlchemy models to DB schema; TOOL-044's phase1 migration creates a transient state where model has `email_address` but DB has both; TOOL-036 must be run after phase2 to confirm no drift |
| TOOL-039 `fastapi_dependency_graph` | Upstream | TOOL-039 maps import dependencies; TOOL-044 reads the dependency graph to determine safe traversal order (import-safe rename order) and detect circular import risks before generating patches |
| TOOL-021 `fastapi_add_cache_layer` | Downstream | Cache keys built from field names (e.g. `cache:tenant:user:{email}`) must be updated; `RawSQLScanner` flags these key patterns; TOOL-044 adds them to `patch_notes["manual_review"]` |
| TOOL-002 `fastapi_add_auth` | Downstream | Auth dependency `get_user_by_email(email)` function parameter renames must be updated; TOOL-044 rewrites function param names via `FieldRenameTransformer` on `Arg` nodes |
| TOOL-003 `fastapi_add_pagination` | Downstream | Pagination filter expressions like `.filter(User.email.contains(q))` are rewritten as attribute accesses; handled by `Attribute` node transformer |
| TOOL-010 `fastapi_add_search` | Downstream | Search index configuration in `search_config.py` references field names as strings; `RawSQLScanner` detects and flags these for manual update |
| TOOL-015 `fastapi_add_webhooks` | Downstream | Webhook payload serializers reference field names; if field is in webhook payload schema, TOOL-044 updates schema and alias |
| TOOL-020 `fastapi_add_rate_limiting` | Orthogonal | Rate limiting by IP/user_id — no field name dependency; TOOL-044 has no interaction |
| TOOL-025 `fastapi_add_background_tasks` | Downstream | Background task functions that receive model fields by keyword argument are updated by TOOL-044's `Arg` node transformer (INV-RM-07 scope includes all Python files, not just `app/`) |
| TOOL-031 `fastapi_add_file_upload` | Downstream | Upload metadata model fields renamed by TOOL-044 require migration; same multi-phase strategy applied |
| TOOL-040 `fastapi_generate_crud` | Upstream | If CRUD was generated by TOOL-040 after a prior rename, re-generation would regenerate old field names; CI gate (T-19) catches this — TOOL-040 must be re-run after TOOL-044 to regenerate consistent CRUD |

---

## 12. Rollback Procedure

### 12.1 Code rollback — reverse the patch

If the patch has been applied via `git apply` but the migration has NOT yet been run:

```bash
# Step 1: verify the current state
cd /path/to/project
git diff --stat  # shows files modified by the patch

# Step 2: reverse the patch atomically
git apply --reverse .refactor/refactor.patch

# Step 3: verify all files restored
git diff --stat  # must show zero files changed

# Step 4: confirm old field name is back
grep -r "email_address" app/ --include="*.py"  # must return zero matches

# Step 5: run tests to confirm baseline
PYTHONPATH=src pytest tests/ -q --tb=short
# Expected: same pass/fail as before refactor
```

If `git apply --reverse` fails (rare — means codebase changed after patch was generated):

```bash
# Fallback: restore from git stash (if stashed before applying) or last commit
git stash pop
# OR
git checkout HEAD -- app/models/ app/schemas/ app/crud/ app/api/ tests/
```

### 12.2 Database rollback — revert Alembic migrations

If phase 1 migration was applied but phase 2 was NOT yet run:

```bash
# Step 1: confirm current migration head
alembic current
# Expected: 0044_phase1

# Step 2: downgrade phase 1
alembic downgrade -1
# This runs 0044_phase1.downgrade():
#   op.drop_index("ix_users_email_address")
#   op.drop_constraint("uq_users_email_address")
#   op.drop_column("users", "email_address")

# Step 3: confirm schema restored
psql $DATABASE_URL -c "\d users"
# Expected: email_address column absent; email column present

# Step 4: verify no data loss
psql $DATABASE_URL -c "SELECT COUNT(*) FROM users WHERE email IS NULL"
# Expected: 0
```

If phase 2 migration was also applied (both columns renamed, old dropped):

```bash
# Step 1: check current head
alembic current
# Expected: 0044_phase2

# Step 2: downgrade phase 2 first
alembic downgrade -1
# This runs 0044_phase2.downgrade():
#   op.add_column("users", sa.Column("email", sa.String(255), nullable=True))
#   op.execute("UPDATE users SET email = email_address")
#   op.alter_column("users", "email", nullable=False)
#   op.create_unique_constraint("uq_users_email", "users", ["email"])
#   op.create_index("ix_users_email", "users", ["email"], unique=True)

# Step 3: downgrade phase 1
alembic downgrade -1
# Drops email_address column

# Step 4: verify original schema
psql $DATABASE_URL -c "\d users"
# Expected: email column present; email_address absent
```

### 12.3 Data preservation rollback

The multi-phase strategy ensures data is NEVER deleted during phase 1. Data preservation specifics:

```bash
# Verify no data was lost at any phase
psql $DATABASE_URL -c "
  SELECT
    COUNT(*) AS total_rows,
    COUNT(email) AS rows_with_email,
    COUNT(email_address) AS rows_with_email_address
  FROM users;
"
# During dual-read window: all three counts must be equal
# After phase1: rows_with_email = rows_with_email_address = total_rows

# If backfill was interrupted mid-run (e.g. migration timeout):
psql $DATABASE_URL -c "SELECT COUNT(*) FROM users WHERE email_address IS NULL"
# If > 0, re-run the backfill manually:
psql $DATABASE_URL -c "
  UPDATE users SET email_address = email WHERE email_address IS NULL;
"
# Then re-run alembic upgrade to complete the NOT NULL promotion
alembic upgrade 0044_phase1
```

### 12.4 Failure mode: patch conflicts after codebase diverged

**Symptom:** `git apply --reverse .refactor/refactor.patch` exits with code 1 and reports "patch does not apply".

**Cause:** Codebase was modified after the patch was generated (e.g. another developer merged changes).

```bash
# Step 1: identify which hunks fail
git apply --reverse --reject .refactor/refactor.patch
# Creates .rej files for failed hunks

# Step 2: manually inspect rejected hunks
find . -name "*.rej" -exec cat {} \;

# Step 3: manually revert the failing files using the .rej content as guide
# For each .rej: find the new_name references and replace with old_name
grep -rn "email_address" app/ --include="*.py" | while read line; do
    file=$(echo "$line" | cut -d: -f1)
    echo "Manual review needed: $file"
done

# Step 4: remove .rej files after manual resolution
find . -name "*.rej" -delete

# Step 5: run tests
PYTHONPATH=src pytest tests/ -q
```

### 12.5 Failure mode: alembic downgrade blocked by FK constraint

**Symptom:** `alembic downgrade -1` fails with `ForeignKeyViolationError` because another table references the column being dropped.

```bash
# Step 1: identify blocking FKs
psql $DATABASE_URL -c "
  SELECT
    tc.table_name,
    kcu.column_name,
    ccu.table_name AS foreign_table,
    ccu.column_name AS foreign_column
  FROM information_schema.table_constraints tc
  JOIN information_schema.key_column_usage kcu
    ON tc.constraint_name = kcu.constraint_name
  JOIN information_schema.constraint_column_usage ccu
    ON ccu.constraint_name = tc.constraint_name
  WHERE tc.constraint_type = 'FOREIGN KEY'
    AND ccu.column_name = 'email_address';
"

# Step 2: temporarily drop the blocking FK before downgrade
psql $DATABASE_URL -c "
  ALTER TABLE orders DROP CONSTRAINT IF EXISTS fk_orders_user_email_address;
"

# Step 3: run downgrade
alembic downgrade -1

# Step 4: restore FK with old column name
psql $DATABASE_URL -c "
  ALTER TABLE orders
    ADD CONSTRAINT fk_orders_user_email
    FOREIGN KEY (user_email) REFERENCES users(email);
"
```

### 12.6 Emergency: schema out of sync between ORM and database

**Symptom:** Application starts with `OperationalError: column users.email_address does not exist` because patch applied but migration not run.

```bash
# Step 1: check what the DB actually has
psql $DATABASE_URL -c "
  SELECT column_name, data_type, is_nullable
  FROM information_schema.columns
  WHERE table_name = 'users'
  ORDER BY ordinal_position;
"

# Option A: the DB is behind — run the migration
alembic upgrade head

# Option B: the patch was applied prematurely — rollback code instead
git apply --reverse .refactor/refactor.patch
# This restores the model to use `email` which matches the DB
# Migration step: **N/A** — code-only rollback; no alembic downgrade required because migration was never run

# Step 3: verify app health
curl -s http://localhost:8000/health | python3 -m json.tool
# Expected: {"status": "ok", "db": "connected"}
```

---

## 13. Edge Cases

| ID | Scenario | Expected behavior |
|----|----------|------------------|
| EC-01 | Field referenced via `getattr(obj, "email")` | Flagged in `patch_notes["dynamic_access"]` with file+line; NOT auto-rewritten; manual review required |
| EC-02 | Field name is a SQL reserved word (e.g. `order`) | `migration_generator.py` quotes the column: `op.add_column(..., sa.Column('"order"', ...))` |
| EC-03 | Rename creates collision with existing attribute | `RefactorConflictError` raised immediately; zero files modified; error includes conflicting file path |
| EC-04 | Model has 100+ references across 40 files | All 100+ references updated in single patch; tool execution < 5s; reference count reported |
| EC-05 | Comments between field definitions in model | libcst preserves all comments and blank lines exactly; round-trip test T-06 verifies |
| EC-06 | Tests import renamed field from fixtures (`conftest.py`) | `conftest.py` included in walk scope; `FieldRenameTransformer` applied; fixture updated |
| EC-07 | Migration runs out of disk mid-backfill | Postgres transaction rolls back automatically; `email_address` column dropped; Alembic records no migration applied |
| EC-08 | Same refactor applied twice | Second run returns `{status: "no_op"}`; no double-rename like `email_address_address` possible |
| EC-09 | Field renamed in `__init__.py` re-export | `__init__.py` included in walk; import alias updated; backward-compat alias added if configured |
| EC-10 | String column name in raw SQL (`"SELECT email"`) | `RawSQLScanner` flags it in `patch_notes["manual_review"]`; NOT auto-modified; developer notified |
| EC-11 | Dry-run then apply produces identical results | Patch generated from same in-memory state; filesystem checksum after apply matches dry-run report |
| EC-12 | Circular import detected after rename | `RefactorCircularImportError` raised with cycle path before any file written; zero files modified |
| EC-13 | Multi-package monorepo with cross-package references | `RefactorEngine.walk()` traverses all Python packages under `project_dir`; cross-package `Attribute` nodes updated |
| EC-14 | Rename blocked by FK referencing the column | Two-phase plan generated: phase1 renames column with dual-write; FK updated to new name before phase2 drop |
| EC-15 | Narrowing a column type (data truncation risk) | `RefactorUnsafeError` raised; migration NOT generated; user must pass `--force-narrow` to override |

---

## 14. Acceptance Criteria

✅ 1. `refactor_model(..., operation="rename_field", target="app.models.User.email", new_name="email_address")` produces a valid `git apply`-able patch that renames all references across model, schemas, CRUD, routes, and tests.
✅ 2. Comments and formatting in all modified files are byte-for-byte identical for unchanged lines (libcst round-trip, not ast.unparse).
✅ 3. Every Pydantic schema exposing the renamed field has `Field(alias="email")` and `populate_by_name=True` added automatically.
✅ 4. Generated Alembic migration is multi-phase: phase1 adds new column (nullable), backfills in 50k-row batches, promotes to NOT NULL; phase2 drops old column.
✅ 5. Dry-run mode writes zero bytes to filesystem and returns `DryRunReport` with `affected_files`, `reference_counts`, and `manual_review` lists.
✅ 6. Patch is validated via `git apply --check` before output; invalid patches raise `RuntimeError` with actionable message.
✅ 7. `git apply --reverse .refactor/refactor.patch` cleanly restores original codebase state.
✅ 8. Second run on already-renamed codebase returns `{status: "no_op"}` without modifying any file.
✅ 9. `RefactorCIGate.check()` exits with code 1 and prints the stale file path if any old-name reference remains post-apply.
✅ 10. Tool execution time < 5s for a 100-file project (measured by T-05 benchmark).

---

## 15. Implementation Checklist

### 15.1 Core refactor engine

- [ ] Create `app/tools/refactor/__init__.py` exporting `RefactorEngine`, `DryRunReport`, `RefactorResult`
- [ ] Implement `RefactorEngine.walk(project_dir)` to discover all `.py` files recursively including `tests/`
- [ ] Implement `RefactorEngine.dry_run()` operating on in-memory `dict[str, str]` only
- [ ] Implement `RefactorEngine.run(apply=True)` calling `dry_run()` then `_emit_patch()`
- [ ] Implement `CollisionChecker.check(module, new_name)` raising `RefactorConflictError` on collision
- [ ] Implement early return `{status: "no_op"}` when `new_name` exists and `old_name` is absent
- [ ] Implement `RefactorEngine._emit_patch()` calling `generate_patch` then `validate_patch`
- [ ] Ensure `include_tests=False` flag skips `tests/` directory in walk

### 15.2 libcst AST transformer

- [ ] Create `app/tools/refactor/ast_transformer.py` with `FieldRenameTransformer`
- [ ] Implement `leave_AnnAssign` to rename field in model class body only (scoped to target class)
- [ ] Implement `leave_Attribute` to rename attribute access (`user.email` → `user.email_address`)
- [ ] Implement `leave_Arg` to rename keyword arguments (`User(email=...)`)
- [ ] Implement `leave_Name` to rename bare name references inside target class body
- [ ] Create `ModelRenameTransformer` for class name and import renames
- [ ] Create `SchemaAliasInjector` to inject `Field(alias=old_name)` and `populate_by_name=True`
- [ ] Verify round-trip comment preservation with unit test T-06

### 15.3 Reference scanner

- [ ] Create `app/tools/refactor/reference_scanner.py` with `RawSQLScanner`
- [ ] Implement `RawSQLScanner.scan(file_content, old_name)` detecting `old_name` in `op.execute(...)` strings
- [ ] Create `DynamicAccessScanner` detecting `getattr(obj, "old_name")` patterns
- [ ] Collect results into `patch_notes["manual_review"]` and `patch_notes["dynamic_access"]`
- [ ] Write scanner results to `.refactor/patch_notes.json` alongside the patch
- [ ] Add `ImportGraphAnalyzer` to detect circular imports before generating patch
- [ ] Ensure scanners return structured results: `{file: str, line: int, snippet: str}`

### 15.4 Patch generator

- [ ] Create `app/tools/refactor/patch_generator.py` with `generate_patch(diffs, patch_path)`
- [ ] Implement `generate_patch` using `difflib.unified_diff` with correct `fromfile`/`tofile` paths
- [ ] Implement `validate_patch(patch_path, project_dir)` calling `git apply --check`
- [ ] Raise `RuntimeError` with actionable message on validation failure
- [ ] Ensure patch directory `.refactor/` is created if absent
- [ ] Write `patch_notes.json` alongside patch file
- [ ] Test round-trip: apply + reverse = original (T-15)

### 15.5 Migration generator

- [ ] Create `app/tools/refactor/migration_generator.py` with `generate_rename_migration`
- [ ] Generate `0044_phase1.py` with `add_column` (nullable) + batched backfill + `alter_column` (NOT NULL)
- [ ] Generate `0044_phase2.py` with `drop_column` (correct `down_revision` chain)
- [ ] Implement `generate_change_type_migration` for `change_type` operation
- [ ] Implement `generate_rename_model_migration` with `op.rename_table`
- [ ] Ensure phase2 `downgrade()` re-adds old column from new column data
- [ ] Validate generated migration files parse as valid Python before writing

### 15.6 CI gate

- [ ] Create `app/tools/refactor/ci_gate.py` with `RefactorCIGate`
- [ ] Implement `RefactorCIGate.check(project_dir, old_name, new_name)` scanning all `.py` files
- [ ] Exit code 1 with file path + line number if old name found in any attribute access or annotation
- [ ] Exit code 0 and `{status: "clean"}` if no references found
- [ ] Add Makefile target `refactor-ci-gate` that runs the gate
- [ ] Integrate with `scripts/run_ci_checks.sh` pipeline

### 15.7 Operation: `rename_field`

- [ ] Parse `target` dotted path (`app.models.User.email`) into `(module_path, class_name, field_name)`
- [ ] Apply `FieldRenameTransformer` to model file first; verify `reference_count >= 1`
- [ ] Apply `SchemaAliasInjector` to all schemas that have an attribute matching `old_name`
- [ ] Apply `FieldRenameTransformer` to all CRUD files, route handlers, and test files
- [ ] Run `RawSQLScanner` and `DynamicAccessScanner` on all files
- [ ] Generate migration if `generate_migration=True`
- [ ] Generate patch; validate; write to `.refactor/refactor.patch`

### 15.8 Operation: `rename_model`

- [ ] Rename class definition with `ModelRenameTransformer` in model file
- [ ] Rename model file (`user_profile.py` → `profile.py`) included in patch
- [ ] Update all `import` statements using `leave_ImportFrom` transformer
- [ ] Update FK string literals (`"user_profiles.id"` → `"profiles.id"`)
- [ ] Update `relationship("UserProfile")` string args
- [ ] Update `__init__.py` re-exports
- [ ] Generate `op.rename_table` migration

### 15.9 Operation: `change_type`

- [ ] Parse `new_name` as SQLAlchemy type string: `String(255)`, `BigInteger`, `Enum(...)`
- [ ] Update `mapped_column(...)` type argument in model
- [ ] Update Pydantic schema validator constraints (e.g. `max_length`)
- [ ] Detect and block narrowing operations unless `--force-narrow` passed
- [ ] Generate appropriate migration: `op.alter_column(type_=...)` for widening; enum value addition for enum extend
- [ ] Validate new type is compatible with existing data if possible

### 15.10 Operation: `split_model`

- [ ] Parse `new_name` as `NewModel:field1,field2,field3` (fields to split off)
- [ ] Create new model file with specified fields
- [ ] Add FK from original model to new model
- [ ] Generate migration: create new table, backfill, add FK, remove fields from original
- [ ] Update all schemas to reference new model where appropriate
- [ ] Update all CRUD functions to handle new model

### 15.11 Dry-run and output

- [ ] Implement `DryRunReport` dataclass with `affected_files`, `reference_counts`, `patch_preview`, `manual_review`, `dynamic_access`
- [ ] Print formatted dry-run report to stdout
- [ ] Write `dry_run_report.json` to `.refactor/` alongside patch
- [ ] Show total file count, total reference count, and estimated migration lines
- [ ] Flag any `change_type` narrowing risk in dry-run output
- [ ] List manual_review items with actionable instructions

### 15.12 Testing

- [ ] Create `tests/test_refactor_model.py` with ≥ 30 test functions (CC-07)
- [ ] Cover all six AST transformer types (field, model, kwarg, attribute, import, annotation)
- [ ] Cover comment preservation with round-trip test (T-06)
- [ ] Cover patch generation, application, and reverse (T-13..T-15)
- [ ] Cover all 5 CI gate tests (T-19..T-24)
- [ ] Cover idempotency (T-25), scanner outputs (T-26..T-27), and per-operation edge cases
- [ ] Add benchmark test measuring execution time for 100-file project (T-05)

### 15.13 Documentation and registration

- [ ] Update `KNOWLEDGE.md` with `fastapi_refactor_model` entry: signature, operations, invariants
- [ ] Update `manifest.yaml` with tool entry: name, category, complexity, dependencies
- [ ] Update `SKILL.md` with TOOL-044 in the EVOLVE section
- [ ] Add Makefile targets: `refactor-dry-run`, `refactor-apply`, `refactor-ci-gate`, `refactor-rollback`
- [ ] Register `fastapi_refactor_model` in `mcp_server.py` under the `EVOLVE` domain
- [ ] Write usage examples in `docs/tools/TOOL-044-refactor-model.md`
- [ ] Add CI hook in `scripts/run_ci_checks.sh` to run `refactor-ci-gate` after any model change

---

## 16. Documentation Output

```json
{
  "status": "success",
  "files_created": [
    "app/tools/refactor/__init__.py",
    "app/tools/refactor/refactor_engine.py",
    "app/tools/refactor/ast_transformer.py",
    "app/tools/refactor/reference_scanner.py",
    "app/tools/refactor/patch_generator.py",
    "app/tools/refactor/migration_generator.py",
    "app/tools/refactor/ci_gate.py",
    "tests/test_refactor_model.py",
    ".refactor/refactor.patch",
    ".refactor/patch_notes.json",
    "alembic/versions/0044_phase1_rename_email_to_email_address.py",
    "alembic/versions/0044_phase2_drop_old_email_column.py"
  ],
  "files_modified": [
    "app/models/user.py",
    "app/schemas/user.py",
    "app/crud/user.py",
    "app/api/endpoints/users.py",
    "tests/test_users.py",
    "tests/conftest.py",
    "Makefile",
    "mcp_server.py",
    "KNOWLEDGE.md",
    "manifest.yaml"
  ],
  "next_steps": [
    "Review .refactor/refactor.patch with `git diff --stat` to confirm blast radius",
    "Apply the patch with `git apply .refactor/refactor.patch` after review",
    "Run `alembic upgrade 0044_phase1` to add email_address column and backfill",
    "Deploy new application code; run dual-read window (both columns live)",
    "After confirming all instances use email_address, run `alembic upgrade 0044_phase2` to drop old email column",
    "Run `make refactor-ci-gate old_name=email new_name=email_address` to confirm zero stale references",
    "Remove Field(alias='email') from schemas after all consumers migrated to email_address"
  ],
  "warnings": [
    "Dynamic getattr references to 'email' detected in app/services/notification.py:47 — manual update required (see .refactor/patch_notes.json)",
    "Raw SQL string 'SELECT email FROM users' detected in alembic/versions/0010_legacy.py:23 — manual update required before running phase 2",
    "Ensure all running application instances are updated before running phase 2 migration (drop old column) to avoid OperationalError"
  ],
  "notes": [
    "Patch validated successfully via `git apply --check` — safe to apply",
    "Phase 1 migration backfills in 50k-row batches; estimated runtime on 5M rows: ~25s",
    "Phase 2 migration (drop old column) is safe only after dual-read window confirmed complete",
    "Field(alias='email') injected in UserBase, UserCreate, UserUpdate, UserPublic schemas for backward compatibility",
    "populate_by_name=True added to all affected schema model_config to allow both field name and alias",
    "Rollback: `git apply --reverse .refactor/refactor.patch` + `alembic downgrade -1` restores full original state"
  ],
  "metrics": {
    "files_created_count": 12,
    "files_modified_count": 10,
    "reference_count": 47,
    "patch_lines": 312,
    "migration_phases": 2,
    "estimated_backfill_runtime_5m_rows": "~25s",
    "tool_execution_time": "3.2s",
    "tests_added": 30
  }
}
```
