"""Generator for baseline Alembic migration (0002_baseline_schema.py).

Produces a ready-to-run baseline migration that creates all tables for
the current model set.  Without this, a freshly generated project has
no way to bootstrap its schema (the old `Base.metadata.create_all` path
was removed from initial_data.py because Alembic is the source of truth).

Chains off ``0001_initial`` (the no-op chain root emitted by
``generators.database.alembic.generate_alembic``).  See R6-O4-A1.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from generators._pluralize import pluralize

# Map user-friendly field types -> (python import, sa column expression, nullable default).
# This mirrors generators/database/model.py::_TYPE_MAP but emits the sa.* form used
# inside migration scripts (which must be literal sqlalchemy expressions, not ORM).
_SA_TYPE_MAP: dict[str, str] = {
    "str": "sa.String(length=255)",
    "text": "sa.Text()",
    "int": "sa.Integer()",
    "float": "sa.Float()",
    "bool": "sa.Boolean()",
    "Decimal": "sa.Numeric(precision=12, scale=2)",
    "decimal": "sa.Numeric(precision=12, scale=2)",
    "date": "sa.Date()",
    "datetime": "sa.DateTime(timezone=True)",
    "EmailStr": "sa.String(length=320)",
    "email": "sa.String(length=320)",
    "url": "sa.String(length=2083)",
    "json": "sa.JSON()",
    "uuid": "sa.Uuid()",
}


def _resolve_fk_model_migration(stem: str, known_models: dict[str, dict] | None) -> str | None:
    """Return the matching model name for a *_id field stem, or None.

    Mirrors generators/database/model.py::_resolve_fk_model — kept as a local
    copy so each module remains importable independently.
    """
    if not known_models:
        return None
    normalised = stem.lower().replace("_", "")
    for model_name in known_models:
        if model_name.lower().replace("_", "") == normalised:
            return model_name
    return None


def _column_for(
    field_name: str,
    field_type: str,
    *,
    table_name: str = "",
    known_models: dict[str, dict] | None = None,
) -> str:
    """Render a single ``sa.Column(...)`` entry for a migration upgrade block."""
    # Foreign key: only emit ForeignKey when the stem matches a real model in
    # known_models.  Without this guard, a plain ``tracking_id: "str"`` field
    # would produce a FK to a non-existent ``trackings`` table and crash
    # ``Base.metadata.create_all`` with NoReferencedTableError.
    if field_name.endswith("_id") and field_name != "id":
        stem = field_name[:-3]
        matched_model = _resolve_fk_model_migration(stem, known_models)
        if matched_model is not None:
            # Derive table name identically to generate_model's __tablename__
            referenced = pluralize(matched_model.lower())
            ondelete = "CASCADE"
            return (
                f'        sa.Column("{field_name}", sa.Uuid(), '
                f'sa.ForeignKey("{referenced}.id", ondelete="{ondelete}"), '
                f"nullable=False),"
            )
        # else: fall through and emit a normal typed column

    sa_type = _SA_TYPE_MAP.get(field_type, "sa.String(length=255)")

    # Nullable overrides — keep in sync with the orchestrator post-generation
    # patches applied to the User model (full_name is optional).
    nullable = "False"
    if table_name == "users" and field_name == "full_name":
        nullable = "True"

    return f'        sa.Column("{field_name}", {sa_type}, nullable={nullable}),'


def _table_args_for(name: str, fields: dict[str, str]) -> list[str]:
    """Return extra table-level args (unique constraints, check constraints)."""
    extras: list[str] = []
    if name == "users":
        extras.append('        sa.UniqueConstraint("email", name="uq_users_email"),')
    # CheckConstraint for rating field in range 1..5
    for field_name, field_type in fields.items():
        if field_name == "rating" and field_type == "int":
            extras.append(
                '        sa.CheckConstraint("rating >= 1 AND rating <= 5", name="ck_rating_range"),'
            )
    return extras


def _table_block(
    table_name: str,
    model_name: str,
    fields: dict[str, str],
    *,
    with_owner: bool,
    with_timestamps: bool = True,
    known_models: dict[str, dict] | None = None,
) -> str:
    """Render an ``op.create_table(...)`` block for a single model."""
    lines: list[str] = []
    lines.append("    op.create_table(")
    lines.append(f'        "{table_name}",')
    lines.append('        sa.Column("id", sa.Uuid(), nullable=False),')

    for field_name, field_type in fields.items():
        if field_name == "id":
            continue
        lines.append(
            _column_for(
                field_name,
                field_type,
                table_name=table_name,
                known_models=known_models,
            )
        )

    if with_owner:
        lines.append(
            '        sa.Column("owner_id", sa.Uuid(), '
            'sa.ForeignKey("users.id", ondelete="CASCADE"), '
            "nullable=False),"
        )

    if with_timestamps:
        lines.append(
            '        sa.Column("created_at", sa.DateTime(timezone=True), '
            "server_default=sa.func.now(), nullable=False),"
        )
        lines.append('        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),')

    lines.append('        sa.PrimaryKeyConstraint("id"),')
    lines.extend(_table_args_for(table_name, fields))
    lines.append("    )")

    # Index on owner_id for efficient ownership filtering
    if with_owner:
        lines.append(
            f'    op.create_index("ix_{table_name}_owner_id", "{table_name}", ["owner_id"])'
        )

    # Index on FK *_id columns (except owner_id which is already indexed)
    for field_name in fields:
        if field_name.endswith("_id") and field_name != "id":
            lines.append(
                f"    op.create_index("
                f'"ix_{table_name}_{field_name}", '
                f'"{table_name}", ["{field_name}"])'
            )

    return "\n".join(lines)


def generate_baseline_migration(  # noqa: C901 — table/column emit loop with per-field branches (PK, FK, index, type).
    output_dir: str,
    models: dict[str, dict[str, str]] | None = None,
    owner_models: dict[str, str] | None = None,
    with_auth: bool = True,
) -> dict:
    """Generate alembic/versions/0002_baseline_schema.py.

    Args:
        output_dir: Project root (the directory that contains ``alembic/``).
        models: Mapping of model name -> field dict, same shape passed to
            the orchestrator.
        owner_models: Mapping of model name -> owner kind (currently only
            ``"user"`` is supported).  Adds an ``owner_id`` FK to users.
        with_auth: Whether the users table should be created.

    Returns:
        Dict with files_created and notes.
    """
    out = Path(output_dir)
    versions_dir = out / "alembic" / "versions"
    versions_dir.mkdir(parents=True, exist_ok=True)

    models = models or {}
    owner_models = owner_models or {}

    upgrade_blocks: list[str] = []
    # Ordered list of tables (creation order respects FK deps):
    # 1. users (referenced by owner_id FKs)
    # 2. Products / standalone tables (no FK to other user-land tables)
    # 3. Tables with owner_id and/or *_id FKs pointing at the above
    tables_in_order: list[tuple[str, str, dict[str, str], bool]] = []

    if with_auth:
        tables_in_order.append(
            (
                "users",
                "User",
                {
                    "email": "EmailStr",
                    "full_name": "str",
                    "hashed_password": "str",
                    "is_active": "bool",
                    "is_superuser": "bool",
                },
                False,
            )
        )

    # Separate models by whether they have FK dependencies on other domain models
    # to ensure creation order is topologically valid.  Use the same normalised
    # matching as _resolve_fk_model_migration so multi-word models are handled
    # correctly (``vaccine_lot_id`` → ``VaccineLot``, not ``Vaccine_lot``).
    independent: list[tuple[str, dict[str, str], bool]] = []
    dependent: list[tuple[str, dict[str, str], bool]] = []
    for model_name, fields in models.items():
        has_domain_fk = any(
            fname.endswith("_id")
            and fname != "id"
            and _resolve_fk_model_migration(fname[:-3], models) is not None
            for fname in fields
        )
        owner = model_name in owner_models
        entry = (model_name, fields, owner)
        if has_domain_fk:
            dependent.append(entry)
        else:
            independent.append(entry)

    for model_name, fields, owner in independent:
        tables_in_order.append((pluralize(model_name.lower()), model_name, fields, owner))
    for model_name, fields, owner in dependent:
        tables_in_order.append((pluralize(model_name.lower()), model_name, fields, owner))

    for table_name, model_name, fields, owner in tables_in_order:
        upgrade_blocks.append(
            _table_block(table_name, model_name, fields, with_owner=owner, known_models=models)
        )

    upgrade_body = "\n\n".join(upgrade_blocks) if upgrade_blocks else "    pass"

    # Drop tables in reverse creation order
    downgrade_lines: list[str] = []
    for table_name, _, fields, owner in reversed(tables_in_order):
        # Drop indices first
        for field_name in fields:
            if field_name.endswith("_id") and field_name != "id":
                downgrade_lines.append(
                    f'    op.drop_index("ix_{table_name}_{field_name}", table_name="{table_name}")'
                )
        if owner:
            downgrade_lines.append(
                f'    op.drop_index("ix_{table_name}_owner_id", table_name="{table_name}")'
            )
        downgrade_lines.append(f'    op.drop_table("{table_name}")')

    downgrade_body = "\n".join(downgrade_lines) if downgrade_lines else "    pass"

    content = textwrap.dedent('''\
        """baseline schema

        Revision ID: 0002_baseline_schema
        Revises: 0001_initial
        Create Date: auto-generated baseline

        Chains off ``0001_initial`` (the no-op chain root emitted by
        ``generators.database.alembic.generate_alembic``).  Closes R6-O4-A1 —
        every extend tool falls back to ``down_revision = "0001_initial"``,
        which must always exist on disk.
        """

        from __future__ import annotations

        from typing import Sequence, Union

        import sqlalchemy as sa
        from alembic import op


        # revision identifiers, used by Alembic.
        revision: str = "0002_baseline_schema"
        down_revision: Union[str, None] = "0001_initial"
        branch_labels: Union[str, Sequence[str], None] = None
        depends_on: Union[str, Sequence[str], None] = None


        def upgrade() -> None:
        {upgrade_body}


        def downgrade() -> None:
        {downgrade_body}
    ''').format(upgrade_body=upgrade_body, downgrade_body=downgrade_body)

    file_path = versions_dir / "0002_baseline_schema.py"
    file_path.write_text(content)

    return {
        "files_created": [str(file_path)],
        "notes": [
            f"Baseline migration 0002_baseline_schema created for {len(tables_in_order)} table(s).",
            "Chains off 0001_initial (no-op chain root from generate_alembic).",
            "FKs auto-detected from *_id field names; users.email has UNIQUE constraint.",
            "Tables created in FK-safe order (users first, then independents, then dependents).",
        ],
    }
