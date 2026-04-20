"""Hypothesis state-machine exploration of TokenIntrospector cache lifecycle."""

from __future__ import annotations

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from TokenIntrospector import (
    CachingTokenIntrospector,
    InvalidTokenError,
    IssuerConfig,
    SigningKey,
    StaticIntrospectionEndpoint,
    StaticJwksFetcher,
)

ISSUER = "https://sm.example.com"
AUD = "sm-aud"
SECRET = b"state-machine-secret-32-bytes-min-len!!"
EXP = 1_700_000_500
TTL = 30


class TokenIntrospectorMachine(RuleBasedStateMachine):
    @initialize()
    def setup(self) -> None:
        self.clock_box = [1_700_000_000.0]
        fetcher = StaticJwksFetcher({
            ISSUER: [SigningKey(kid="k", algorithm="HS256", secret=SECRET)],
        })
        self.endpoint = StaticIntrospectionEndpoint()
        self.ti = CachingTokenIntrospector(
            issuers={ISSUER: IssuerConfig(
                issuer=ISSUER, allowed_algorithms=frozenset({"HS256"}),
            )},
            jwks_fetcher=fetcher,
            introspection_endpoint=self.endpoint,
            introspection_ttl_s=TTL,
            clock=lambda: self.clock_box[0],
        )
        self.revoked: set[str] = set()
        self.known_tokens: set[str] = set()
        for name in ("tokA", "tokB", "tokC"):
            self.endpoint.set(name, {
                "active": True, "sub": f"sub-{name}", "iss": ISSUER,
                "aud": AUD, "exp": EXP,
            })
            self.known_tokens.add(name)

    @rule(name=st.sampled_from(("tokA", "tokB", "tokC")))
    def introspect_op(self, name: str) -> None:
        try:
            self.ti.introspect(name, AUD)
        except InvalidTokenError:
            # Expected when token revoked or expired.
            pass

    @rule(name=st.sampled_from(("tokA", "tokB", "tokC")))
    def revoke_op(self, name: str) -> None:
        self.ti.revoke(name)
        self.revoked.add(name)

    @rule(delta=st.integers(min_value=1, max_value=40))
    def advance_clock(self, delta: int) -> None:
        self.clock_box[0] += float(delta)

    @invariant()
    def revoked_never_surfaces_cached(self) -> None:
        if not hasattr(self, "ti"):
            return
        for t in self.revoked:
            try:
                self.ti.introspect(t, AUD)
            except InvalidTokenError:
                continue
            raise AssertionError(
                f"TI-INV-06 violated: revoked token {t!r} returned claims."
            )

    @invariant()
    def expired_never_surfaces(self) -> None:
        if not hasattr(self, "ti"):
            return
        if self.clock_box[0] >= EXP:
            for t in self.known_tokens:
                try:
                    self.ti.introspect(t, AUD)
                except InvalidTokenError:
                    continue
                raise AssertionError(
                    f"TI-INV-03 violated: expired token {t!r} surfaced claims."
                )

    @invariant()
    def cache_size_bounded(self) -> None:
        if not hasattr(self, "ti"):
            return
        assert self.ti.introspection_cache_size <= len(self.known_tokens)


TestTokenIntrospectorMachine = TokenIntrospectorMachine.TestCase
