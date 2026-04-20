from __future__ import annotations
from typing import Any
import uuid


def generate_upload_url(*, file_id: uuid.UUID, extension: str, content_type: str, expires_in: int=300, max_size_bytes: int | None=None) -> dict[str, Any]:
    """Return a presigned POST URL for direct client-to-S3 upload.

    ``max_size_bytes`` adds a Content-Length-Range condition so S3 rejects
    oversized uploads at the bucket level before our confirmation endpoint.

    Args:
        file_id: UUID for the new file — used to derive the stored_key.
        extension: File extension (max 10 chars, stripped of leading dot).
        content_type: Detected MIME type for the S3 object.
        expires_in: Presigned URL TTL in seconds.
        max_size_bytes: Optional maximum upload size enforced by S3.

    Returns:
        Dict with ``upload_url``, ``fields``, ``stored_key``, ``expires_in``.
    """
    import boto3
    from app.core.config import settings
    client = boto3.client('s3', region_name=settings.AWS_REGION)
    ext = extension.lstrip('.')[:10]
    stored_key = f'uploads/{file_id}.{ext}'
    conditions = _build_presign_conditions(content_type, max_size_bytes)
    response = client.generate_presigned_post(Bucket=settings.S3_BUCKET, Key=stored_key, Fields={'Content-Type': content_type, 'x-amz-server-side-encryption': 'AES256'}, Conditions=conditions, ExpiresIn=expires_in)
    return {'upload_url': response['url'], 'fields': response['fields'], 'stored_key': stored_key, 'expires_in': expires_in}
