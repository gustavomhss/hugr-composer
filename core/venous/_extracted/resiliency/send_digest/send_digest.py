from __future__ import annotations
from typing import Any


@_task
def send_digest(user_id: str, digest_type: str='weekly') -> dict[str, Any]:
    """Scheduled task: send a periodic digest email to a user.

    Args:
        user_id: UUID string of the target user.
        digest_type: Digest frequency label (e.g. ``weekly``, ``daily``).

    Returns:
        Dict with ``status``, ``user_id``, and ``digest_type``.
    """
    logger.info('send_digest: user=%s type=%s', user_id, digest_type)
    return {'status': 'sent', 'user_id': user_id, 'digest_type': digest_type}
