"""CorsPolicy primitive — deny-by-default CORS evaluator with closed allowlist.

Regulation anchors:

- OWASP ASVS 4.0.3 **V14.5** HTTP Request Header Validation Requirements (CORS).
- OWASP Top 10 2021 **A05:2021** Security Misconfiguration — CORS hardening.

Invariant IDs:

- CP_INV_01: ``evaluate()`` MUST NEVER echo back an ``Origin`` that is not in
  the configured allowlist. A non-matching origin SHALL produce
  ``allow_origin=None`` (deny-by-default).
- CP_INV_02: When ``allow_credentials`` is True, ``allow_origin`` CANNOT be
  ``'*'`` and MUST be a single exact origin string (never the wildcard).
- CP_INV_03: ``Vary: Origin`` MUST be emitted on every per-origin decision.
  Because this primitive always decides per-origin, the flag is pinned True;
  attempting to construct a policy with ``vary_origin=False`` SHALL be
  rejected at bind time.
- CP_INV_04: Preflight caching (``Access-Control-Max-Age``) MUST be
  ``<= 86400`` seconds and MUST NEVER default to unbounded. Negative values
  and values above the cap SHALL be rejected at construction.
- CP_INV_05: Null origin (``'null'``) MUST be rejected in credentialed mode
  because it collapses distinct sandboxed contexts (data: URIs, sandboxed
  iframes, file://) into one principal.

Design notes:

- Deny-by-default: the evaluator returns ``allow_origin=None`` for any input
  not matched by an explicit allowlist entry. There is no ``'*'`` reflection
  path and no regex that can expand to ``.*``.
- Matcher plugins (see ``OriginMatcher``) cover exact, suffix-tenant, and
  governance-reviewed regex patterns. The registry rejects regexes that
  match the empty string or ``.*`` outright.
- Requested-header filtering: preflight responses only list headers that
  intersect the allowlist; unknown headers are silently dropped, never
  reflected.
- Methods: only methods in the bound set are reported in ``allow_methods``;
  ``OPTIONS`` is implicitly supported for preflight but is not echoed unless
  configured.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Final, Protocol, runtime_checkable

MAX_AGE_CAP_SECONDS: Final[int] = 86_400
"""CP_INV_04: hard ceiling on preflight cache (24h)."""

NULL_ORIGIN: Final[str] = "null"
"""CP_INV_05: origin literal emitted by sandboxed contexts."""

WILDCARD: Final[str] = "*"
"""CP_INV_02: wildcard literal — incompatible with credentialed mode."""

_ORIGIN_SCHEME_RE: Final[re.Pattern[str]] = re.compile(
    r"^https?://[A-Za-z0-9._:\-\[\]]+$",
)
"""A conservative origin shape: scheme + host[:port]. Path/query excluded."""

_FORBIDDEN_REGEX_PATTERNS: Final[frozenset[str]] = frozenset({
    "",         # empty pattern matches everything.
    ".*",       # universal wildcard.
    ".+",       # near-universal.
    "^.*$",     # anchored universal.
    "^.+$",     # anchored near-universal.
})
"""Patterns that collapse to an open allowlist — extension_contract forbids."""


class CorsPolicyError(ValueError):
    """Runtime invariant violation on CorsPolicy surface."""


# ---------------------------------------------------------------------------
# Catalog-defined Protocol + decision dataclass (byte-for-byte)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CorsDecision:
    """Result of a single CORS evaluation.

    ``allow_origin=None`` is the deny signal. Callers MUST translate that to
    a 403 (or absent CORS headers) — they MUST NOT fall back to any wildcard.
    """

    allow_origin: str | None
    allow_methods: tuple[str, ...]
    allow_headers: tuple[str, ...]
    allow_credentials: bool
    max_age_seconds: int


@runtime_checkable
class CorsPolicy(Protocol):
    """Catalog-defined Protocol for CORS evaluation."""

    def evaluate(
        self,
        origin: str,
        method: str,
        requested_headers: tuple[str, ...],
    ) -> CorsDecision: ...


# ---------------------------------------------------------------------------
# Origin matcher plugin protocol + built-in matchers
# ---------------------------------------------------------------------------
@runtime_checkable
class OriginMatcher(Protocol):
    """Predicate plugin: does ``origin`` belong to the allowlist?"""

    def matches(self, origin: str) -> bool: ...


@dataclass(frozen=True)
class ExactOriginMatcher:
    """Matches a single fully-qualified origin string (case-sensitive host)."""

    origin: str

    def __post_init__(self) -> None:
        if not isinstance(self.origin, str) or not self.origin.strip():
            raise CorsPolicyError(
                "CP_INV_01: ExactOriginMatcher origin MUST be non-empty.",
            )
        if self.origin == WILDCARD:
            raise CorsPolicyError(
                "CP_INV_01: ExactOriginMatcher refuses the wildcard '*'; "
                "the allowlist MUST be closed.",
            )
        if self.origin == NULL_ORIGIN:
            # The constructor of CredentialedCorsPolicy rejects null again at
            # request time (CP_INV_05); we also forbid binding it as an exact
            # entry because it is never a meaningful trusted principal.
            raise CorsPolicyError(
                "CP_INV_05: origin 'null' MUST NOT be bound as an exact match.",
            )
        if not _ORIGIN_SCHEME_RE.match(self.origin):
            raise CorsPolicyError(
                f"CP_INV_01: origin {self.origin!r} MUST be scheme://host[:port].",
            )

    def matches(self, origin: str) -> bool:
        return origin == self.origin


@dataclass(frozen=True)
class SuffixTenantMatcher:
    """Matches ``https://<tenant>.<suffix>`` where suffix is a closed domain.

    Example: suffix ``.tenants.example.com`` matches
    ``https://acme.tenants.example.com`` but NOT
    ``https://attacker.com/.tenants.example.com`` (path ignored by origin
    shape check) nor ``https://evil.tenants.example.com.attacker.com``.
    """

    scheme: str
    suffix: str

    def __post_init__(self) -> None:
        if self.scheme not in ("http", "https"):
            raise CorsPolicyError(
                f"CP_INV_01: SuffixTenantMatcher scheme MUST be http|https; "
                f"got {self.scheme!r}.",
            )
        if not isinstance(self.suffix, str) or not self.suffix.startswith("."):
            raise CorsPolicyError(
                "CP_INV_01: SuffixTenantMatcher suffix MUST start with '.' "
                "(closed tenant domain).",
            )
        # A bare dot is open — reject.
        if len(self.suffix) < 4 or "." not in self.suffix[1:]:
            raise CorsPolicyError(
                f"CP_INV_01: SuffixTenantMatcher suffix {self.suffix!r} is too "
                "open; MUST be a multi-label closed domain (e.g. '.a.example.com').",
            )

    def matches(self, origin: str) -> bool:
        prefix = f"{self.scheme}://"
        if not origin.startswith(prefix):
            return False
        host = origin[len(prefix):]
        # No path/query/fragment in an Origin header per RFC 6454.
        if any(c in host for c in "/?#"):
            return False
        # Tenant label MUST exist: host must end with suffix AND have a
        # non-empty label before it.
        if not host.endswith(self.suffix):
            return False
        tenant = host[: -len(self.suffix)]
        # Empty tenant or nested subdomain not allowed — keeps the match one
        # level deep (CP_INV_01).
        return bool(tenant) and "." not in tenant


@dataclass(frozen=True)
class RegexOriginMatcher:
    """Governance-reviewed regex matcher — rejects open patterns at bind."""

    pattern: str
    review_ticket: str

    def __post_init__(self) -> None:
        if not isinstance(self.pattern, str):
            raise CorsPolicyError("CP_INV_01: regex pattern MUST be a string.")
        stripped = self.pattern.strip()
        if stripped in _FORBIDDEN_REGEX_PATTERNS:
            raise CorsPolicyError(
                f"CP_INV_01: regex pattern {self.pattern!r} accepts too broad "
                "a set; extension_contract forbids '.*', '.+', and empty.",
            )
        try:
            compiled = re.compile(self.pattern)
        except re.error as exc:
            raise CorsPolicyError(
                f"CP_INV_01: regex pattern {self.pattern!r} is invalid: {exc}.",
            ) from exc
        # Empty-string acceptance is an open allowlist in disguise.
        if compiled.fullmatch(""):
            raise CorsPolicyError(
                f"CP_INV_01: regex pattern {self.pattern!r} matches empty "
                "string; refusing open allowlist.",
            )
        if not isinstance(self.review_ticket, str) or not self.review_ticket.strip():
            raise CorsPolicyError(
                "CP_INV_01: regex matcher MUST cite a review_ticket "
                "(governance review per extension_contract).",
            )

    def matches(self, origin: str) -> bool:
        return re.compile(self.pattern).fullmatch(origin) is not None


# ---------------------------------------------------------------------------
# Reference impl: ClosedAllowlistCorsPolicy
# ---------------------------------------------------------------------------
def _canonical_method(method: str) -> str:
    return method.strip().upper()


def _canonical_header(header: str) -> str:
    return header.strip().lower()


@dataclass(frozen=True)
class ClosedAllowlistCorsPolicy:
    """Reference CorsPolicy implementation.

    Deny-by-default. ``allow_credentials=True`` forces a single exact origin
    in the decision (CP_INV_02) and outright rejects ``null`` origins
    (CP_INV_05). ``vary_origin`` is pinned True to satisfy CP_INV_03.
    """

    matchers: tuple[OriginMatcher, ...]
    allowed_methods: frozenset[str]
    allowed_headers: frozenset[str]
    allow_credentials: bool
    max_age_seconds: int
    vary_origin: bool = True
    # Frozen internal index of exact origins for credentialed-mode fast-path.
    _exact_origins: frozenset[str] = field(default_factory=frozenset, init=False)

    def __post_init__(self) -> None:  # noqa: C901 — CP_INV_01..05 each contribute a guard; collapsing them would hide invariant-specific error messages.
        if not self.matchers:
            raise CorsPolicyError(
                "CP_INV_01: matchers MUST be non-empty; deny-by-default "
                "requires at least one explicit allowlist entry.",
            )
        for m in self.matchers:
            if not isinstance(m, OriginMatcher):
                raise CorsPolicyError(
                    f"CP_INV_01: matcher {m!r} does not implement OriginMatcher.",
                )
        # CP_INV_04: max-age bounds.
        if not isinstance(self.max_age_seconds, int) or isinstance(
            self.max_age_seconds, bool,
        ):
            raise CorsPolicyError(
                "CP_INV_04: max_age_seconds MUST be a non-bool int.",
            )
        if self.max_age_seconds < 0:
            raise CorsPolicyError(
                f"CP_INV_04: max_age_seconds MUST be >= 0; "
                f"got {self.max_age_seconds}.",
            )
        if self.max_age_seconds > MAX_AGE_CAP_SECONDS:
            raise CorsPolicyError(
                f"CP_INV_04: max_age_seconds {self.max_age_seconds} "
                f"exceeds cap {MAX_AGE_CAP_SECONDS}; unbounded caching forbidden.",
            )
        # CP_INV_03: Vary: Origin is mandatory on per-origin decisions.
        if not self.vary_origin:
            raise CorsPolicyError(
                "CP_INV_03: vary_origin MUST be True; per-origin decisions "
                "without Vary: Origin leak data across caches.",
            )
        # Normalize method / header sets — reject empty strings.
        for meth in self.allowed_methods:
            if not isinstance(meth, str) or not meth.strip():
                raise CorsPolicyError(
                    "CP_INV_01: allowed_methods entries MUST be non-empty strings.",
                )
        for hdr in self.allowed_headers:
            if not isinstance(hdr, str) or not hdr.strip():
                raise CorsPolicyError(
                    "CP_INV_01: allowed_headers entries MUST be non-empty strings.",
                )
        # CP_INV_02: credentialed mode needs at least one exact origin and
        # zero wildcard matchers (the matchers we accept never produce '*',
        # so this is an additional belt-and-braces check on the allow set).
        exact: set[str] = {
            m.origin for m in self.matchers if isinstance(m, ExactOriginMatcher)
        }
        if self.allow_credentials and not exact:
            raise CorsPolicyError(
                "CP_INV_02: allow_credentials=True requires at least one "
                "ExactOriginMatcher; wildcard/suffix/regex alone cannot be "
                "safely combined with credentials.",
            )
        # Dataclass is frozen — use object.__setattr__ for the derived index.
        object.__setattr__(self, "_exact_origins", frozenset(exact))

    # -- CorsPolicy protocol ------------------------------------------------
    def evaluate(  # noqa: PLR0911 — CP_INV_01..05 each short-circuit with an explicit deny; reducing returns would obscure which invariant fired.
        self,
        origin: str,
        method: str,
        requested_headers: tuple[str, ...],
    ) -> CorsDecision:
        # CP_INV_03: a per-origin decision requires vary_origin — enforced at
        # __post_init__; re-check defensively so runtime mutation cannot bypass.
        if not self.vary_origin:
            raise CorsPolicyError(
                "CP_INV_03: per-origin evaluate() requires vary_origin=True.",
            )

        denied = CorsDecision(
            allow_origin=None,
            allow_methods=(),
            allow_headers=(),
            allow_credentials=self.allow_credentials,
            max_age_seconds=self.max_age_seconds,
        )

        # CP_INV_01 / CP_INV_05: reject empty / null origin outright in
        # credentialed mode; deny silently in non-credentialed mode.
        if not isinstance(origin, str) or not origin:
            return denied
        if origin == NULL_ORIGIN:
            if self.allow_credentials:
                raise CorsPolicyError(
                    "CP_INV_05: 'null' origin MUST be rejected in credentialed mode.",
                )
            return denied
        if origin == WILDCARD:
            # CP_INV_01: never echo '*'. Treat as denied.
            return denied

        if not _ORIGIN_SCHEME_RE.match(origin):
            return denied

        if not any(m.matches(origin) for m in self.matchers):
            # CP_INV_01: unknown origin — never echoed.
            return denied

        # CP_INV_02: credentialed mode MUST use a single exact origin. The
        # matched value (the incoming origin) MUST be in the exact set.
        if self.allow_credentials and origin not in self._exact_origins:
            # Matched a suffix/regex matcher but not an exact entry — refuse
            # to emit allow_credentials against a non-exact origin.
            return denied

        # Filter requested headers to allowed set (case-insensitive). Never
        # reflect headers we did not declare.
        allowed_hdr_norm = {_canonical_header(h) for h in self.allowed_headers}
        filtered_headers = tuple(
            h for h in requested_headers
            if _canonical_header(h) in allowed_hdr_norm
        )

        # Method check: for a simple request the method must be allowed; for
        # preflight (OPTIONS) we always report the bound method set.
        norm_method = _canonical_method(method)
        if norm_method != "OPTIONS" and norm_method not in {
            _canonical_method(m) for m in self.allowed_methods
        }:
            return denied

        return CorsDecision(
            allow_origin=origin,
            allow_methods=tuple(sorted(_canonical_method(m) for m in self.allowed_methods)),
            allow_headers=filtered_headers,
            allow_credentials=self.allow_credentials,
            max_age_seconds=self.max_age_seconds,
        )


# ---------------------------------------------------------------------------
# Builder helper — keeps call sites honest
# ---------------------------------------------------------------------------
def build_policy(
    *,
    exact_origins: Iterable[str] = (),
    suffix_tenants: Iterable[tuple[str, str]] = (),
    regex_origins: Iterable[tuple[str, str]] = (),
    allowed_methods: Iterable[str] = ("GET", "POST", "OPTIONS"),
    allowed_headers: Iterable[str] = ("Content-Type", "Authorization"),
    allow_credentials: bool = False,
    max_age_seconds: int = 600,
) -> ClosedAllowlistCorsPolicy:
    """Assemble a ClosedAllowlistCorsPolicy from simple kwargs.

    Shapes the primary construction path so callers cannot forget
    ``vary_origin`` (the default True is enforced) or pass a raw ``'*'``.
    """
    matchers: list[OriginMatcher] = [ExactOriginMatcher(o) for o in exact_origins]
    matchers.extend(SuffixTenantMatcher(scheme, suffix) for scheme, suffix in suffix_tenants)
    matchers.extend(
        RegexOriginMatcher(pattern=p, review_ticket=t) for p, t in regex_origins
    )
    return ClosedAllowlistCorsPolicy(
        matchers=tuple(matchers),
        allowed_methods=frozenset(allowed_methods),
        allowed_headers=frozenset(allowed_headers),
        allow_credentials=allow_credentials,
        max_age_seconds=max_age_seconds,
    )


__all__ = [
    "MAX_AGE_CAP_SECONDS",
    "NULL_ORIGIN",
    "WILDCARD",
    "ClosedAllowlistCorsPolicy",
    "CorsDecision",
    "CorsPolicy",
    "CorsPolicyError",
    "ExactOriginMatcher",
    "OriginMatcher",
    "RegexOriginMatcher",
    "SuffixTenantMatcher",
    "build_policy",
]
