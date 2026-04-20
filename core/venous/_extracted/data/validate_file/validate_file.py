from __future__ import annotations


def validate_file(file: BinaryIO, declared_content_type: str, allowed_types: frozenset[str]) -> str:
    """Detect actual MIME from magic bytes and validate against allowed list.

    Args:
        file: Readable binary file-like object.
        declared_content_type: Client-supplied Content-Type (informational only).
        allowed_types: Set of allowed MIME type strings.

    Returns:
        Detected MIME type (ground truth for DB storage).

    Raises:
        ValueError: If type cannot be detected, is in ``ALWAYS_BLOCKED``,
            or not in ``allowed_types``.
    """
    actual = detect_mime(file)
    if actual is None:
        raise ValueError('Could not detect file type from content (empty or unknown bytes)')
    if actual in ALWAYS_BLOCKED:
        raise ValueError(f"File type '{actual}' is unconditionally blocked")
    if actual not in allowed_types:
        raise ValueError(f"File type '{actual}' is not in the allowed list")
    return actual
