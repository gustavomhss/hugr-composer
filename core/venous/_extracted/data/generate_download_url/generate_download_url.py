from __future__ import annotations


def generate_download_url(stored_key: str, expires_in: int=3600) -> str:
    """Return a presigned GET URL for an S3 object.

    Args:
        stored_key: S3 object key.
        expires_in: URL TTL in seconds.

    Returns:
        Presigned GET URL string.

    Raises:
        RuntimeError: If the boto3 presign call fails.
    """
    import boto3
    from botocore.exceptions import ClientError
    from app.core.config import settings
    client = boto3.client('s3', region_name=settings.AWS_REGION)
    try:
        return client.generate_presigned_url('get_object', Params={'Bucket': settings.S3_BUCKET, 'Key': stored_key}, ExpiresIn=expires_in)
    except ClientError as exc:
        raise RuntimeError(f'S3 presign failed: {exc}') from exc
