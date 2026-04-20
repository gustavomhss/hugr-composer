from __future__ import annotations
from datetime import datetime
from datetime import timezone
from typing import Any


def generate_erasure_certificate(user_id: str, tables_affected: list[str]) -> dict[str, Any]:
    """Build a GDPR Art. 17 erasure certificate dict.

    Args:
        user_id: The data subject identifier.
        tables_affected: Tables from which data was erased / anonymised.

    Returns:
        Dict with timestamp, user_id, tables_affected, and attestation string.
    """
    ts = datetime.now(timezone.utc).isoformat()
    return {'certificate_type': 'GDPR_ART17_ERASURE', 'issued_at': ts, 'data_subject_id': user_id, 'tables_affected': tables_affected, 'attestation': f'Personal data for subject {user_id!r} was anonymised/deleted across {len(tables_affected)} table(s) at {ts}.'}
