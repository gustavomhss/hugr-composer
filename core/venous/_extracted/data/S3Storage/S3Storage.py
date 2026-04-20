from __future__ import annotations


class S3Storage(StorageBackend):
    """S3 storage backend — files uploaded directly by client via presigned URL.

    ``save()`` is a no-op for S3 (client uploads directly); only ``get_url``
    and ``delete`` are called by the application server.
    """

    async def save(self, file_obj: object, content_type: str) -> tuple[str, int]:
        """Not used on S3 path — clients upload directly via presigned POST.

        Args:
            file_obj: Ignored.
            content_type: Ignored.

        Returns:
            Empty stored_key and 0 bytes (S3 confirmation uses HEAD).
        """
        return ('', 0)

    async def get_url(self, stored_key: str, expires_in: int=3600) -> str:
        """Return a presigned GET URL for *stored_key*.

        Args:
            stored_key: S3 object key.
            expires_in: URL TTL in seconds.

        Returns:
            Presigned S3 GET URL.
        """
        import boto3
        from app.core.config import settings
        client = boto3.client('s3', region_name=settings.AWS_REGION)
        return client.generate_presigned_url('get_object', Params={'Bucket': settings.S3_BUCKET, 'Key': stored_key}, ExpiresIn=expires_in)

    async def delete(self, stored_key: str) -> None:
        """Delete *stored_key* from S3.  Uses AES256 server-side encryption bucket.

        Args:
            stored_key: S3 object key.
        """
        import boto3
        from app.core.config import settings
        client = boto3.client('s3', region_name=settings.AWS_REGION)
        client.delete_object(Bucket=settings.S3_BUCKET, Key=stored_key)
