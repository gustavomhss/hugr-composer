"""Generator for authentication FastAPI dependencies."""

from __future__ import annotations

import textwrap
from pathlib import Path


def generate_auth_deps(
    output_dir: str,
    token_url: str = "/api/v1/login/access-token",
) -> dict:
    """Generate api/deps.py with OAuth2 bearer dependencies.

    Creates ``get_current_user``, ``get_current_superuser``, and
    annotated type aliases ``CurrentUser`` / ``CurrentSuperuser``
    for use in route function signatures.

    Args:
        output_dir: Directory where api/deps.py will be written.
        token_url: OAuth2 token endpoint URL for OpenAPI docs.

    Returns:
        Dict with files_created and notes.
    """
    out = Path(output_dir) / "api"
    out.mkdir(parents=True, exist_ok=True)

    content = textwrap.dedent(f'''\
        """Authentication dependencies for FastAPI routes."""

        import uuid
        from typing import Annotated

        import jwt
        from fastapi import Depends, HTTPException, status
        from fastapi.security import OAuth2PasswordBearer

        from app.core.jwt import decode_token
        from app.core.session import SessionDep
        from app.crud.user import get as get_user
        from app.models.user import User
        from app.schemas.token import TokenPayload

        oauth2_scheme = OAuth2PasswordBearer(tokenUrl="{token_url}")

        # Generic 401 used for every auth failure. Differentiating between
        # "bad token", "no user", and "inactive user" leaks account state to
        # attackers and enables user-enumeration.
        _CREDENTIALS_ERROR = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={{"WWW-Authenticate": "Bearer"}},
        )


        async def get_current_user(
            session: SessionDep,
            token: Annotated[str, Depends(oauth2_scheme)],
        ) -> User:
            """Decode the JWT and return the active user.

            Returns a single generic 401 for ALL failure modes
            (bad token, missing sub, malformed UUID, user not found,
            inactive user) to prevent account-state enumeration.
            """
            try:
                payload = decode_token(token)
                token_data = TokenPayload(sub=payload.get("sub"))
            except jwt.InvalidTokenError:
                raise _CREDENTIALS_ERROR

            if token_data.sub is None:
                raise _CREDENTIALS_ERROR

            # sub may be a non-UUID string if the token was crafted; reject.
            try:
                user_id = uuid.UUID(token_data.sub)
            except (ValueError, TypeError):
                raise _CREDENTIALS_ERROR

            user = await get_user(session, id=user_id)
            # Collapse "not found" and "inactive" into the same response to
            # avoid leaking whether an account exists.
            if user is None or not user.is_active:
                raise _CREDENTIALS_ERROR

            return user


        async def get_current_superuser(
            current_user: Annotated[User, Depends(get_current_user)],
        ) -> User:
            """Require the current user to be a superuser.

            Raises:
                HTTPException 403: User does not have superuser privileges.
            """
            if not current_user.is_superuser:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="The user does not have enough privileges",
                )
            return current_user


        # ------------------------------------------------------------------
        # Annotated aliases — use these in route function signatures:
        #
        #   @router.get("/me")
        #   async def read_me(user: CurrentUser) -> UserPublic:
        #       return user
        # ------------------------------------------------------------------
        CurrentUser = Annotated[User, Depends(get_current_user)]
        CurrentSuperuser = Annotated[User, Depends(get_current_superuser)]
    ''')

    file_path = out / "deps.py"
    file_path.write_text(content)

    return {
        "files_created": [str(file_path)],
        "notes": [
            f"Generated api/deps.py with OAuth2PasswordBearer (tokenUrl={token_url}).",
            "CurrentUser / CurrentSuperuser annotated aliases ready for route injection.",
            "get_current_user checks: token validity, user existence, is_active flag.",
        ],
    }
