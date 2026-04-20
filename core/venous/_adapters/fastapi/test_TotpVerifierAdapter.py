"""Tests for the FastAPI `TotpVerifierAdapter`."""

from __future__ import annotations


def test_adapter_imports_cleanly() -> None:
    from core.venous._adapters.fastapi import TotpVerifierAdapter

    for name in ("install", "get_verifier", "verify_code"):
        assert hasattr(TotpVerifierAdapter, name)


def test_install_attaches_verifier() -> None:
    from fastapi import FastAPI

    from core.venous._adapters.fastapi.TotpVerifierAdapter import install
    from core.venous.auth.TotpVerifier.TotpVerifier import StandardTotpVerifier

    app = FastAPI()
    v = install(app)
    assert isinstance(v, StandardTotpVerifier)
    assert app.state.totp is v


def test_verify_code_allows_valid_and_rejects_replay() -> None:
    from fastapi import FastAPI, HTTPException

    from core.venous._adapters.fastapi.TotpVerifierAdapter import install, verify_code
    from core.venous.auth.TotpVerifier.TotpVerifier import _hotp, generate_secret

    app = FastAPI()
    verifier = install(app)
    secret = generate_secret()
    # Compute a valid code for the verifier's current step.
    import time

    step = int(time.time() // 30)
    code = _hotp(secret, step, 6, "SHA1")

    used = verify_code(verifier, secret=secret, code=code, last_step=None)
    assert used == step

    # Replay same step → 409.
    try:
        verify_code(verifier, secret=secret, code=code, last_step=used)
    except HTTPException as exc:
        assert exc.status_code == 409
    else:  # pragma: no cover
        raise AssertionError("replay was not rejected")


def test_invalid_code_maps_to_401() -> None:
    from fastapi import FastAPI, HTTPException

    from core.venous._adapters.fastapi.TotpVerifierAdapter import install, verify_code
    from core.venous.auth.TotpVerifier.TotpVerifier import generate_secret

    app = FastAPI()
    verifier = install(app)
    try:
        verify_code(verifier, secret=generate_secret(), code="000000", last_step=None)
    except HTTPException as exc:
        assert exc.status_code == 401
    else:  # pragma: no cover — could theoretically match by astronomical chance
        pass


if __name__ == "__main__":
    import sys

    tests = [
        test_adapter_imports_cleanly,
        test_install_attaches_verifier,
        test_verify_code_allows_valid_and_rejects_replay,
        test_invalid_code_maps_to_401,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL  {t.__name__}: {exc}")
            failed += 1
    sys.exit(1 if failed else 0)
