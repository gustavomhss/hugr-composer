"""Generator for a shared slowapi rate-limiter backed by Redis.

Writes ``core/rate_limit.py`` with a module-level ``Limiter`` instance
that auth/signup/password-recovery endpoints can import and decorate
their routes with.  Uses Redis as the storage backend so limits apply
across multiple uvicorn workers and containers.
"""

from __future__ import annotations

import textwrap
from pathlib import Path


def generate_rate_limit(output_dir: str) -> dict:
    """Generate ``core/rate_limit.py`` with a shared slowapi Limiter.

    Args:
        output_dir: The app package directory (``out/app``).

    Returns:
        Dict with ``files_created`` and ``notes``.
    """
    out = Path(output_dir) / "core"
    out.mkdir(parents=True, exist_ok=True)

    content = textwrap.dedent('''\
        """Rate limiter for authentication endpoints.

        Uses ``slowapi`` with a Redis backend so limits survive worker
        restarts and apply across multiple uvicorn processes.  Register
        the limiter on the FastAPI app in ``main.py``::

            from app.core.rate_limit import limiter
            from slowapi.errors import RateLimitExceeded
            from slowapi import _rate_limit_exceeded_handler

            app.state.limiter = limiter
            app.add_exception_handler(
                RateLimitExceeded, _rate_limit_exceeded_handler
            )

        Then decorate sensitive endpoints::

            @limiter.limit("5/minute")
            async def login_access_token(request: Request, ...):
                ...
        """

        from __future__ import annotations

        from slowapi import Limiter
        from slowapi.util import get_remote_address

        from app.core.config import settings


        def _storage_uri() -> str:
            """Return the storage URI for the limiter.

            Falls back to in-memory storage if ``REDIS_URL`` is not
            configured — useful for local development but not for
            production, where multiple workers would each maintain
            their own counters.
            """
            url = getattr(settings, "REDIS_URL", None)
            if url:
                return str(url)
            return "memory://"


        # When ``RATE_LIMITING_ENABLED`` is false (e.g. during pytest runs),
        # construct the limiter with ``enabled=False`` so all decorators
        # become no-ops.  This avoids 429s in tests that hit auth endpoints
        # in tight loops while keeping the production decorators in place.
        _enabled = getattr(settings, "RATE_LIMITING_ENABLED", True)

        limiter = Limiter(
            key_func=get_remote_address,
            storage_uri=_storage_uri(),
            default_limits=[],
            enabled=_enabled,
        )
    ''')

    file_path = out / "rate_limit.py"
    file_path.write_text(content)

    return {
        "files_created": [str(file_path)],
        "notes": [
            "Generated core/rate_limit.py with a slowapi Limiter.",
            "Uses Redis storage when REDIS_URL is configured; falls back to memory otherwise.",
        ],
    }
