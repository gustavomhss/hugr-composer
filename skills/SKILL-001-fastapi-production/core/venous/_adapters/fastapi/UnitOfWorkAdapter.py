"""FastAPI adapter over the `UnitOfWork` primitive.

Exposes `get_uow` — a FastAPI dependency that yields a fresh
`InMemoryUnitOfWork` per request, committing on clean exit and rolling
back on exception. Callers can supply their own `flush_fn` (e.g.
SQLAlchemy session flush) via `make_dependency(flush_fn)`.

Usage::

    from fastapi import Depends
    from core.venous._adapters.fastapi.UnitOfWorkAdapter import get_uow

    @app.post("/items")
    async def create(uow=Depends(get_uow)): ...
"""

from __future__ import annotations

from typing import Callable, Iterator

from core.venous.data.UnitOfWork.UnitOfWork import InMemoryUnitOfWork

FlushFn = Callable[[list[object], list[object], list[object]], None]


def make_dependency(flush_fn: FlushFn | None = None) -> Callable[[], Iterator[InMemoryUnitOfWork]]:
    """Return a FastAPI generator-dependency that yields a fresh UnitOfWork."""

    def _dep() -> Iterator[InMemoryUnitOfWork]:
        uow = InMemoryUnitOfWork(flush_fn=flush_fn)
        try:
            with uow:
                yield uow
                uow.commit()
        except BaseException:
            uow.rollback()
            raise

    return _dep


get_uow = make_dependency()
"""Default dependency — no-op flush; swap via make_dependency(sql_flush)."""
