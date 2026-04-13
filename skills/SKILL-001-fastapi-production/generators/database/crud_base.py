"""Generator for a shared ``CRUDBase`` generic used by all entity CRUDs.

Writes ``crud/base.py`` with a generic, reusable ``CRUDBase`` class so
that each entity-specific CRUD module shrinks from ~200 lines of
copy-paste to a few lines that instantiate the base::

    from app.crud.base import CRUDBase
    from app.models.order import Order

    crud = CRUDBase[Order](Order)
    create = crud.create
    get = crud.get
    get_multi = crud.get_multi
    update = crud.update
    delete = crud.delete

Owner filtering is built in; entity modules that need a unique lookup
(e.g. ``get_by_email`` for User) keep that function alongside the
base alias.
"""

from __future__ import annotations

import textwrap
from pathlib import Path


def generate_crud_base(output_dir: str) -> dict:
    """Write ``crud/base.py`` with the generic CRUDBase class.

    This should be called ONCE before any entity CRUD is generated.

    Args:
        output_dir: The app package directory (usually ``out/app``).

    Returns:
        Dict with ``files_created`` and ``notes``.
    """
    out = Path(output_dir) / "crud"
    out.mkdir(parents=True, exist_ok=True)

    content = textwrap.dedent('''\
        """Shared CRUD base class used by all entity CRUD modules.

        Provides the standard async CRUD operations (create, get,
        get_multi, update, delete) as methods on a generic ``CRUDBase``
        class.  Entity modules create a module-level instance and
        re-export its methods as module-level functions so existing
        imports (``from app.crud.order import create``) keep working.
        """

        from __future__ import annotations

        import uuid
        from typing import Generic, TypeVar

        from sqlalchemy import func, select
        from sqlalchemy.ext.asyncio import AsyncSession

        ModelType = TypeVar("ModelType")


        class CRUDBase(Generic[ModelType]):
            """Generic async CRUD operations for any SQLAlchemy model."""

            def __init__(self, model: type[ModelType]) -> None:
                self.model = model

            async def create(
                self,
                session: AsyncSession,
                *,
                obj_in: dict,
            ) -> ModelType:
                """Insert a new row and return the created instance."""
                db_obj = self.model(**obj_in)
                session.add(db_obj)
                await session.flush()
                return db_obj

            async def get(
                self,
                session: AsyncSession,
                id: uuid.UUID,
            ) -> ModelType | None:
                """Fetch a single row by primary key."""
                stmt = select(self.model).where(self.model.id == id)
                result = await session.execute(stmt)
                return result.scalar_one_or_none()

            async def get_multi(
                self,
                session: AsyncSession,
                *,
                skip: int = 0,
                limit: int = 20,
                owner_id: uuid.UUID | None = None,
            ) -> dict:
                """Fetch a paginated list.

                Returns a dict with ``data`` (list of model instances)
                and ``count`` (total matching rows).  If *owner_id* is
                provided and the model has an ``owner_id`` column,
                results are filtered to that owner.
                """
                stmt = select(self.model)
                if owner_id is not None and hasattr(self.model, "owner_id"):
                    stmt = stmt.where(self.model.owner_id == owner_id)

                count_stmt = select(func.count()).select_from(stmt.subquery())
                total = (await session.execute(count_stmt)).scalar_one()

                stmt = (
                    stmt.order_by(self.model.created_at.desc())
                    .offset(skip)
                    .limit(limit)
                )
                result = await session.execute(stmt)
                return {"data": list(result.scalars().all()), "count": total}

            async def update(
                self,
                session: AsyncSession,
                *,
                db_obj: ModelType,
                obj_in: dict,
            ) -> ModelType:
                """Partially update an existing row.

                Only keys present in *obj_in* are modified — pass
                ``body.model_dump(exclude_unset=True)`` from the caller.
                """
                for field, value in obj_in.items():
                    setattr(db_obj, field, value)
                session.add(db_obj)
                await session.flush()
                return db_obj

            async def delete(
                self,
                session: AsyncSession,
                id: uuid.UUID,
            ) -> ModelType | None:
                """Delete a row by primary key.

                Returns the deleted instance, or ``None`` if it did not
                exist.
                """
                obj = await self.get(session, id)
                if obj is None:
                    return None
                await session.delete(obj)
                await session.flush()
                return obj
    ''')

    file_path = out / "base.py"
    file_path.write_text(content)

    # Ensure crud/__init__.py exists so imports work
    init_path = out / "__init__.py"
    if not init_path.exists():
        init_path.write_text("")

    return {
        "files_created": [str(file_path)],
        "notes": [
            "Generated crud/base.py with generic CRUDBase[ModelType].",
            "Entity CRUD modules can now re-export create/get/get_multi/update/delete "
            "from a single CRUDBase instance instead of copy-pasting implementations.",
        ],
    }
