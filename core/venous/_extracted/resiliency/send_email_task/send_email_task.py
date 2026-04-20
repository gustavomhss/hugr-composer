from __future__ import annotations
from typing import Any


async def send_email_task(ctx: dict[str, Any], to: str, subject: str, body: str) -> dict[str, Any]:
    """Example I/O task: send a transactional email.

    This stub logs instead of calling an SMTP provider so the task
    is safe to run in tests.  Replace the body with a real email
    client (``aiosmtplib``, Postmark, SES, …) in production.

    Args:
        ctx: arq worker context dict.
        to: Recipient address.
        subject: Email subject line.
        body: Plain-text body.

    Returns:
        Dict with ``status``, ``to``, and the executing ``job_id``.
    """
    job_id = ctx.get('job_id', 'unknown')
    logger.info('send_email_task executing', extra={'job_id': job_id, 'to': to, 'subject': subject})
    _ = body
    return {'status': 'sent', 'to': to, 'job_id': job_id}
