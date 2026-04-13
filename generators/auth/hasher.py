"""Generator for password hashing utilities (argon2id via pwdlib)."""

from __future__ import annotations

import textwrap
from pathlib import Path


def generate_password_hasher(output_dir: str) -> dict:
    """Generate core/security.py with argon2id password hashing.

    Uses ``pwdlib`` (the modern replacement for passlib) with its
    recommended Argon2 hasher. Includes a pre-computed dummy hash
    for constant-time verification to prevent timing attacks.

    Args:
        output_dir: Directory where core/security.py will be written.

    Returns:
        Dict with files_created and notes.
    """
    out = Path(output_dir) / "core"
    out.mkdir(parents=True, exist_ok=True)

    content = textwrap.dedent('''\
        """Password hashing and verification — argon2id via pwdlib."""

        from pwdlib import PasswordHash
        from pwdlib.hashers.argon2 import Argon2Hasher

        # Argon2id is the OWASP-recommended algorithm (2024+).
        # pwdlib.recommended() selects Argon2 with safe defaults:
        #   time_cost=3, memory_cost=65536 (64 MiB), parallelism=4
        password_hash = PasswordHash((Argon2Hasher(),))

        # Pre-computed hash used for timing-attack prevention.
        # When a login attempt targets a non-existent user, we still run
        # verify against this dummy so the response time is indistinguishable
        # from a real verification.
        DUMMY_HASH = password_hash.hash("dummy-timing-prevention")


        def verify_password(plain_password: str, hashed_password: str) -> bool:
            """Verify a plain-text password against an argon2id hash.

            Args:
                plain_password: The password to check.
                hashed_password: The stored argon2id hash.

            Returns:
                True if the password matches.
            """
            return password_hash.verify(plain_password, hashed_password)


        def get_password_hash(password: str) -> str:
            """Hash a plain-text password with argon2id.

            Args:
                password: The plain-text password.

            Returns:
                The argon2id hash string.
            """
            return password_hash.hash(password)
    ''')

    file_path = out / "security.py"
    file_path.write_text(content)

    return {
        "files_created": [str(file_path)],
        "notes": [
            "Generated core/security.py with argon2id hashing via pwdlib.",
            "DUMMY_HASH prevents timing-based user enumeration on login.",
            "Requires: pip install 'pwdlib[argon2]'",
        ],
    }
