"""Hypothesis state-machine exploration of AuthorizationCodeFlow lifecycle."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from AuthorizationCodeFlow import (
    AuthorizationRequest,
    InvalidGrantError,
    InvalidStateError,
    ProviderMetadata,
    create_flow,
)

_PROVIDER = ProviderMetadata(
    authorization_endpoint="https://op.example/authorize",
    token_endpoint="https://op.example/token",
    jwks_uri="https://op.example/jwks",
    code_challenge_methods_supported=("S256",),
)


def _ok_token(_req: Mapping[str, str]) -> Mapping[str, object]:
    return {
        "access_token": "A" * 32,
        "refresh_token": "R" * 32,
        "id_token": "I" * 32,
        "token_type": "Bearer",
        "expires_in": 3600,
    }


class AuthorizationCodeFlowMachine(RuleBasedStateMachine):

    @initialize()
    def setup(self) -> None:
        self.flow = create_flow(
            client_id="c",
            redirect_uri="https://client.example/cb",
            provider=_PROVIDER,
            token_endpoint=_ok_token,
        )
        self.outstanding: list[AuthorizationRequest] = []
        self.redeemed_codes: set[str] = set()

    @rule()
    def begin_op(self) -> None:
        if not hasattr(self, "flow"):
            return
        req = self.flow.begin(scopes=["openid"])
        assert req.state not in {r.state for r in self.outstanding}
        self.outstanding.append(req)

    @rule(code_tag=st.integers(min_value=0, max_value=9))
    def exchange_correct_state(self, code_tag: int) -> None:
        if not hasattr(self, "flow") or not self.outstanding:
            return
        req = self.outstanding.pop(0)
        code = f"code-{code_tag}-{req.state[:6]}"
        if code in self.redeemed_codes:
            try:
                self.flow.exchange(code=code, state=req.state, stored=req)
                raise AssertionError("replay accepted")
            except InvalidGrantError:
                return
        resp = self.flow.exchange(code=code, state=req.state, stored=req)
        assert "access_token" in resp
        self.redeemed_codes.add(code)

    @rule(code_tag=st.integers(min_value=100, max_value=200))
    def exchange_wrong_state(self, code_tag: int) -> None:
        if not hasattr(self, "flow") or not self.outstanding:
            return
        req = self.outstanding[0]
        # Swap to a state we never issued.
        try:
            self.flow.exchange(code=f"x-{code_tag}", state="bogus-state", stored=req)
            raise AssertionError("wrong state accepted")
        except InvalidStateError:
            pass

    @rule(code_tag=st.integers(min_value=0, max_value=9))
    def exchange_tampered_verifier(self, code_tag: int) -> None:
        if not hasattr(self, "flow") or not self.outstanding:
            return
        req = self.outstanding[0]
        tampered = replace(req, code_verifier="evil-verifier-" + str(code_tag))
        try:
            self.flow.exchange(code=f"t-{code_tag}", state=req.state, stored=tampered)
            raise AssertionError("tampered verifier accepted")
        except InvalidGrantError:
            pass

    @invariant()
    def redeemed_count_matches_set(self) -> None:
        if not hasattr(self, "flow"):
            return
        assert self.flow.redeemed_count == len(self.redeemed_codes)

    @invariant()
    def outstanding_states_are_unique(self) -> None:
        states = [r.state for r in self.outstanding]
        assert len(set(states)) == len(states)


# Hypothesis hook
TestAuthorizationCodeFlowMachine = AuthorizationCodeFlowMachine.TestCase
