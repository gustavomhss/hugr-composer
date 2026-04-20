from __future__ import annotations
from datetime import datetime
from datetime import timezone


def log_pii_access(table: str, user_id: str, columns: list[str]) -> None:
    """Emit a structured log entry for PII field access.

    Logged at INFO level.  Sink is the standard Python logger; downstream
    handlers (structlog, Loki, etc.) can enrich the event.

    Args:
        table: Name of the database table accessed.
        user_id: Identifier of the requesting user.
        columns: PII column names that were read.
    """
    logger.info('pii_access', extra={'table': table, 'user_id': user_id, 'pii_columns': columns, 'ts': datetime.now(timezone.utc).isoformat()})
