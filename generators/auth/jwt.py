"""Generator for JWT token creation and verification."""

from __future__ import annotations

import textwrap
from pathlib import Path


def generate_jwt(
    output_dir: str,
    access_expiry_minutes: int = 30,
    algorithm: str = "HS256",
) -> dict:
    """Generate core/jwt.py with JWT helpers using PyJWT.

    Args:
        output_dir: Directory where core/jwt.py will be written.
        access_expiry_minutes: Default access-token lifetime in minutes.
        algorithm: JWT signing algorithm (HS256, HS384, HS512).

    Returns:
        Dict with files_created and notes.
    """
    out = Path(output_dir) / "core"
    out.mkdir(parents=True, exist_ok=True)

    content = textwrap.dedent(f'''\
        """JWT token creation and verification — PyJWT.

        Uses PyJWT (``import jwt``), NOT python-jose which is unmaintained.
        All timestamps use ``datetime.now(timezone.utc)`` — never ``utcnow()``.
        """

        from datetime import datetime, timedelta, timezone

        import jwt

        from app.core.config import settings

        ALGORITHM = "{algorithm}"
        ACCESS_TOKEN_EXPIRE_MINUTES = {access_expiry_minutes}


        def create_access_token(
            subject: str,
            expires_delta: timedelta | None = None,
        ) -> str:
            """Create a signed JWT access token.

            Args:
                subject: Token subject (typically user ID as string).
                expires_delta: Custom expiry; defaults to ACCESS_TOKEN_EXPIRE_MINUTES.

            Returns:
                Encoded JWT string.
            """
            now = datetime.now(timezone.utc)
            expire = now + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
            payload = {{
                "sub": subject,
                "exp": expire,
                "iat": now,
                "type": "access",
            }}
            return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


        def decode_token(token: str) -> dict:
            """Decode and validate a JWT token.

            Enforces algorithm whitelist to prevent algorithm-confusion attacks.

            Args:
                token: The encoded JWT string.

            Returns:
                Decoded payload dict.

            Raises:
                jwt.ExpiredSignatureError: Token has expired.
                jwt.InvalidTokenError: Token is malformed or signature invalid.
            """
            return jwt.decode(
                token,
                settings.SECRET_KEY,
                algorithms=[ALGORITHM],
            )


        def create_password_reset_token(email: str) -> str:
            """Create a short-lived token for password reset flows.

            Args:
                email: User email embedded in the token.

            Returns:
                Encoded JWT string (expires in 1 hour).
            """
            now = datetime.now(timezone.utc)
            payload = {{
                "sub": email,
                "exp": now + timedelta(hours=1),
                "iat": now,
                "type": "password_reset",
            }}
            return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


        def verify_password_reset_token(token: str) -> str | None:
            """Verify a password-reset token and extract the email.

            Args:
                token: The encoded JWT string.

            Returns:
                The email address if valid, None otherwise.
            """
            try:
                payload = jwt.decode(
                    token,
                    settings.SECRET_KEY,
                    algorithms=[ALGORITHM],
                )
                if payload.get("type") != "password_reset":
                    return None
                return payload.get("sub")
            except jwt.InvalidTokenError:
                return None
    ''')

    # --- Phase 0.5 nugget: create_token_pair with jti ----------------------
    # Extracted from modules/auth/tools/scaffold_auth.py (_security_py)
    # Appended to the generated jwt.py after the base functions above.
    token_pair_snippet = textwrap.dedent(f'''\


        REFRESH_TOKEN_EXPIRE_DAYS = 7


        def create_token_pair(user_id: str) -> dict:
            """Create an access + refresh token pair.

            Access token: short-lived ({access_expiry_minutes} min), type=\"access\".
            Refresh token: long-lived (7 days), type=\"refresh\", includes a
            unique ``jti`` (JWT ID) for rotation and revocation tracking.

            Args:
                user_id: The subject to embed in both tokens.

            Returns:
                Dict with ``access_token``, ``refresh_token``, and
                ``token_type`` keys.

            Note:
                Store the refresh token's ``jti`` in a Redis/DB blocklist on
                use (rotation) or logout to prevent replay attacks.
            """
            import uuid as _uuid
            now = datetime.now(timezone.utc)

            access = jwt.encode(
                {{
                    "sub": user_id,
                    "type": "access",
                    "exp": now + timedelta(minutes={access_expiry_minutes}),
                    "iat": now,
                }},
                settings.SECRET_KEY,
                algorithm=ALGORITHM,
            )

            refresh = jwt.encode(
                {{
                    "sub": user_id,
                    "type": "refresh",
                    "exp": now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
                    "iat": now,
                    "jti": str(_uuid.uuid4()),
                }},
                settings.SECRET_KEY,
                algorithm=ALGORITHM,
            )

            return {{
                "access_token": access,
                "refresh_token": refresh,
                "token_type": "bearer",
            }}
    ''')
    content = content.rstrip() + token_pair_snippet

    file_path = out / "jwt.py"
    file_path.write_text(content)

    return {
        "files_created": [str(file_path)],
        "notes": [
            f"Generated core/jwt.py with {algorithm}, {access_expiry_minutes}-min access tokens.",
            "Uses PyJWT (import jwt), NOT python-jose. Algorithm whitelist enforced on decode.",
            "Password-reset tokens are separate (type=password_reset, 1-hour expiry).",
            "All timestamps use datetime.now(timezone.utc) — never utcnow().",
            "Phase 0.5 nugget: added create_token_pair(user_id) with jti in refresh token "
            "(extracted from scaffold_auth.py._security_py). Supports rotation/revocation.",
        ],
    }
