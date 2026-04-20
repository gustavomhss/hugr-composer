"""Hypothesis state-machine exploration of WebAuthnAuthenticator lifecycle."""

from __future__ import annotations

import hashlib

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from WebAuthnAuthenticator import (
    ReferenceWebAuthnAuthenticator,
    WebAuthnInvariantError,
)

RP_ID = "passkeys.example.com"
ORIGIN = "https://passkeys.example.com"
RP_ID_HASH = hashlib.sha256(RP_ID.encode()).digest()


class WebAuthnMachine(RuleBasedStateMachine):

    @initialize()
    def setup(self) -> None:
        self.auth = ReferenceWebAuthnAuthenticator(rp_id=RP_ID, origin=ORIGIN)
        # credential_id -> (user_id, current_sign_count, public_key)
        self.bound: dict[bytes, tuple[bytes, int, bytes]] = {}

    @rule(
        user_tag=st.integers(min_value=0, max_value=4),
        cred_tag=st.integers(min_value=0, max_value=7),
    )
    def register_rule(self, user_tag: int, cred_tag: int) -> None:
        user_id = b"user-" + bytes([user_tag])
        credential_id = b"cred-" + bytes([cred_tag])
        opts = self.auth.begin_registration(user_id=user_id, user_name="u")
        ch = opts["challenge"]
        assert isinstance(ch, bytes)
        response = {
            "clientData": {"type": "webauthn.create", "origin": ORIGIN, "challenge": ch},
            "authenticatorData": RP_ID_HASH + bytes([0x05]) + (0).to_bytes(4, "big"),
            "credentialId": credential_id,
            "publicKey": b"pk-" + user_id,
            "aaguid": b"\x00" * 16,
            "userId": user_id,
        }
        existing = self.bound.get(credential_id)
        if existing is not None and existing[0] != user_id:
            # Cross-user binding MUST be rejected.
            try:
                self.auth.finish_registration(challenge=ch, response=response)
            except WebAuthnInvariantError:
                return
            raise AssertionError("cross-user rebinding accepted")
        self.auth.finish_registration(challenge=ch, response=response)
        self.bound[credential_id] = (user_id, 0, b"pk-" + user_id)

    @rule(
        cred_tag=st.integers(min_value=0, max_value=7),
        bump=st.integers(min_value=1, max_value=10),
    )
    def assert_rule(self, cred_tag: int, bump: int) -> None:
        credential_id = b"cred-" + bytes([cred_tag])
        info = self.bound.get(credential_id)
        if info is None:
            return
        user_id, stored_count, public_key = info
        opts = self.auth.begin_assertion([credential_id])
        ch = opts["challenge"]
        assert isinstance(ch, bytes)
        new_count = stored_count + bump
        resp = {
            "clientData": {"type": "webauthn.get", "origin": ORIGIN, "challenge": ch},
            "authenticatorData": RP_ID_HASH + bytes([0x05]) + new_count.to_bytes(4, "big"),
            "credentialId": credential_id,
            "signatureValid": True,
        }
        returned = self.auth.finish_assertion(
            challenge=ch,
            response=resp,
            stored_public_key=public_key,
            stored_sign_count=stored_count,
        )
        assert returned == new_count
        self.bound[credential_id] = (user_id, new_count, public_key)

    @rule(cred_tag=st.integers(min_value=0, max_value=7))
    def regression_rejected_rule(self, cred_tag: int) -> None:
        credential_id = b"cred-" + bytes([cred_tag])
        info = self.bound.get(credential_id)
        if info is None or info[1] == 0:
            return
        user_id, stored_count, public_key = info
        opts = self.auth.begin_assertion([credential_id])
        ch = opts["challenge"]
        assert isinstance(ch, bytes)
        # regressed count — MUST be rejected
        try:
            self.auth.finish_assertion(
                challenge=ch,
                response={
                    "clientData": {"type": "webauthn.get", "origin": ORIGIN, "challenge": ch},
                    "authenticatorData": RP_ID_HASH + bytes([0x05]) + (1).to_bytes(4, "big"),
                    "credentialId": credential_id,
                    "signatureValid": True,
                },
                stored_public_key=public_key,
                stored_sign_count=stored_count,
            )
        except WebAuthnInvariantError:
            return
        raise AssertionError("counter regression accepted")

    @invariant()
    def credentials_bound_consistently(self) -> None:
        if not hasattr(self, "auth"):
            return
        # No credential_id CAN map to two different user_ids inside the store.
        for credential_id, (user_id, _count, public_key) in self.bound.items():
            rec = self.auth.credentials.get(credential_id)
            assert rec is not None
            assert rec.user_id == user_id
            assert rec.public_key == public_key


TestWebAuthnMachine = WebAuthnMachine.TestCase
