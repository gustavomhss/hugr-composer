"""Generator for structlog configuration (core/logging.py)."""

from __future__ import annotations

import textwrap
from pathlib import Path


def generate_logging_setup(output_dir: str) -> dict:
    """Generate core/logging.py with structlog configuration.

    Produces a configure_logging() function that:
    - Sets up structlog with JSON output for production
    - Includes a TimeStamper, log level, logger name, stack/exception info
    - Binds correlation_id from contextvars (CorrelationMiddleware sets this)
    - Routes stdlib logging through structlog ProcessorFormatter

    Args:
        output_dir: Directory where core/logging.py will be written.

    Returns:
        Dict with files_created and notes.
    """
    out = Path(output_dir) / "core"
    out.mkdir(parents=True, exist_ok=True)

    content = textwrap.dedent('''\
        """Structlog configuration with JSON output and correlation ID binding.

        Call ``configure_logging()`` ONCE at application startup, before any
        logger is created.  After this call, every ``structlog.get_logger()``
        will produce JSON logs with the active correlation_id (set by
        ``CorrelationMiddleware``) bound to every record.
        """

        from __future__ import annotations

        import logging
        import sys

        import structlog
        from structlog.contextvars import merge_contextvars


        def configure_logging() -> None:
            """Configure structlog + stdlib logging for production-grade JSON output."""
            timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

            shared_processors = [
                merge_contextvars,
                structlog.stdlib.add_log_level,
                structlog.stdlib.add_logger_name,
                timestamper,
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
            ]

            structlog.configure(
                processors=shared_processors + [
                    structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
                ],
                logger_factory=structlog.stdlib.LoggerFactory(),
                cache_logger_on_first_use=True,
            )

            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(
                structlog.stdlib.ProcessorFormatter(
                    foreign_pre_chain=shared_processors,
                    processors=[
                        structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                        structlog.processors.JSONRenderer(),
                    ],
                )
            )

            root = logging.getLogger()
            root.handlers = [handler]
            root.setLevel(logging.INFO)

            # Quiet noisy third-party loggers
            for noisy in ("uvicorn.access", "watchfiles"):
                logging.getLogger(noisy).setLevel(logging.WARNING)


        __all__ = ["configure_logging"]
    ''')

    file_path = out / "logging.py"
    file_path.write_text(content)

    return {
        "files_created": [str(file_path)],
        "notes": [
            "Generated core/logging.py with structlog configuration.",
            "JSON output with correlation_id binding via contextvars.",
            "Call configure_logging() before app instantiation in main.py.",
        ],
    }
