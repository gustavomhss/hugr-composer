from __future__ import annotations
from fastapi import Depends
from fastapi import HTTPException
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession


@router.post('/{content_type}/{content_id}/draft', response_model=VersionRead, status_code=status.HTTP_201_CREATED)
async def create_draft(content_type: str, content_id: str, body: VersionCreate, session: AsyncSession=Depends(_get_session), service: VersioningService=Depends(_get_service)) -> VersionRead:
    """Create a new draft version for a content item.

    Args:
        content_type: Lowercase content type name.
        content_id: Opaque string ID of the content item.
        body: VersionCreate with data and optional author_id.
        session: Injected async DB session.
        service: VersioningService instance.

    Returns:
        The newly created draft as VersionRead.

    Raises:
        HTTPException 422: If max_drafts limit is reached.
    """
    try:
        version = await service.create_draft(session, content_id=content_id, content_type=content_type, data=body.data, author_id=body.author_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={'detail': str(exc)}) from exc
    return VersionRead.model_validate(version)
