"""Generator for User API routes.

User endpoints are special -- they have auth patterns that no generic CRUD
can handle:

* Public signup (no auth).
* Self-management endpoints (``/me``) gated by ``CurrentUser``.
* Superuser management endpoints gated by ``CurrentSuperuser``.
"""

from __future__ import annotations

MCP_TOOL = {
    'name': 'fastapi_generate_user_routes',
    'description': 'Generate complete User management routes: signup, /me, /me/password, and superuser CRUD.',
    'tags': ['auth', 'endpoints', 'generator'],
    'entry': 'generate_user_routes',
}

import textwrap
from pathlib import Path


def generate_user_routes(
    output_dir: str,
    with_superuser_management: bool = True,
) -> dict:
    """Generate ``api/routes/users.py`` with all User endpoints.

    Public:
        POST /users/signup -- public registration (no auth).

    Authenticated (self-management):
        GET    /users/me          -- return current user.
        PATCH  /users/me          -- update own profile.
        PATCH  /users/me/password -- update own password.
        DELETE /users/me          -- delete own account.

    Superuser management (optional):
        GET    /users/           -- list all users (paginated).
        POST   /users/           -- admin-create a user.
        GET    /users/{id}       -- get user by ID.
        PATCH  /users/{id}       -- update any user.
        DELETE /users/{id}       -- delete user and cascade items.

    Args:
        output_dir: Project root.  File is written to
            ``{output_dir}/api/routes/users.py``.
        with_superuser_management: Include the superuser-only
            CRUD endpoints (list, admin-create, get-by-id,
            update-by-id, delete-by-id).  Defaults to ``True``.

    Returns:
        Dict with ``files_created`` and ``notes``.
    """
    out = Path(output_dir) / "api" / "routes"
    out.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Superuser management block
    # ------------------------------------------------------------------
    superuser_imports = ""
    superuser_routes = ""

    if with_superuser_management:
        superuser_imports = "from app.api.deps import CurrentSuperuser, get_current_superuser\n"

        superuser_routes = textwrap.dedent('''\


# ---------------------------------------------------------------------------
# Superuser management
# ---------------------------------------------------------------------------


@router.get(
    "/",
    response_model=UsersPublic,
    dependencies=[Depends(get_current_superuser)],
)
async def list_users(
    session: SessionDep,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
) -> UsersPublic:
    """Return a paginated list of all users.

    Superuser-only.  Results are ordered by ``created_at`` descending.

    Args:
        skip: Number of records to skip (offset).
        limit: Maximum number of records to return (1--1000).
    """
    result = await crud_get_multi(session, skip=skip, limit=limit)
    return UsersPublic(**result)


@router.post(
    "/",
    response_model=UserPublic,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(get_current_superuser)],
)
async def create_user(
    session: SessionDep,
    body: UserCreate,
) -> UserPublic:
    """Create a new user (admin-created).

    Validates that the email is not already registered.
    Hashes the password before storing.
    """
    existing = await crud_get_by_email(session, email=body.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email already exists",
        )

    obj_in = body.model_dump()
    obj_in["hashed_password"] = get_password_hash(obj_in.pop("password"))
    user = await crud_create(session, obj_in=obj_in)
    return user


@router.get("/{user_id}", response_model=UserPublic)
async def read_user_by_id(
    session: SessionDep,
    user_id: uuid.UUID,
    current_user: CurrentUser,
) -> UserPublic:
    """Fetch a user by UUID.

    Non-superusers may only view themselves.

    Raises:
        HTTPException 403: Not enough permissions.
        HTTPException 404: User not found.
    """
    if not current_user.is_superuser and current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        )

    user = await crud_get(session, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return user


@router.patch("/{user_id}", response_model=UserPublic)
async def update_user_by_id(
    session: SessionDep,
    user_id: uuid.UUID,
    body: UserUpdate,
    current_user: CurrentSuperuser,
) -> UserPublic:
    """Update any user by UUID.

    Superuser-only.  Supports partial updates (``exclude_unset``).
    If email is changed, validates uniqueness.
    """
    user = await crud_get(session, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    update_data = body.model_dump(exclude_unset=True)

    if "email" in update_data and update_data["email"] != user.email:
        existing = await crud_get_by_email(session, email=update_data["email"])
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A user with this email already exists",
            )

    if "password" in update_data:
        update_data["hashed_password"] = get_password_hash(
            update_data.pop("password"),
        )

    user = await crud_update(session, db_obj=user, obj_in=update_data)
    return user


@router.delete("/{user_id}", response_model=Message)
async def delete_user_by_id(
    session: SessionDep,
    user_id: uuid.UUID,
    current_user: CurrentSuperuser,
) -> Message:
    """Delete a user by UUID and cascade-delete their items.

    Superuser-only.  A superuser cannot delete themselves via this
    endpoint.

    Raises:
        HTTPException 403: Cannot delete yourself.
        HTTPException 404: User not found.
    """
    if current_user.id == user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Superusers cannot delete themselves",
        )

    user = await crud_get(session, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    await crud_delete(session, user_id)
    return Message(message="User deleted")
''')

    # ------------------------------------------------------------------
    # Deps helper for superuser dependency injection
    # ------------------------------------------------------------------
    deps_helper = ""
    if with_superuser_management:
        deps_helper = ""  # get_current_superuser is imported directly from deps

    # ------------------------------------------------------------------
    # Full file content
    # ------------------------------------------------------------------
    content = textwrap.dedent(f'''\
"""User routes -- signup, self-management, and superuser administration."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.exc import IntegrityError

from app.crud.user import (
    create as crud_create,
    delete as crud_delete,
    get as crud_get,
    get_by_email as crud_get_by_email,
    get_multi as crud_get_multi,
    update as crud_update,
)
from app.core.rate_limit import limiter
from app.core.security import get_password_hash, verify_password
from app.core.session import SessionDep
from app.api.deps import CurrentUser
{superuser_imports}from app.schemas.user import (
    UserCreate,
    UserPublic,
    UsersPublic,
    UserUpdate,
)
from app.schemas.message import Message
{deps_helper}

# ---------------------------------------------------------------------------
# Inline schemas for self-management endpoints
# ---------------------------------------------------------------------------


class UpdatePassword(BaseModel):
    """Payload for the change-own-password endpoint."""

    current_password: str = Field(max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class UserUpdateMe(BaseModel):
    """Payload for the update-own-profile endpoint."""

    full_name: str | None = Field(default=None, max_length=256)
    email: EmailStr | None = Field(default=None, max_length=320)


router = APIRouter(prefix="/users", tags=["users"])


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------


@router.post(
    "/signup",
    response_model=UserPublic,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("3/minute")
async def signup(
    request: Request,
    session: SessionDep,
    body: UserCreate,
) -> UserPublic:
    """Public registration endpoint (no auth required).

    Validates that the email is not already registered.
    Hashes the password before storing.
    Returns ``UserPublic`` -- never exposes ``hashed_password``.

    Race-safe: the optimistic check is backed by a UNIQUE constraint
    on ``users.email`` and an IntegrityError handler so two concurrent
    signups with the same email both return 400 (not one 201 + one 500).
    """
    existing = await crud_get_by_email(session, email=body.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email already exists",
        )

    obj_in = body.model_dump()
    obj_in["hashed_password"] = get_password_hash(obj_in.pop("password"))
    try:
        user = await crud_create(session, obj_in=obj_in)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email already exists",
        )
    return user


# ---------------------------------------------------------------------------
# Authenticated user -- self-management (/me)
# ---------------------------------------------------------------------------


@router.get("/me", response_model=UserPublic)
async def read_user_me(
    current_user: CurrentUser,
) -> UserPublic:
    """Return the currently authenticated user."""
    return current_user  # type: ignore[return-value]


@router.patch("/me", response_model=UserPublic)
async def update_user_me(
    session: SessionDep,
    body: UserUpdateMe,
    current_user: CurrentUser,
) -> UserPublic:
    """Update the authenticated user\'s own profile.

    Only ``full_name`` and ``email`` may be changed.  If the email is
    changed, validates that the new address is not already taken.
    """
    update_data = body.model_dump(exclude_unset=True)

    if "email" in update_data and update_data["email"] != current_user.email:
        existing = await crud_get_by_email(session, email=update_data["email"])
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A user with this email already exists",
            )

    user = await crud_update(session, db_obj=current_user, obj_in=update_data)
    return user


@router.patch("/me/password", response_model=Message)
async def update_password_me(
    session: SessionDep,
    body: UpdatePassword,
    current_user: CurrentUser,
) -> Message:
    """Update the authenticated user\'s own password.

    Requires the current password for verification.  Rejects the
    request if the new password is the same as the current one.
    """
    if not verify_password(body.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect password",
        )

    if body.current_password == body.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must differ from current password",
        )

    hashed = get_password_hash(body.new_password)
    await crud_update(session, db_obj=current_user, obj_in={{"hashed_password": hashed}})
    return Message(message="Password updated successfully")


@router.delete("/me", response_model=Message)
async def delete_user_me(
    session: SessionDep,
    current_user: CurrentUser,
) -> Message:
    """Delete the authenticated user\'s own account.

    Superusers cannot delete themselves via this endpoint -- they must
    be removed by another superuser through ``DELETE /users/{{id}}``.
    """
    if current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Superusers cannot delete themselves; use DELETE /users/{{id}} instead",
        )

    await crud_delete(session, current_user.id)
    return Message(message="User deleted")
{superuser_routes}''')

    file_path = out / "users.py"
    file_path.write_text(content)

    # ------------------------------------------------------------------
    # Notes
    # ------------------------------------------------------------------
    notes = [
        "Generated api/routes/users.py with public signup + self-management (/me) endpoints.",
    ]
    if with_superuser_management:
        notes.append(
            "Superuser management included: list, admin-create, get-by-id, "
            "update-by-id, delete-by-id."
        )
    notes.append(
        "Inline schemas: UpdatePassword (current_password, new_password), "
        "UserUpdateMe (full_name, email) with max_length constraints."
    )
    notes.append(
        "Imports: crud/user.py (create, get, get_multi, get_by_email, update, delete), "
        "core/security.py, core/session.py, api/deps.py, schemas/user.py "
        "(contains UserCreate/Update/Public + UsersPublic), schemas/message.py."
    )

    return {"files_created": [str(file_path)], "notes": notes}
