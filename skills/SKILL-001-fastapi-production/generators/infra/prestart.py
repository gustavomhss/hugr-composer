"""Generator for backend_pre_start.py — waits for database readiness."""

from __future__ import annotations

MCP_TOOL = {
    'name': 'fastapi_generate_prestart',
    'description': 'Generate backend_pre_start.py -- waits for database readiness with exponential backoff.',
    'tags': ['generator', 'infra'],
    'entry': 'generate_prestart',
}

import textwrap
from pathlib import Path


def generate_prestart(
    output_dir: str,
    max_retries: int = 10,
    wait_seconds: int = 1,
) -> dict:
    """Generate backend_pre_start.py that blocks until the database is reachable.

    Uses a simple TCP socket check — no extra driver dependencies needed.
    Designed to be the first command in a Docker entrypoint::

        python -m app.backend_pre_start && uvicorn app.main:app ...

    Args:
        output_dir: Directory where backend_pre_start.py will be written.
        max_retries: Maximum number of connection attempts before exiting.
        wait_seconds: Initial wait between retries (doubles each attempt).

    Returns:
        Dict with files_created and notes.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    content = textwrap.dedent(f'''\
        """Wait for the database to be ready before starting the application.

        Uses a TCP socket check — no psycopg2 or other sync driver needed.
        Retries with exponential back-off up to {max_retries} attempts.
        """

        from __future__ import annotations

        import logging
        import socket
        import sys
        import time

        from app.core.config import settings

        logger = logging.getLogger(__name__)

        MAX_RETRIES = {max_retries}
        INITIAL_WAIT = {wait_seconds}


        def wait_for_db() -> None:
            """Block until the database accepts TCP connections."""
            host = settings.POSTGRES_SERVER
            port = int(settings.POSTGRES_PORT)

            wait = INITIAL_WAIT
            last_error: Exception | None = None

            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    sock = socket.create_connection((host, port), timeout=5)
                    sock.close()
                    logger.info(
                        "Database is reachable at %s:%d (attempt %d/%d).",
                        host, port, attempt, MAX_RETRIES,
                    )
                    return
                except (OSError, ConnectionRefusedError) as exc:
                    last_error = exc
                    logger.warning(
                        "Database not ready at %s:%d (attempt %d/%d) — retrying in %ds ...",
                        host, port, attempt, MAX_RETRIES, wait,
                    )
                    time.sleep(wait)
                    wait = min(wait * 2, 30)

            logger.error(
                "Could not connect to database at %s:%d after %d attempts. Last error: %s",
                host, port, MAX_RETRIES, last_error,
            )
            sys.exit(1)


        if __name__ == "__main__":
            logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
            wait_for_db()
    ''')

    file_path = out / "backend_pre_start.py"
    file_path.write_text(content)

    return {
        "files_created": [str(file_path)],
        "notes": [
            f"Generated backend_pre_start.py — TCP socket check with {max_retries} retries, exponential back-off.",
            "No sync DB driver needed — uses raw socket connection.",
            "Usage: python -m app.backend_pre_start && uvicorn app.main:app ...",
        ],
    }
