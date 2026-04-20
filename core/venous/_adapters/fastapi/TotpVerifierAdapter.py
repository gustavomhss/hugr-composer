"""FastAPI adapter over the `TotpVerifier` primitive.

Attaches a process-wide `StandardTotpVerifier` to `app.state.totp`
and exposes `get_verifier` + a convenience `verify_code()` helper that
maps primitive errors to idiomatic FastAPI responses.

Usage::

    from fastapi import Depends, FastAPI
    from core.venous._adapters.fastapi.TotpVerifierAdapter import install, get_verifier

    app = FastAPI()
    install(app)

    @app.post("/mfa/verify")
    async def verify(code: str, verifier=Depends(get_verifier)): ...
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request

from core.venous.auth.TotpVerifier.TotpVerifier import (
    StandardTotpVerifier,
    TotpInvalidCodeError,
    TotpReplayError,
    TotpVerifier,
)


def install(app: FastAPI, *, digits: int = 6, step_seconds: int = 30) -> StandardTotpVerifier:
    """Attach a `StandardTotpVerifier` to *app*.state.totp and return it."""
    verifier = StandardTotpVerifier(digits=digits, step_seconds=step_seconds)
    app.state.totp = verifier
    return verifier


def get_verifier(request: Request) -> TotpVerifier:
    """FastAPI dependency: resolve the app-wide verifier."""
    return request.app.state.totp  # type: ignore[no-any-return]


def verify_code(verifier: TotpVerifier, *, secret: bytes, code: str, last_step: int | None) -> int:
    """Wrap `verifier.verify()` translating primitive errors to HTTPException."""
    try:
        return verifier.verify(secret, code, last_step)
    except TotpReplayError as exc:
        raise HTTPException(status_code=409, detail="code already used") from exc
    except TotpInvalidCodeError as exc:
        raise HTTPException(status_code=401, detail="invalid code") from exc
