"""Pure Python primitive: S3Client."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import uuid
from datetime import datetime

class S3Client:
    """Thin wrapper around ``boto3.client('s3')`` with lazy import.

    Attributes:
        _client: The underlying boto3 S3 client (created on first use).
    """

    def __init__(self) -> None:
        """Initialise the S3Client, importing boto3 lazily."""
        import boto3
        kwargs: dict[str, Any] = {'region_name': settings.S3_REGION, 'aws_access_key_id': settings.S3_ACCESS_KEY_ID or None, 'aws_secret_access_key': settings.S3_SECRET_ACCESS_KEY or None}
        if settings.S3_ENDPOINT_URL:
            kwargs['endpoint_url'] = settings.S3_ENDPOINT_URL
        self._client = boto3.client('s3', **kwargs)

    def generate_key(self, filename: str, prefix: str='') -> str:
        """Return a collision-safe object key for *filename*.

        Args:
            filename: Original filename from the client request.
            prefix: Optional path prefix (overrides settings default when
                provided and non-empty).

        Returns:
            Key string formatted as ``{prefix}/{uuid}/{filename}``.
        """
        key_prefix = prefix or settings.S3_KEY_PREFIX
        safe_name = filename.replace('..', '').lstrip('/')
        return f'{key_prefix}/{uuid.uuid4()}/{safe_name}'

    def presigned_upload_url(self, key: str, content_type: str, expiration: int | None=None) -> str:
        """Return a presigned PUT URL for a direct client-to-S3 upload.

        Args:
            key: Object key within the bucket.
            content_type: MIME type the client will send as ``Content-Type``.
            expiration: URL lifetime in seconds (defaults to settings value).

        Returns:
            A presigned URL string the client must PUT to directly.
        """
        exp = expiration if expiration is not None else settings.S3_PRESIGNED_URL_EXPIRATION
        return self._client.generate_presigned_url('put_object', Params={'Bucket': settings.S3_BUCKET_NAME, 'Key': key, 'ContentType': content_type}, ExpiresIn=exp, HttpMethod='PUT')

    def presigned_download_url(self, key: str, expiration: int | None=None) -> str:
        """Return a presigned GET URL for a direct client-to-S3 download.

        Args:
            key: Object key within the bucket.
            expiration: URL lifetime in seconds (defaults to settings value).

        Returns:
            A presigned URL string the client can GET directly.
        """
        exp = expiration if expiration is not None else settings.S3_PRESIGNED_URL_EXPIRATION
        return self._client.generate_presigned_url('get_object', Params={'Bucket': settings.S3_BUCKET_NAME, 'Key': key}, ExpiresIn=exp)

    def delete_object(self, key: str) -> None:
        """Delete an object from the configured bucket.

        Args:
            key: Object key within the bucket.
        """
        self._client.delete_object(Bucket=settings.S3_BUCKET_NAME, Key=key)

    def guess_content_type(self, filename: str) -> str:
        """Guess the MIME type of *filename* using the stdlib.

        Args:
            filename: Filename (with extension).

        Returns:
            MIME type string; falls back to ``'application/octet-stream'``.
        """
        mime, _ = mimetypes.guess_type(filename)
        return mime or 'application/octet-stream'
