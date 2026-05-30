"""Regression tests for R5-O4-C2 — Apple id_token signature verification.

Source: Round-5 Opus juror ``acdd867db23e99170`` flagged that the
``_parse_apple_id_token`` helper in the generated ``app/auth/social.py``
base64-decoded the JWT payload **without verifying the signature**, so
any attacker who could reach ``GET /auth/apple/callback`` with a
self-crafted id_token (any ``sub``, any ``email``) took over the
matching account → direct ATO.

These tests:

  1. Run ``add_social_login`` against a fresh fixture project.
  2. Load the generated ``app.auth.social`` module.
  3. Synthesize id_tokens against a test RSA keypair and seed the
     module's JWKS cache so we never hit the network.
  4. Assert:

     - BAD-01: Unsigned ("alg=none" / empty signature) token rejected.
     - BAD-02: Token signed with the WRONG key rejected.
     - BAD-03: Token with the WRONG ``iss`` rejected.
     - BAD-04: Token with the WRONG ``aud`` rejected.
     - BAD-05: Token with expired ``exp`` rejected.
     - BAD-06: Token whose ``kid`` is not in the JWKS rejected.
     - BAD-07: Malformed token (not three dots) rejected.
     - GOOD-01: Correctly-signed, well-claimed token passes and the
       returned ``SocialUserInfo`` carries the verified ``sub``.

Run with::

    PYTHONPATH=. pytest adapt/extend/auth_access/test_add_social_login_apple_jwt.py -v
"""

from __future__ import annotations

import base64
import importlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("ENVIRONMENT", "local")
os.environ.setdefault("SECRET_KEY", "apple-jwt-regression-test-secret-key-ok!")
os.environ.setdefault("RATE_LIMITING_ENABLED", "false")
os.environ.setdefault("APPLE_CLIENT_ID", "com.example.test")
os.environ.pop("REDIS_URL", None)

# These libs ship with the generated project (PyJWT pulled in by
# ``with_auth=True`` in generators.orchestrator; cryptography is a
# transitive dep of pwdlib[argon2]). We import them at top level here
# because the test itself is the synthesizer of well-formed JWTs —
# the SUT (the generated template) still imports them lazily.
import jwt as pyjwt  # PyJWT
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

# ---------------------------------------------------------------------------
# Shared fixture project + loaded social module
# ---------------------------------------------------------------------------

_TMPDIR: tempfile.TemporaryDirectory | None = None
_SOCIAL_MOD = None


def _build_social_module():
    """Generate a fixture project, apply add_social_login, import social.py.

    Returns:
        The imported ``app.auth.social`` module from the generated project.
    """
    global _TMPDIR, _SOCIAL_MOD
    if _SOCIAL_MOD is not None:
        return _SOCIAL_MOD

    from adapt.contracts import ToolInput
    from adapt.extend.auth_access.add_social_login import add_social_login
    from tests.common.fixture_factory import create_fixture_project

    _TMPDIR = tempfile.TemporaryDirectory()
    project_dir = create_fixture_project(
        name="apple_jwt_regression",
        tmp_dir=Path(_TMPDIR.name),
    )
    result = add_social_login(ToolInput(project_dir=str(project_dir)))
    if result.status != "success":
        raise RuntimeError(f"add_social_login failed: {result.error}")

    key = str(project_dir)
    if key not in sys.path:
        sys.path.insert(0, key)
    # Drop any cached app.* modules from prior fixtures.
    for mod in list(sys.modules):
        if mod == "app" or mod.startswith("app."):
            del sys.modules[mod]
    _SOCIAL_MOD = importlib.import_module("app.auth.social")
    return _SOCIAL_MOD


# ---------------------------------------------------------------------------
# JWKS / JWT synthesis helpers
# ---------------------------------------------------------------------------


