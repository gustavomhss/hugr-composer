"""Generator for async CRUD operations (thin wrappers over CRUDBase)."""

from __future__ import annotations

MCP_TOOL = {
    'name': 'fastapi_data_generate_crud',
    'description': 'Generate CRUD layer (create/read/update/delete/list) with pagination and optional owner filtering.',
    'tags': ['database', 'generator'],
    'entry': 'generate_crud',
}

import textwrap
from pathlib import Path


def generate_crud(
    output_dir: str,
    model_name: str,
    with_owner_filter: bool = False,
    with_soft_delete: bool = False,
    unique_field: str | None = None,
) -> dict:
    """Generate ``crud/{model_name.lower()}.py`` as a thin wrapper over CRUDBase.

    The generated file instantiates ``CRUDBase[Model](Model)`` and
    re-exports the standard CRUD functions as module-level aliases.
    This keeps backwards compatibility with code that imports
    ``from app.crud.order import create`` while eliminating the
    ~200-line copy-paste each entity used to have.

    ``crud/base.py`` (generated once by ``generate_crud_base``) must
    exist before this generator runs.

    Args:
        output_dir: Directory root (``crud/`` subdir is created automatically).
        model_name: PascalCase model class name (e.g. ``Product``).
        with_owner_filter: Retained for API compatibility — ``CRUDBase.get_multi``
            already supports ``owner_id`` filtering, so this flag is a no-op
            (owner filtering is automatic when the model has an ``owner_id``
            column and a value is passed).
        with_soft_delete: Use soft-delete instead of hard-delete.  When true,
            this generator emits a custom ``delete`` that bypasses ``CRUDBase``.
        unique_field: If set, generates a ``get_by_{field}`` lookup function
            alongside the CRUDBase aliases.  Pass ``"email"`` for ``User`` to
            get ``get_by_email()``.

    Returns:
        Dict with files_created and notes.
    """
    out = Path(output_dir) / "crud"
    out.mkdir(parents=True, exist_ok=True)

    lower = model_name.lower()
    cls = model_name if model_name[0].isupper() else model_name.capitalize()

    # --- unique field lookup (e.g. get_by_email) ---
    unique_lookup = ""
    if unique_field:
        unique_lookup = textwrap.dedent(f"""

            async def get_by_{unique_field}(
                session: AsyncSession, *, {unique_field}: str
            ) -> {cls} | None:
                \"\"\"Fetch a single {cls} by {unique_field}.\"\"\"
                stmt = select({cls}).where({cls}.{unique_field} == {unique_field})
                result = await session.execute(stmt)
                return result.scalar_one_or_none()
        """)
        # Dedent the function to module level (textwrap.dedent strips
        # the leading spaces from all lines).
        unique_lookup = unique_lookup.lstrip("\n")

    # --- soft-delete override ---
    soft_delete_block = ""
    if with_soft_delete:
        soft_delete_block = textwrap.dedent(f"""

            async def delete(
                session: AsyncSession, id: uuid.UUID
            ) -> {cls} | None:
                \"\"\"Soft-delete a {cls} by primary key.\"\"\"
                obj = await crud.get(session, id)
                if obj is None:
                    return None
                obj.is_deleted = True
                obj.deleted_at = datetime.now(timezone.utc)
                await session.flush()
                return obj
        """).lstrip("\n")

    # Build the template WITHOUT extras, dedent it cleanly,
    # then prepend the extra imports as plain text at the right spot.
    content = textwrap.dedent(f'''\
        """Async CRUD operations for {cls} (thin wrapper over CRUDBase)."""

        from __future__ import annotations

        from app.crud.base import CRUDBase
        from app.models.{lower} import {cls}


        crud = CRUDBase[{cls}]({cls})

        # Backwards-compatible module-level aliases so callers can use
        #   ``from app.crud.{lower} import create, get, get_multi, update, delete``
        create = crud.create
        get = crud.get
        get_multi = crud.get_multi
        update = crud.update
        delete = crud.delete
    ''')

    # Insert any extra imports right before "from app.crud.base import CRUDBase"
    extra_imports: list[str] = []
    if with_soft_delete:
        extra_imports.append("import uuid")
        extra_imports.append("from datetime import datetime, timezone")
    if unique_field or with_soft_delete:
        extra_imports.append("from sqlalchemy.ext.asyncio import AsyncSession")
    if unique_field:
        extra_imports.append("from sqlalchemy import select")

    if extra_imports:
        extras_block = "\n".join(extra_imports) + "\n"
        content = content.replace(
            "from app.crud.base import CRUDBase",
            extras_block + "from app.crud.base import CRUDBase",
        )

    if unique_lookup:
        content += "\n\n" + unique_lookup.rstrip() + "\n"

    if soft_delete_block:
        content += "\n\n" + soft_delete_block.rstrip() + "\n"

    file_path = out / f"{lower}.py"
    file_path.write_text(content)

    notes = [
        f"Generated crud/{lower}.py as a thin wrapper over CRUDBase[{cls}].",
    ]
    if unique_field:
        notes.append(f"Added get_by_{unique_field} lookup function.")
    if with_soft_delete:
        notes.append("delete() overridden for soft-delete (sets is_deleted=True, deleted_at).")
    if with_owner_filter:
        notes.append(
            "owner_filter param accepted — CRUDBase.get_multi natively supports owner_id."
        )

    return {"files_created": [str(file_path)], "notes": notes}
