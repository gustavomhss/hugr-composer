"""Generator for authentication Pydantic schemas."""

from __future__ import annotations

import textwrap
from pathlib import Path


def generate_auth_schemas(output_dir: str) -> dict:
    """Generate schemas/token.py and schemas/message.py for auth flows.

    Args:
        output_dir: Directory where schemas/ files will be written.

    Returns:
        Dict with files_created and notes.
    """
    out = Path(output_dir) / "schemas"
    out.mkdir(parents=True, exist_ok=True)

    files_created: list[str] = []

    # --- schemas/token.py -------------------------------------------------
    # Codex 3 F-008: NewPassword now applies the strength validator that
    # ships in schemas/password_policy.py — previously the policy was
    # generated but never bound to any real password input, so weak
    # passwords slipped past the advertised digit/uppercase/blocklist
    # rules. The validator returns the raw string on success and raises
    # ValueError on policy violations (Pydantic surfaces these as 422).
    token_content = textwrap.dedent('''\
        """Token and password-reset schemas."""

        from pydantic import BaseModel, Field, field_validator

        from app.schemas.password_policy import password_strength_validator


        class Token(BaseModel):
            """OAuth2-compatible access token response."""

            access_token: str
            token_type: str = "bearer"


        class TokenPayload(BaseModel):
            """Decoded JWT payload.

            Only the ``sub`` claim is extracted — additional claims
            (exp, iat, type) are validated by PyJWT during decoding.
            """

            sub: str | None = None


        class NewPassword(BaseModel):
            """Password-reset request body.

            ``new_password`` is validated against the project password
            policy (length + digit + uppercase + common-passwords
            blocklist) — see ``schemas.password_policy``.
            """

            token: str
            new_password: str = Field(min_length=8, max_length=128)

            _validate_new_password = field_validator("new_password")(
                password_strength_validator,
            )
    ''')

    token_path = out / "token.py"
    token_path.write_text(token_content)
    files_created.append(str(token_path))

    # --- schemas/message.py -----------------------------------------------
    message_content = textwrap.dedent('''\
        """Generic message response schema."""

        from pydantic import BaseModel


        class Message(BaseModel):
            """Simple message response used for confirmations and errors."""

            message: str
    ''')

    message_path = out / "message.py"
    message_path.write_text(message_content)
    files_created.append(str(message_path))

    # --- schemas/password_policy.py ----------------------------------------
    # Extracted from modules/auth/tools/scaffold_auth.py (_schemas_py)
    # Contains COMMON_PASSWORDS blocklist + field_validator for strength checks.
    password_policy_content = textwrap.dedent('''\
        """Password policy: COMMON_PASSWORDS blocklist and strength validator.

        Extracted from SKILL-001 Phase 0.5 (scaffold_auth.py nugget).
        Import and apply the validator to any Pydantic model that accepts
        a password field.

        Usage::

            from schemas.password_policy import password_strength_validator

            class RegisterRequest(BaseModel):
                password: str = Field(min_length=8, max_length=128)
                _validate_password = field_validator("password")(password_strength_validator)
        """

        # Top-10 most common passwords — reject these outright.
        # Expand this list from HIBP or SecLists as needed.
        COMMON_PASSWORDS = {
            "password", "12345678", "qwerty123", "admin123", "letmein",
            "welcome1", "password1", "abc12345", "123456789", "iloveyou",
        }


        def password_strength_validator(v: str) -> str:
            """Validate password strength: digit, uppercase, not in blocklist.

            Raises:
                ValueError: On any policy violation (message is client-safe).
            """
            if v.lower() in COMMON_PASSWORDS:
                raise ValueError("Password is too common")
            if not any(c.isdigit() for c in v):
                raise ValueError("Password must contain at least one digit")
            if not any(c.isupper() for c in v):
                raise ValueError("Password must contain at least one uppercase letter")
            return v
    ''')

    password_policy_path = out / "password_policy.py"
    password_policy_path.write_text(password_policy_content)
    files_created.append(str(password_policy_path))

    return {
        "files_created": files_created,
        "notes": [
            "Generated schemas/token.py (Token, TokenPayload, NewPassword) and schemas/message.py (Message).",
            "NewPassword enforces min_length=8, max_length=128 on the password field.",
            "Generated schemas/password_policy.py with COMMON_PASSWORDS blocklist and "
            "password_strength_validator (digit + uppercase + blocklist checks). "
            "Phase 0.5 nugget from scaffold_auth.py._schemas_py().",
        ],
    }
