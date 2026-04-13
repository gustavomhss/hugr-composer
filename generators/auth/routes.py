"""Generator for authentication API routes."""

from __future__ import annotations

import textwrap
from pathlib import Path


def generate_auth_routes(
    output_dir: str,
    with_password_recovery: bool = True,
) -> dict:
    """Generate api/routes/login.py with login and optional password-recovery endpoints.

    Args:
        output_dir: Directory where api/routes/login.py will be written.
        with_password_recovery: Include password-recovery and reset endpoints.

    Returns:
        Dict with files_created and notes.
    """
    out = Path(output_dir) / "api" / "routes"
    out.mkdir(parents=True, exist_ok=True)

    # --- Password recovery endpoints -------------------------------------
    recovery_imports = ""
    recovery_routes = ""
    if with_password_recovery:
        recovery_imports = (
            "from app.core.jwt import create_password_reset_token, verify_password_reset_token\n"
            "from app.core.security import get_password_hash\n"
            "from app.crud.user import update as update_user\n"
            "from app.schemas.message import Message\n"
            "from app.schemas.token import NewPassword\n"
            "from app.utils.email import send_password_reset_email\n"
        )

        recovery_routes = textwrap.dedent('''\


@router.post("/password-recovery/{email}", response_model=Message)
@limiter.limit("3/minute")
async def recover_password(
    request: Request, email: str, session: SessionDep
) -> Message:
    """Send a password-recovery email.

    SECURITY: Always returns the same response regardless of whether
    the email exists. This prevents user-enumeration attacks.
    """
    user = await get_by_email(session, email=email)

    if user:
        token = create_password_reset_token(email=email)
        await send_password_reset_email(to=email, token=token)

    # Same response whether user exists or not -- no enumeration.
    return Message(message="If that email is registered, a recovery link has been sent.")


@router.post("/reset-password", response_model=Message)
async def reset_password(session: SessionDep, body: NewPassword) -> Message:
    """Reset password using a valid reset token.

    Args:
        body: Contains the reset token and the new password.
    """
    email = verify_password_reset_token(body.token)
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired token",
        )

    user = await get_by_email(session, email=email)
    # Collapse "user not found" and "inactive user" into the same generic
    # error as "invalid token" — never reveal which accounts exist.
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired token",
        )

    hashed = get_password_hash(body.new_password)
    await update_user(session, db_obj=user, obj_in={"hashed_password": hashed})

    return Message(message="Password updated successfully.")
''')

    content = textwrap.dedent(f"""\
\"\"\"Authentication routes -- login, token validation, password recovery.\"\"\"

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm

from app.core.config import settings
from app.core.jwt import ACCESS_TOKEN_EXPIRE_MINUTES, create_access_token
from app.core.rate_limit import limiter
from app.core.security import DUMMY_HASH, verify_password
from app.core.session import SessionDep
from app.api.deps import CurrentUser
from app.crud.user import get_by_email
from app.schemas.token import Token
{recovery_imports}
router = APIRouter(tags=["login"])


@router.post("/login/access-token", response_model=Token)
@limiter.limit("5/minute")
async def login_access_token(
    request: Request,
    session: SessionDep,
    form_data: OAuth2PasswordRequestForm = Depends(),
) -> Token:
    \"\"\"OAuth2-compatible token login.

    Authenticates with username (email) + password and returns a
    bearer access token. Uses constant-time comparison via DUMMY_HASH
    to prevent timing-based user enumeration.
    \"\"\"
    user = await get_by_email(session, email=form_data.username)

    # Single, generic 401 for EVERY failure path (no user / wrong password /
    # inactive user). Differentiating these leaks account state and enables
    # user enumeration. DUMMY_HASH ensures timing parity with a real lookup.
    _INVALID = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect email or password",
    )

    if user is None:
        verify_password("not-a-real-password", DUMMY_HASH)
        raise _INVALID

    if not verify_password(form_data.password, user.hashed_password):
        raise _INVALID

    if not user.is_active:
        raise _INVALID

    access_token = create_access_token(
        subject=str(user.id),
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return Token(access_token=access_token)


@router.post("/login/test-token", response_model=dict)
async def test_token(current_user: CurrentUser) -> dict:
    \"\"\"Test access token validity.

    Returns the authenticated user's basic info.
    \"\"\"
    return {{
        "id": str(current_user.id),
        "email": current_user.email,
        "is_active": current_user.is_active,
        "is_superuser": current_user.is_superuser,
    }}
{recovery_routes}""")

    file_path = out / "login.py"
    file_path.write_text(content)

    notes = ["Generated api/routes/login.py with /login/access-token and /login/test-token."]
    if with_password_recovery:
        notes.append("Password recovery (/password-recovery/{email}) and reset (/reset-password) included.")
    notes.append("Login uses DUMMY_HASH for timing-attack prevention on non-existent users.")

    return {"files_created": [str(file_path)], "notes": notes}
