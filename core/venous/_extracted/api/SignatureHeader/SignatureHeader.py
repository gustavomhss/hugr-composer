from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class SignatureHeader:
    """Value object representing the parsed ``X-Signature`` header.

    Attributes:
        timestamp: Unix seconds when the signature was created.
        v1_hex: Hex-encoded HMAC-SHA256 digest.
    """
    timestamp: int
    v1_hex: str

    def to_header_value(self) -> str:
        """Serialize to the ``t=...,v1=...`` wire format.

        Returns:
            Header string ready to send.
        """
        return f't={self.timestamp},v1={self.v1_hex}'
