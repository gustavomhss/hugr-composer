from __future__ import annotations


def upload_multipart(file: BinaryIO, stored_key: str, content_type: str) -> dict[str, str]:
    """Upload a file to S3 using multipart upload for large files.

    Reads *file* in ``PART_SIZE_BYTES`` chunks, uploading each part.
    On any error, aborts the multipart upload and re-raises the exception.

    Args:
        file: Readable binary file-like object.
        stored_key: S3 object key for the destination.
        content_type: MIME type for the S3 object.

    Returns:
        Dict with ``ETag`` and ``VersionId`` from the complete response.

    Raises:
        Exception: Any error from S3 after aborting the multipart upload.
    """
    import boto3
    from app.core.config import settings
    client = boto3.client('s3', region_name=settings.AWS_REGION)
    upload_id = _start_multipart(client, settings.S3_BUCKET, stored_key, content_type)
    try:
        parts = _upload_parts(client, file, settings.S3_BUCKET, stored_key, upload_id)
        return _complete_multipart(client, settings.S3_BUCKET, stored_key, upload_id, parts)
    except Exception:
        client.abort_multipart_upload(Bucket=settings.S3_BUCKET, Key=stored_key, UploadId=upload_id)
        raise
