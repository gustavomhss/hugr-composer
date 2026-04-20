from __future__ import annotations
from typing import Any
import logging
import structlog
import sys


def configure_structlog(level: str='INFO', fmt: str='json', redaction_enabled: bool=True) -> None:
    """Configure structlog for the application.

    Sets up JSON (production) or console (development) renderer,
    correlation ID injection, and optional PII redaction.

    Args:
        level: Log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        fmt: Output format — ``"json"`` or ``"console"``.
        redaction_enabled: When ``True``, apply PII redaction processor.
    """
    processors: list[Any] = [structlog.contextvars.merge_contextvars, structlog.stdlib.add_log_level, structlog.stdlib.add_logger_name, structlog.processors.TimeStamper(fmt='iso'), structlog.processors.StackInfoRenderer(), structlog.processors.format_exc_info]
    if redaction_enabled:
        redactor = Redactor()
        processors.append(redactor)
    if fmt == 'json':
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())
    structlog.configure(processors=processors, wrapper_class=structlog.stdlib.BoundLogger, context_class=dict, logger_factory=structlog.stdlib.LoggerFactory(), cache_logger_on_first_use=True)
    logging.basicConfig(format='%(message)s', stream=sys.stdout, level=getattr(logging, level.upper(), logging.INFO))
