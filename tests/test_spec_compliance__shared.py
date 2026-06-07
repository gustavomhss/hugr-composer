"""Shared helpers for split spec-compliance tests.

For each of the 10 critical tools, we generate a minimal project into a
temp directory, run the tool, and then grep the generated files for patterns
that prove each Section-8 Invariant is implemented in the generated code.

Tests are intentionally coarse (string-search based) so they run fast and
stay maintenance-light.  Every assertion documents which invariant it checks.
"""

from __future__ import annotations

import shutil
import textwrap
import uuid
from pathlib import Path

import pytest

from adapt.contracts import ToolInput

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project(tmp_path: Path) -> Path:
    """Create a minimal FastAPI project scaffold in *tmp_path*.

    Produces just enough structure for every tool to find its target files:
    app/, app/models/item.py, app/crud/item.py, app/api/routes/item.py,
    app/schemas/item.py, app/main.py, alembic/versions/.
    """
    p = tmp_path / "proj"
    (p / "app" / "models").mkdir(parents=True)
    (p / "app" / "crud").mkdir(parents=True)
    (p / "app" / "schemas").mkdir(parents=True)
    (p / "app" / "api" / "routes").mkdir(parents=True)
    (p / "app" / "core").mkdir(parents=True)
    (p / "alembic" / "versions").mkdir(parents=True)
    (p / "requirements.txt").write_text("fastapi\nsqlalchemy\n")

    # Minimal base
    (p / "app" / "models" / "base.py").write_text(
        "from sqlalchemy.orm import DeclarativeBase\n\nclass Base(DeclarativeBase):\n    pass\n"
    )
    # A real model
    (p / "app" / "models" / "item.py").write_text(
        textwrap.dedent("""\
        from __future__ import annotations
        import uuid
        from sqlalchemy import String, Uuid
        from sqlalchemy.orm import Mapped, mapped_column
        from app.models.base import Base

        class Item(Base):
            __tablename__ = "items"
            id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
            title: Mapped[str] = mapped_column(String(255), nullable=False)
        """)
    )
    (p / "app" / "crud" / "item.py").write_text(
        textwrap.dedent("""\
        from __future__ import annotations
        from sqlalchemy.ext.asyncio import AsyncSession

        async def get(session: AsyncSession, item_id):
            pass
        """)
    )
    (p / "app" / "api" / "routes" / "item.py").write_text(
        textwrap.dedent("""\
        from __future__ import annotations
        from fastapi import APIRouter
        from app.api.deps import CurrentUser, SessionDep

        router = APIRouter()

        @router.get("/items/")
        async def list_items(session: SessionDep, current_user: CurrentUser):
            return []
        """)
    )
    (p / "app" / "api" / "deps.py").write_text(
        textwrap.dedent("""\
        from __future__ import annotations
        from typing import Annotated
        from fastapi import Depends
        from sqlalchemy.ext.asyncio import AsyncSession

        async def get_session():
            pass

        SessionDep = Annotated[AsyncSession, Depends(get_session)]
        CurrentUser = str
        CurrentSuperuser = str
        """)
    )
    (p / "app" / "schemas" / "item.py").write_text(
        textwrap.dedent("""\
        from __future__ import annotations
        from pydantic import BaseModel

        class ItemPublic(BaseModel):
            id: str
            title: str
        """)
    )
    (p / "app" / "main.py").write_text(
        textwrap.dedent("""\
        from __future__ import annotations
        from fastapi import FastAPI
        from app.core.logging import configure_logging

        app = FastAPI()
        """)
    )
    (p / "app" / "core" / "logging.py").write_text("def configure_logging(): pass\n")
    (p / "app" / "api" / "main.py").write_text(
        "from fastapi import APIRouter\napi_router = APIRouter()\n"
    )
    return p


def _read_tree(project: Path) -> str:
    """Return concatenated text of all .py files under *project*."""
    parts: list[str] = []
    for f in sorted(project.rglob("*.py")):
        try:
            parts.append(f.read_text(errors="ignore"))
        except OSError:
            pass
    return "\n".join(parts)
