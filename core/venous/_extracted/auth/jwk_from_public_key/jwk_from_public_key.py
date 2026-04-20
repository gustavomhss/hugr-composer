from __future__ import annotations
from typing import Any


def jwk_from_public_key(public_key: Any) -> dict[str, Any]:
    """Export a public key as a JWK dict (EC P-256).

    Args:
        public_key: A cryptography EC public key object.

    Returns:
        JWK dict with kty, crv, x, y fields.
    """
    import base64
    from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePublicKey
    if not isinstance(public_key, EllipticCurvePublicKey):
        raise TypeError('Only EC public keys are supported')
    nums = public_key.public_numbers()

    def _b64(n: int, length: int=32) -> str:
        return base64.urlsafe_b64encode(n.to_bytes(length, 'big')).rstrip(b'=').decode()
    return {'kty': 'EC', 'crv': 'P-256', 'x': _b64(nums.x), 'y': _b64(nums.y)}
