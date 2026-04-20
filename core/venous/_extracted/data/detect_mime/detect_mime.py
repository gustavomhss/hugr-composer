from __future__ import annotations


def detect_mime(file: BinaryIO) -> str | None:
    """Read the first 8 KB and detect MIME type via libmagic byte-signature analysis.

    The file pointer is reset to its original position before returning, so
    subsequent reads from the caller are not affected.

    Args:
        file: Readable binary file-like object.

    Returns:
        MIME type string, or ``None`` if libmagic cannot identify the content.
    """
    import magic
    pos = file.tell()
    head = file.read(_HEAD_BYTES)
    file.seek(pos)
    if not head:
        return None
    return magic.from_buffer(head, mime=True)
