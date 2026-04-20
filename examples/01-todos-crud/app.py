"""Todos CRUD — self-contained illustration of owner-scoped access + keyset pagination.

The production version of this app lives in the generated scaffold produced by
`fastapi_generate_project` + the add_* tools listed in README.md. This file is
a single-process in-memory approximation sufficient to demonstrate the
invariants that matter:

- Owner-scoped reads/writes return 404 (not 403) on cross-owner access.
- Keyset pagination never duplicates or skips under concurrent inserts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import count
from typing import Iterable


@dataclass(frozen=True)
class Todo:
    id: int
    owner_id: str
    title: str
    done: bool
    created_at: datetime


class TodoRepository:
    """In-memory stand-in for the `Repository` primitive.

    The production emitter wires `fastapi_add_crud_resource` into the
    `Repository` primitive under `core/venous/data.persistence/`. Behaviour
    here mirrors the contract: **no cross-owner reads leak existence**.
    """

    def __init__(self) -> None:
        self._rows: dict[int, Todo] = {}
        self._next_id = count(1)

    def create(self, owner_id: str, title: str) -> Todo:
        tid = next(self._next_id)
        todo = Todo(
            id=tid, owner_id=owner_id, title=title, done=False,
            created_at=datetime.now(tz=timezone.utc),
        )
        self._rows[tid] = todo
        return todo

    def get_for(self, owner_id: str, todo_id: int) -> Todo | None:
        row = self._rows.get(todo_id)
        if row is None or row.owner_id != owner_id:
            return None
        return row

    def patch_for(
        self, owner_id: str, todo_id: int, *, done: bool | None = None,
    ) -> Todo | None:
        row = self.get_for(owner_id, todo_id)
        if row is None:
            return None
        updated = Todo(
            id=row.id, owner_id=row.owner_id, title=row.title,
            done=row.done if done is None else done, created_at=row.created_at,
        )
        self._rows[row.id] = updated
        return updated

    def delete_for(self, owner_id: str, todo_id: int) -> bool:
        if self.get_for(owner_id, todo_id) is None:
            return False
        del self._rows[todo_id]
        return True

    def list_page(
        self,
        owner_id: str,
        *,
        cursor: tuple[datetime, int] | None,
        size: int,
    ) -> tuple[list[Todo], tuple[datetime, int] | None]:
        """Keyset page over ``(created_at, id)``.

        Returns the page and a cursor for the next page, or None if end.
        """
        owned: Iterable[Todo] = (t for t in self._rows.values() if t.owner_id == owner_id)
        ordered = sorted(owned, key=lambda t: (t.created_at, t.id))
        if cursor is not None:
            ordered = [t for t in ordered if (t.created_at, t.id) > cursor]
        page = ordered[:size]
        next_cursor = (page[-1].created_at, page[-1].id) if len(page) == size else None
        return page, next_cursor


def owner_scoped_patch(repo: TodoRepository, owner: str, todo_id: int, done: bool) -> tuple[int, Todo | None]:
    """Return (status_code, row). 404 when cross-owner — *never* 403.

    Leaking existence via 403 enables enumeration; this is the anti-pattern
    the `fastapi_add_crud_resource` generator guards against.
    """
    row = repo.patch_for(owner, todo_id, done=done)
    if row is None:
        return 404, None
    return 200, row
