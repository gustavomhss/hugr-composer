from __future__ import annotations
from fastapi import HTTPException


@router.put('/{name}', response_model=ToggleRead)
async def update_toggle(name: str, toggle_in: ToggleUpdate, session: SessionDep, current_user: CurrentSuperuser) -> ToggleRead:
    """Update a feature toggle. Superuser only.

    Args:
        name: Toggle name path parameter.
        toggle_in: Validated partial update payload.
        session: Injected async DB session.
        current_user: Must be a superuser.

    Raises:
        HTTPException: 404 if toggle not found.
    """
    svc = FeatureToggleService(session)
    result = await svc.update_toggle(name, toggle_in)
    if result is None:
        raise HTTPException(status_code=404, detail='Toggle not found')
    return result