def _b64u_uint(n: int) -> str:
    """Base64url-encode a positive integer the way RFC 7518 wants."""
    blen = (n.bit_length() + 7) // 8
    raw = n.to_bytes(blen, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _make_jwk(pubkey, kid: str) -> dict:
    """Convert an RSA public key into a JWK dict with the given kid."""
    nums = pubkey.public_numbers()
    return {
        "kty": "RSA",
        "alg": "RS256",
        "use": "sig",
        "kid": kid,
        "n": _b64u_uint(nums.n),
        "e": _b64u_uint(nums.e),
    }


def _gen_keypair():
    """Generate an RSA-2048 keypair for one test session."""
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return priv, pem


def _sign_jwt(pem: bytes, kid: str, claims: dict) -> str:
    """Sign a JWT with RS256 using the supplied PEM private key."""
    return pyjwt.encode(
        claims,
        pem,
        algorithm="RS256",
        headers={"kid": kid, "alg": "RS256"},
    )


def _unsigned_jwt(kid: str, claims: dict) -> str:
    """Build a JWT-shaped string with `alg=none` and an empty signature.

    PyJWT will refuse to decode this with ``algorithms=['RS256']`` —
    which is exactly what the SUT must do.
    """
    header = {"alg": "none", "typ": "JWT", "kid": kid}

    def _enc(obj: dict) -> str:
        return base64.urlsafe_b64encode(
            json.dumps(obj, separators=(",", ":")).encode()
        ).rstrip(b"=").decode("ascii")

    return f"{_enc(header)}.{_enc(claims)}."


def _seed_jwks(social_mod, jwk: dict) -> None:
    """Seed the in-process JWKS cache so the SUT never touches network."""
    social_mod._jwks_cache.set(
        social_mod._APPLE_JWKS_URL,
        time.monotonic(),
        {"keys": [jwk]},
    )


def _clear_jwks(social_mod) -> None:
    social_mod._jwks_cache.clear()


class _NoNetClient:
    """Stand-in for httpx.AsyncClient — every .get() raises.

    If the SUT actually hits the network for JWKS we want the test to
    fail loudly, not silently exfiltrate. The cache seed should always
    be hit first.
    """

    async def get(self, url):  # noqa: D401
        raise AssertionError(f"SUT tried to fetch JWKS over the network: {url}")


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


_KID = "test-kid-1"
_GOOD_AUD = "com.example.test"  # matches APPLE_CLIENT_ID env above
_GOOD_ISS = "https://appleid.apple.com"


def _good_claims(sub: str = "001234.abc.5678") -> dict:
    now = int(time.time())
    return {
        "iss": _GOOD_ISS,
        "aud": _GOOD_AUD,
        "exp": now + 600,
        "iat": now,
        "sub": sub,
        "email": "victim@example.com",
        "email_verified": "true",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_good_signed_token_passes() -> None:
    """GOOD-01: A properly-signed token with valid claims verifies and
    returns a SocialUserInfo with the verified ``sub``."""
    social_mod = _build_social_module()
    priv, pem = _gen_keypair()
    _seed_jwks(social_mod, _make_jwk(priv.public_key(), _KID))

    token = _sign_jwt(pem, _KID, _good_claims(sub="apple-sub-good"))
    info = await social_mod._verify_apple_id_token(
        _NoNetClient(), {"id_token": token}, "apple"
    )
    assert info.provider == "apple"
    assert info.provider_user_id == "apple-sub-good"
    assert info.email == "victim@example.com"
    assert info.email_verified is True


@pytest.mark.asyncio
async def test_unsigned_token_rejected() -> None:
    """BAD-01: A JWT with ``alg=none`` / empty signature is rejected.

    This is the exact attack the prior implementation enabled: any
    attacker could craft this with their own ``sub`` and take over
    the matching account. The SUT MUST refuse it.
    """
    social_mod = _build_social_module()
    priv, _pem = _gen_keypair()
    _seed_jwks(social_mod, _make_jwk(priv.public_key(), _KID))

    token = _unsigned_jwt(_KID, _good_claims())
    with pytest.raises(ValueError):
        await social_mod._verify_apple_id_token(
            _NoNetClient(), {"id_token": token}, "apple"
        )


@pytest.mark.asyncio
async def test_wrong_key_signed_token_rejected() -> None:
    """BAD-02: Token signed with a key the JWKS does not advertise is rejected."""
    social_mod = _build_social_module()
    priv_apple, _ = _gen_keypair()
    _priv_attacker, pem_attacker = _gen_keypair()
    # JWKS advertises ONLY apple's key.
    _seed_jwks(social_mod, _make_jwk(priv_apple.public_key(), _KID))

    # Attacker signs with their own key but reuses apple's kid.
    token = _sign_jwt(pem_attacker, _KID, _good_claims())
    with pytest.raises(ValueError):
        await social_mod._verify_apple_id_token(
            _NoNetClient(), {"id_token": token}, "apple"
        )


@pytest.mark.asyncio
async def test_wrong_issuer_rejected() -> None:
    """BAD-03: ``iss`` other than appleid.apple.com is rejected."""
    social_mod = _build_social_module()
    priv, pem = _gen_keypair()
    _seed_jwks(social_mod, _make_jwk(priv.public_key(), _KID))

    claims = _good_claims()
    claims["iss"] = "https://evil.example.com"
    token = _sign_jwt(pem, _KID, claims)
    with pytest.raises(ValueError):
        await social_mod._verify_apple_id_token(
            _NoNetClient(), {"id_token": token}, "apple"
        )


@pytest.mark.asyncio
async def test_wrong_audience_rejected() -> None:
    """BAD-04: ``aud`` other than APPLE_CLIENT_ID is rejected."""
    social_mod = _build_social_module()
    priv, pem = _gen_keypair()
    _seed_jwks(social_mod, _make_jwk(priv.public_key(), _KID))

    claims = _good_claims()
    claims["aud"] = "com.someoneelse.app"
    token = _sign_jwt(pem, _KID, claims)
    with pytest.raises(ValueError):
        await social_mod._verify_apple_id_token(
            _NoNetClient(), {"id_token": token}, "apple"
        )


@pytest.mark.asyncio
async def test_expired_token_rejected() -> None:
    """BAD-05: Token with ``exp`` in the past is rejected."""
    social_mod = _build_social_module()
    priv, pem = _gen_keypair()
    _seed_jwks(social_mod, _make_jwk(priv.public_key(), _KID))

    now = int(time.time())
    claims = _good_claims()
    claims["iat"] = now - 7200
    claims["exp"] = now - 3600
    token = _sign_jwt(pem, _KID, claims)
    with pytest.raises(ValueError):
        await social_mod._verify_apple_id_token(
            _NoNetClient(), {"id_token": token}, "apple"
        )


@pytest.mark.asyncio
async def test_unknown_kid_rejected() -> None:
    """BAD-06: Token whose ``kid`` is not in the JWKS is rejected."""
    social_mod = _build_social_module()
    priv, pem = _gen_keypair()
    _seed_jwks(social_mod, _make_jwk(priv.public_key(), _KID))

    # Signed with the right key, but the header kid points elsewhere.
    token = _sign_jwt(pem, "some-other-kid", _good_claims())
    with pytest.raises(ValueError):
        await social_mod._verify_apple_id_token(
            _NoNetClient(), {"id_token": token}, "apple"
        )


@pytest.mark.asyncio
async def test_malformed_token_rejected() -> None:
    """BAD-07: A non-JWT string (wrong dot count) is rejected before any
    JWKS / crypto work."""
    social_mod = _build_social_module()
    _clear_jwks(social_mod)
    with pytest.raises(ValueError):
        await social_mod._verify_apple_id_token(
            _NoNetClient(), {"id_token": "not.a.jwt.really"}, "apple"
        )
    with pytest.raises(ValueError):
        await social_mod._verify_apple_id_token(
            _NoNetClient(), {"id_token": ""}, "apple"
        )


@pytest.mark.asyncio
async def test_missing_apple_client_id_refuses() -> None:
    """SAFETY: If APPLE_CLIENT_ID is unset we refuse to verify rather
    than fall back to ``aud=""`` (which would match a maliciously-empty
    aud claim)."""
    social_mod = _build_social_module()
    priv, pem = _gen_keypair()
    _seed_jwks(social_mod, _make_jwk(priv.public_key(), _KID))

    from app.core.config import settings
    saved = settings.APPLE_CLIENT_ID
    try:
        settings.APPLE_CLIENT_ID = ""
        token = _sign_jwt(pem, _KID, _good_claims())
        with pytest.raises(ValueError):
            await social_mod._verify_apple_id_token(
                _NoNetClient(), {"id_token": token}, "apple"
            )
    finally:
        settings.APPLE_CLIENT_ID = saved


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    import asyncio

    tests = [
        test_good_signed_token_passes,
        test_unsigned_token_rejected,
        test_wrong_key_signed_token_rejected,
        test_wrong_issuer_rejected,
        test_wrong_audience_rejected,
        test_expired_token_rejected,
        test_unknown_kid_rejected,
        test_malformed_token_rejected,
        test_missing_apple_client_id_refuses,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            asyncio.run(t())
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {t.__name__}: {exc!r}")
            failed += 1
    print(f"\n{passed}/{passed + failed} passed")
    if failed:
        sys.exit(1)
