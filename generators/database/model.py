"""Generator for SQLAlchemy/SQLModel ORM models."""

from __future__ import annotations

import textwrap
from pathlib import Path

from generators._pluralize import pluralize

# Mapping from user-friendly type names to (python_type, sa_column) pairs.
_TYPE_MAP: dict[str, tuple[str, str]] = {
    "str": ("str", "String(255)"),
    "text": ("str", "Text"),
    "int": ("int", "Integer"),
    "float": ("float", "Float"),
    "bool": ("bool", "Boolean"),
    "Decimal": ("Decimal", "Numeric(precision=12, scale=2)"),
    "decimal": ("Decimal", "Numeric(precision=12, scale=2)"),
    "date": ("date", "Date"),
    "datetime": ("datetime", "DateTime(timezone=True)"),
    "EmailStr": ("EmailStr", "String(320)"),
    "email": ("EmailStr", "String(320)"),
    "url": ("str", "String(2083)"),
    "json": ("dict", "JSON"),
    "uuid": ("UUID", "Uuid"),
}


def generate_model(
    output_dir: str,
    name: str,
    fields: dict[str, str],
    with_timestamps: bool = True,
    with_soft_delete: bool = False,
    owner_field: str | None = None,
) -> dict:
    """Generate a SQLAlchemy ORM model file.

    Args:
        output_dir: Directory root (models/ subdir is created automatically).
        name: Model class name (PascalCase, e.g. ``Product``).
        fields: Mapping of field_name -> type string (see _TYPE_MAP keys).
        with_timestamps: Add created_at / updated_at columns.
        with_soft_delete: Add is_deleted / deleted_at columns.
        owner_field: If set, adds an ``owner_id`` UUID FK pointing to the
            given table name (e.g. ``"user"``).

    Returns:
        Dict with files_created and notes.
    """
    out = Path(output_dir) / "models"
    out.mkdir(parents=True, exist_ok=True)

    # --- Ensure models/base.py exists (shared DeclarativeBase) ---
    base_file = out / "base.py"
    if not base_file.exists():
        base_file.write_text(
            '"""Shared declarative base for all ORM models."""\n\n'
            "from sqlalchemy.orm import DeclarativeBase\n\n\n"
            "class Base(DeclarativeBase):\n"
            '    """Base class for all models."""\n\n'
            "    pass\n"
        )

    # Use English pluralizer (handles "category" -> "categories", not "categorys")
    table_name = pluralize(name.lower())
    class_name = name if name[0].isupper() else name.capitalize()

    # --- Detect FK fields (*_id auto-detection) ----------------------------
    # A field named like ``product_id`` becomes a ForeignKey to ``products.id``.
    # ``owner_id`` is handled separately via the owner_field parameter so we
    # skip it here to avoid double-generation.
    fk_fields: dict[str, str] = {}
    for field_name in fields:
        if (
            field_name.endswith("_id")
            and field_name != "id"
            and field_name != "owner_id"
        ):
            referenced_table = pluralize(field_name[:-3])
            fk_fields[field_name] = referenced_table

    # --- Detect CheckConstraint candidates (rating 1..5) -------------------
    has_rating_check = (
        fields.get("rating") == "int"
    )

    # --- Collect imports ---------------------------------------------------
    stdlib_imports: set[str] = {"uuid"}
    pydantic_imports: set[str] = set()
    sa_imports: set[str] = {"Mapped", "mapped_column"}
    sa_type_imports: set[str] = {"Uuid"}

    for _, type_hint in fields.items():
        entry = _TYPE_MAP.get(type_hint, ("str", "String(255)"))
        py_type, sa_col = entry
        if py_type == "Decimal":
            stdlib_imports.add("decimal")
        if py_type == "date":
            stdlib_imports.add("datetime")
        if py_type == "datetime":
            stdlib_imports.add("datetime")
        if py_type == "EmailStr":
            pydantic_imports.add("EmailStr")
        if py_type == "UUID":
            pass  # uuid already imported
        # Extract SA type name (e.g. "String(255)" -> "String")
        sa_type_name = sa_col.split("(")[0]
        sa_type_imports.add(sa_type_name)

    if with_timestamps:
        stdlib_imports.add("datetime")
        sa_type_imports.update({"DateTime"})
        sa_type_imports.add("func")
    if with_soft_delete:
        stdlib_imports.add("datetime")
        sa_type_imports.update({"Boolean", "DateTime"})
    if owner_field or fk_fields:
        sa_type_imports.add("ForeignKey")
        sa_type_imports.add("Uuid")
    if has_rating_check:
        sa_type_imports.add("CheckConstraint")

    # --- Build import block -----------------------------------------------
    import_lines: list[str] = []
    import_lines.append('"""ORM model for %s."""' % class_name)
    import_lines.append("")
    import_lines.append("from __future__ import annotations")
    import_lines.append("")

    # stdlib
    if "datetime" in stdlib_imports:
        import_lines.append("from datetime import datetime, timezone")
    if "decimal" in stdlib_imports:
        import_lines.append("from decimal import Decimal")
    if "uuid" in stdlib_imports:
        import_lines.append("import uuid")
    import_lines.append("")

    # pydantic (optional)
    if pydantic_imports:
        import_lines.append(f"from pydantic import {', '.join(sorted(pydantic_imports))}")
        import_lines.append("")

    # sqlalchemy
    sa_sorted = sorted(sa_imports)
    sa_type_sorted = sorted(sa_type_imports)
    import_lines.append(f"from sqlalchemy import {', '.join(sa_type_sorted)}")
    import_lines.append(f"from sqlalchemy.orm import {', '.join(sa_sorted)}")
    import_lines.append("")
    import_lines.append("from app.models.base import Base")
    import_lines.append("")
    import_lines.append("")

    # --- Model class ------------------------------------------------------
    class_lines: list[str] = []
    class_lines.append(f"class {class_name}(Base):")
    class_lines.append(f'    """{class_name} ORM model."""')
    class_lines.append("")
    class_lines.append(f'    __tablename__ = "{table_name}"')
    class_lines.append("")

    # Primary key
    class_lines.append(
        "    id: Mapped[uuid.UUID] = mapped_column("
        "Uuid, primary_key=True, default=uuid.uuid4"
        ")"
    )

    # User-defined fields
    for field_name, type_hint in fields.items():
        # FK fields (auto-detected *_id) — emit as ForeignKey column
        if field_name in fk_fields:
            referenced = fk_fields[field_name]
            class_lines.append(
                f"    {field_name}: Mapped[uuid.UUID] = mapped_column("
                f'Uuid, ForeignKey("{referenced}.id", ondelete="CASCADE"), '
                f"nullable=False, index=True)"
            )
            continue

        entry = _TYPE_MAP.get(type_hint, ("str", "String(255)"))
        py_type, sa_col = entry
        # Resolve display type
        display_type = py_type
        if py_type == "Decimal":
            display_type = "Decimal"
        elif py_type == "date":
            display_type = "datetime.date"
        elif py_type == "datetime":
            display_type = "datetime"
        elif py_type == "UUID":
            display_type = "uuid.UUID"
        class_lines.append(
            f"    {field_name}: Mapped[{display_type}] = mapped_column({sa_col})"
        )

    # Owner field
    if owner_field:
        class_lines.append("")
        class_lines.append(
            f'    owner_id: Mapped[uuid.UUID] = mapped_column('
            f'Uuid, ForeignKey("{pluralize(owner_field)}.id", ondelete="CASCADE")'
            f')'
        )

    # Timestamps
    if with_timestamps:
        class_lines.append("")
        class_lines.append(
            "    created_at: Mapped[datetime] = mapped_column("
            "DateTime(timezone=True), server_default=func.now()"
            ")"
        )
        class_lines.append(
            "    updated_at: Mapped[datetime | None] = mapped_column("
            "DateTime(timezone=True), onupdate=func.now(), default=None"
            ")"
        )

    # Soft delete
    if with_soft_delete:
        class_lines.append("")
        class_lines.append(
            "    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)"
        )
        class_lines.append(
            "    deleted_at: Mapped[datetime | None] = mapped_column("
            "DateTime(timezone=True), default=None"
            ")"
        )

    # --- __table_args__ for table-level constraints -----------------------
    table_args_entries: list[str] = []
    if has_rating_check:
        table_args_entries.append(
            'CheckConstraint("rating >= 1 AND rating <= 5", name="ck_rating_range")'
        )
    if table_args_entries:
        class_lines.append("")
        class_lines.append("    __table_args__ = (")
        for entry in table_args_entries:
            class_lines.append(f"        {entry},")
        class_lines.append("    )")

    # --- Assemble ---------------------------------------------------------
    full_content = "\n".join(import_lines + class_lines) + "\n"

    file_path = out / f"{name.lower()}.py"
    file_path.write_text(full_content)

    notes = [f"Generated models/{name.lower()}.py with {len(fields)} field(s)."]
    if with_timestamps:
        notes.append("Timestamps (created_at, updated_at) included.")
    if with_soft_delete:
        notes.append("Soft-delete columns (is_deleted, deleted_at) included.")
    if owner_field:
        notes.append(f"owner_id FK -> {pluralize(owner_field)}.id with CASCADE delete.")

    return {"files_created": [str(file_path)], "notes": notes}
