"""Generator for at-rest field encryption helpers (Fernet).

When a model declares a ``*_encrypted`` field (e.g. ``ssn_encrypted``),
the scaffold must ship a real way to encrypt that value before it lands
in the database and decrypt it on read.  This generator emits
``app/core/encryption.py`` with Fernet-based ``encrypt`` / ``decrypt``
helpers.

The Fernet key is derived deterministically from ``settings.SECRET_KEY``
so no extra environment variable is required: the same boot-time secret
that protects JWTs also keys field encryption.  Like the rest of the
scaffold the helper fails closed — an empty/short ``SECRET_KEY`` already
trips the config validator before this module is ever imported.
"""

from __future__ import annotations

import textwrap
from pathlib import Path


def generate_encryption(output_dir: str) -> dict:
    """Generate core/encryption.py with Fernet encrypt/decrypt helpers.

    Args:
        output_dir: Directory where core/encryption.py will be written
            (the generated project's ``app/`` directory).

    Returns:
        Dict with ``files_created`` and ``notes``.
    """
    out = Path(output_dir) / "core"
    out.mkdir(parents=True, exist_ok=True)

    content = textwrap.dedent('''\
        """At-rest encryption for sensitive ``*_encrypted`` fields (Fernet).

        Fernet provides authenticated symmetric encryption (AES-128-CBC +
        HMAC-SHA256).  Use :func:`encrypt` before persisting a sensitive
        value and :func:`decrypt` after loading it.  The cipher key is
        derived from ``settings.SECRET_KEY`` so it rotates with the rest of
        the app's secrets and needs no separate configuration.

        Example::

            from app.core.encryption import encrypt, decrypt

            patient.ssn_encrypted = encrypt(raw_ssn)        # bytes -> bytes
            raw_ssn = decrypt(patient.ssn_encrypted)        # bytes -> bytes
        """

        from __future__ import annotations

        import base64
        import hashlib
        from functools import lru_cache

        from cryptography.fernet import Fernet

        from app.core.config import settings


        @lru_cache(maxsize=1)
        def _fernet() -> Fernet:
            """Build the Fernet cipher from ``settings.SECRET_KEY``.

            A Fernet key must be 32 url-safe base64-encoded bytes.  We
            derive those 32 bytes deterministically from ``SECRET_KEY`` via
            SHA-256 so any sufficiently-strong secret yields a valid key.
            The config validator already rejects empty/weak secrets, so an
            unusable key can never reach this point.

            Raises:
                ValueError: if ``SECRET_KEY`` is unset — fail closed rather
                    than encrypt with a predictable key.
            """
            secret = settings.SECRET_KEY
            if not secret:
                raise ValueError(
                    "SECRET_KEY is not set — cannot derive a field encryption "
                    "key. Set SECRET_KEY before encrypting sensitive data."
                )
            digest = hashlib.sha256(secret.encode("utf-8")).digest()
            return Fernet(base64.urlsafe_b64encode(digest))


        def encrypt(plaintext: bytes) -> bytes:
            """Encrypt raw bytes for storage in a ``*_encrypted`` column.

            Args:
                plaintext: The sensitive value as raw bytes.

            Returns:
                The Fernet ciphertext (also bytes) — safe to persist.
            """
            return _fernet().encrypt(plaintext)


        def decrypt(ciphertext: bytes) -> bytes:
            """Decrypt a stored ``*_encrypted`` value back to raw bytes.

            Args:
                ciphertext: The Fernet ciphertext loaded from the database.

            Returns:
                The original plaintext bytes.
            """
            return _fernet().decrypt(ciphertext)
    ''')

    file_path = out / "encryption.py"
    file_path.write_text(content)

    return {
        "files_created": [str(file_path)],
        "notes": [
            "Generated core/encryption.py with Fernet encrypt/decrypt for *_encrypted fields.",
            "Cipher key is derived from SECRET_KEY (no extra env var needed).",
            "Requires: pip install cryptography",
        ],
    }
