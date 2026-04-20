from __future__ import annotations
from fastapi import HTTPException
from fastapi import status


@router.post('/', response_model=ToggleRead, status_code=status.HTTP_201_CREATED)
async def create_toggle(toggle_in: ToggleCreate, session: SessionDep, current_user: CurrentSuperuser) -> ToggleRead:
    """Create a new feature toggle. Superuser only.

    Args:
        toggle_in: Validated toggle create payload.
        session: Injected async DB session.
        current_user: Must be a superuser.

    Raises:
        HTTPException: 409 if toggle name already exists.
    """
    from app.crud.feature_toggle import get_by_name
    existing = await get_by_name(session, name=toggle_in.name)
    if existing:
        raise HTTPException(status_code=409, detail='Toggle name already exists')
    svc = FeatureToggleService(session)
    return await svc.create_toggle(toggle_in)
