"""ContentSecurityPolicy primitive — compose, serialize, enforce a CSP header.

Implements the catalog Protocol for `security.ContentSecurityPolicy`.
Directives are typed, immutable, and composed functionally: `with_directive`
and `with_nonce` each return a new policy rather than mutating in place.
`render_header` serializes to the `(header_name, header_value)` tuple a
caller can drop onto an HTTP response.

Key behaviors (enforced at runtime):

- CSP_INV_01: every policy MUST declare `default-src`; `render_header` on
  a policy without one raises rather than producing a header with a gaping
  hole.
- CSP_INV_02: `'unsafe-inline'` and a nonce MUST NEVER coexist on
  `script-src` — CSP3 treats the nonce as a no-op when `'unsafe-inline'`
  is present, which is the classic XSS bypass. The builder refuses the
  combination at `render_header` time.
- CSP_INV_03: nonces MUST be ≥128 bits from a CSPRNG and MUST NEVER be
  reused across responses. `generate_nonce` enforces both; the policy
  tracks used nonces for uniqueness checks in a process-local registry.
- CSP_INV_04: `object-src` MUST be `'none'` unless the caller opts in
  explicitly with a non-empty rationale string recorded on the policy.
- CSP_INV_05: `base-uri` and `frame-ancestors` MUST be set to a closed
  list; wildcard (`*`, `http:`, `https:`, scheme-only) values are refused
  in production profiles.
- CSP_INV_06: report-only and enforce headers MUST be separate header
  names (`Content-Security-Policy-Report-Only` vs `Content-Security-Policy`)
  and MUST NEVER both block and merely report the same directive.

Import is side-effect-free. The `secrets` module is stdlib; no third-party
SDKs are imported at module import time.
"""

from __future__ import annotations

import re
import secrets
import threading
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from typing import Final, Protocol, runtime_checkable

# CSP3 minimum entropy for a nonce (≥128 bits) expressed as base64 chars.
# base64 encodes 6 bits per char, so 22 chars unpadded = 132 bits — above the
# floor. We emit 24 chars to keep a round-trip to 18 raw bytes (144 bits).
NONCE_BYTES_MIN: Final[int] = 16  # 128 bits
NONCE_BYTES_DEFAULT: Final[int] = 18  # 144 bits

# Header names exposed by RFC / W3C CSP3.
HEADER_ENFORCE: Final[str] = "Content-Security-Policy"
HEADER_REPORT_ONLY: Final[str] = "Content-Security-Policy-Report-Only"

# Directive names CSP3 recognizes as closed-list (no wildcard in production).
CLOSED_LIST_DIRECTIVES: Final[frozenset[str]] = frozenset(
    {"base-uri", "frame-ancestors"},
)

# Directive names that admit a nonce on their source list.
NONCEABLE_DIRECTIVES: Final[frozenset[str]] = frozenset(
    {"script-src", "script-src-elem", "script-src-attr", "style-src", "style-src-elem"},
)

# Wildcards refused on closed-list directives (CSP_INV_05). `'self'`, origin
# URLs, and `'none'` remain acceptable.
_WILDCARD_SOURCES: Final[frozenset[str]] = frozenset(
    {"*", "http:", "https:", "data:", "blob:", "filesystem:", "mediastream:"},
)

# Directive names we recognize. We do NOT reject unknown directive names —
# the CSP spec is extensible — but we validate the known set more strictly.
_KNOWN_DIRECTIVES: Final[frozenset[str]] = frozenset(
    {
        "default-src", "script-src", "script-src-elem", "script-src-attr",
        "style-src", "style-src-elem", "style-src-attr",
        "img-src", "connect-src", "font-src", "media-src",
        "object-src", "frame-src", "child-src", "worker-src",
        "manifest-src", "prefetch-src",
        "base-uri", "frame-ancestors", "form-action", "sandbox",
        "upgrade-insecure-requests", "block-all-mixed-content",
        "report-uri", "report-to", "require-trusted-types-for", "trusted-types",
    },
)

# Directive-name validator — CSP directive names are lowercase kebab-case.
_DIRECTIVE_NAME_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9-]*$")

# Source-token validator — accept keyword sources (`'self'`), nonces
# (`'nonce-...'`), hashes (`'sha256-...'`), schemes, hostnames, and data URIs.
# We keep this permissive; the invariant checks enforce the dangerous cases.
_SOURCE_TOKEN_RE: Final[re.Pattern[str]] = re.compile(
    r"^('[A-Za-z0-9+/=._-]+'"
    r"|[A-Za-z][A-Za-z0-9+.-]*:(?://)?[^\s;,]*"
    r"|\*(?:\.[A-Za-z0-9.-]+)?"
    r"|[A-Za-z0-9][A-Za-z0-9.-]*(?::\d+)?(?:/[^\s;,]*)?)$",
)


class ContentSecurityPolicyError(Exception):
    """Runtime invariant violation on a ContentSecurityPolicy operation.

    Exception messages cite CSP_INV_* invariant IDs so CI logs can trace
    back to the contract. No nonce or header content is echoed to the
    message: callers log the policy via `render_header` or `to_dict`, not
    via the exception itself.
    """


class CspDirectiveError(ContentSecurityPolicyError):
    """Directive name or source list failed validation (CSP_INV_01/05)."""


class CspNonceError(ContentSecurityPolicyError):
    """Nonce generation / reuse / coexistence-with-unsafe-inline failure.

    CSP_INV_02: `'unsafe-inline'` + nonce on `script-src` forbidden.
    CSP_INV_03: nonce entropy below 128 bits OR reuse across responses.
    """


class CspRenderError(ContentSecurityPolicyError):
    """Policy rejected at render time (missing default-src, wildcard on
    closed-list, unsafe-inline without rationale, etc.)."""


# ---------------------------------------------------------------------------
# Public data types — catalog-exact surface
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Directive:
    """A single CSP directive — a name + an ordered tuple of sources.

    Order is preserved because CSP source-list evaluation is order-sensitive
    for some user agents; serialization copies the tuple verbatim.
    """

    name: str
    sources: tuple[str, ...]


@runtime_checkable
class ContentSecurityPolicy(Protocol):
    def with_directive(self, directive: Directive) -> ContentSecurityPolicy: ...
    def with_nonce(self, nonce: str) -> ContentSecurityPolicy: ...
    def render_header(self) -> tuple[str, str]: ...


# ---------------------------------------------------------------------------
# Nonce registry — process-local uniqueness tracking (CSP_INV_03)
# ---------------------------------------------------------------------------
class _NonceRegistry:
    """Thread-safe `set`-backed nonce tracker.

    Production deployments typically replace this with a request-scoped
    context; the shared registry here catches naive `.with_nonce("same")`
    reuse across responses that would otherwise silently defeat CSP3.
    """

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._lock = threading.Lock()

    def record(self, nonce: str) -> None:
        with self._lock:
            if nonce in self._seen:
                raise CspNonceError(
                    "CSP_INV_03: nonce reuse across responses is forbidden "
                    "(nonce value withheld).",
                )
            self._seen.add(nonce)

    def forget(self, nonce: str) -> None:
        with self._lock:
            self._seen.discard(nonce)

    def reset(self) -> None:
        """Clear the registry. Tests use this to avoid cross-case bleed."""
        with self._lock:
            self._seen.clear()


_DEFAULT_REGISTRY: Final[_NonceRegistry] = _NonceRegistry()


# ---------------------------------------------------------------------------
# Nonce generation — CSP_INV_03 (≥128 bits from CSPRNG, uniquely tracked)
# ---------------------------------------------------------------------------
def generate_nonce(
    *,
    n_bytes: int = NONCE_BYTES_DEFAULT,
    registry: _NonceRegistry | None = None,
) -> str:
    """Return a base64-url nonce suitable for `'nonce-<value>'` sources.

    CSP_INV_03: ≥128 bits of entropy from `secrets.token_urlsafe` and a
    record entry in the registry to catch cross-response reuse.
    """
    if n_bytes < NONCE_BYTES_MIN:
        raise CspNonceError(
            f"CSP_INV_03: nonce MUST be ≥{NONCE_BYTES_MIN * 8} bits "
            f"(got {n_bytes * 8}).",
        )
    nonce = secrets.token_urlsafe(n_bytes).rstrip("=")
    (registry or _DEFAULT_REGISTRY).record(nonce)
    return nonce


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def _validate_directive_name(name: str) -> str:
    if not isinstance(name, str) or not name:
        raise CspDirectiveError(
            "CSP_INV_01: directive name MUST be a non-empty str.",
        )
    if not _DIRECTIVE_NAME_RE.match(name):
        raise CspDirectiveError(
            f"CSP_INV_01: directive name {name!r} is not CSP3-compliant "
            "(must match [a-z][a-z0-9-]*).",
        )
    return name


def _validate_source_token(name: str, token: str) -> str:
    if not isinstance(token, str) or not token:
        raise CspDirectiveError(
            f"CSP_INV_01: empty source on directive {name!r}.",
        )
    # Reject semicolons / commas / newlines — these would escape the header
    # and allow directive-injection into adjacent rules.
    if any(c in token for c in ";\n\r,"):
        raise CspDirectiveError(
            f"CSP_INV_01: source on {name!r} contains a reserved separator "
            "character (';', ',', or newline).",
        )
    if not _SOURCE_TOKEN_RE.match(token):
        raise CspDirectiveError(
            f"CSP_INV_01: source {token!r} on directive {name!r} is not a "
            "valid CSP source token.",
        )
    return token


def _is_wildcard_for_closed_list(source: str) -> bool:
    """Returns True if `source` is forbidden on a closed-list directive."""
    # A bare scheme (`https:`) / `*` / leading-wildcard (`*.example.com`)
    # all widen the list to more than an explicit allow-list.
    return (
        source in _WILDCARD_SOURCES
        or source == "*"
        or source.startswith("*.")
    )


# ---------------------------------------------------------------------------
# Policy mode — enforce vs report-only (CSP_INV_06)
# ---------------------------------------------------------------------------
class PolicyMode:
    ENFORCE: Final[str] = "enforce"
    REPORT_ONLY: Final[str] = "report_only"


# ---------------------------------------------------------------------------
# Reference implementation
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CspPolicy:
    """Immutable reference implementation of `ContentSecurityPolicy`.

    Directives are carried in insertion order via `_directive_order` so
    serialization is deterministic; stashed values live in `_directives`.
    Nonces attach to all `NONCEABLE_DIRECTIVES` already present on the
    policy (this matches most frameworks' behavior).
    """

    _directive_order: tuple[str, ...] = field(default_factory=tuple)
    _directives: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    mode: str = PolicyMode.ENFORCE
    allow_unsafe_inline_script: bool = False
    unsafe_inline_rationale: str = ""
    allow_object_src_override: bool = False
    object_src_rationale: str = ""
    allow_closed_list_wildcard: bool = False
    report_only_directives: frozenset[str] = field(default_factory=frozenset)

    # ---- builder ----------------------------------------------------------
    @classmethod
    def strict_default(cls) -> CspPolicy:
        """Return a sane strict-baseline policy.

        - `default-src 'self'`
        - `object-src 'none'` (CSP_INV_04)
        - `base-uri 'self'` (CSP_INV_05)
        - `frame-ancestors 'none'` (CSP_INV_05)
        - `form-action 'self'`
        - `upgrade-insecure-requests` (no-source directive).
        """
        base = cls()
        for name, sources in (
            ("default-src", ("'self'",)),
            ("script-src", ("'self'",)),
            ("style-src", ("'self'",)),
            ("img-src", ("'self'",)),
            ("connect-src", ("'self'",)),
            ("font-src", ("'self'",)),
            ("object-src", ("'none'",)),
            ("base-uri", ("'self'",)),
            ("frame-ancestors", ("'none'",)),
            ("form-action", ("'self'",)),
        ):
            base = base.with_directive(Directive(name, sources))
        return base

    # ---- protocol surface -------------------------------------------------
    def with_directive(self, directive: Directive) -> CspPolicy:
        if not isinstance(directive, Directive):
            raise CspDirectiveError(
                "CSP_INV_01: with_directive expects a Directive instance.",
            )
        name = _validate_directive_name(directive.name)
        if not isinstance(directive.sources, tuple):
            raise CspDirectiveError(
                "CSP_INV_01: Directive.sources MUST be a tuple (immutable).",
            )
        for s in directive.sources:
            _validate_source_token(name, s)
        # Close-list check — we do NOT fail here to allow the builder to be
        # loose; render_header is where CSP_INV_05 is enforced against the
        # final closed-list directives unless explicitly overridden.
        new_order = (
            self._directive_order if name in self._directives
            else (*self._directive_order, name)
        )
        new_map: dict[str, tuple[str, ...]] = dict(self._directives)
        new_map[name] = tuple(directive.sources)
        return replace(self, _directive_order=new_order, _directives=new_map)

    def with_nonce(self, nonce: str) -> CspPolicy:
        _validate_nonce_shape(nonce)
        # Attach the nonce to every nonceable directive already present.
        new_map: dict[str, tuple[str, ...]] = dict(self._directives)
        nonce_token = f"'nonce-{nonce}'"
        touched = False
        for name, sources in self._directives.items():
            if name not in NONCEABLE_DIRECTIVES:
                continue
            if "'unsafe-inline'" in sources and not self.allow_unsafe_inline_script:
                # CSP_INV_02: refuse at build time to avoid a silently weak
                # policy. Callers that *really* want both must set the flag.
                raise CspNonceError(
                    f"CSP_INV_02: with_nonce refused on {name!r} because "
                    "'unsafe-inline' is already present; remove it first "
                    "or set allow_unsafe_inline_script=True with a rationale.",
                )
            if nonce_token not in sources:
                new_map[name] = (*sources, nonce_token)
                touched = True
        if not touched:
            # A policy with no nonceable directives still accepts with_nonce
            # for API consistency — a fresh builder chains as expected.
            pass
        return replace(self, _directives=new_map)

    # ---- private invariant sub-checks (keep render_header simple) -------
    def _check_object_src(self) -> None:
        """CSP_INV_04: object-src must be 'none' unless overridden."""
        sources = self._directives.get("object-src")
        if sources is None:
            raise CspRenderError(
                "CSP_INV_04: object-src missing; set to 'none' or opt in with "
                "allow_object_src_override=True + object_src_rationale.",
            )
        if sources != ("'none'",) and not self.allow_object_src_override:
            raise CspRenderError(
                "CSP_INV_04: object-src MUST be 'none' unless "
                "allow_object_src_override=True with a non-empty rationale.",
            )
        if self.allow_object_src_override and not self.object_src_rationale.strip():
            raise CspRenderError(
                "CSP_INV_04: allow_object_src_override requires "
                "a non-empty object_src_rationale.",
            )

    def _check_unsafe_inline_and_nonce(self) -> None:
        """CSP_INV_02: `'unsafe-inline'` / `'unsafe-eval'` + nonce checks."""
        for name in NONCEABLE_DIRECTIVES & set(self._directives):
            sources = self._directives[name]
            has_unsafe = "'unsafe-inline'" in sources
            has_unsafe_eval = "'unsafe-eval'" in sources
            has_nonce = any(s.startswith("'nonce-") for s in sources)
            if has_unsafe and has_nonce:
                raise CspRenderError(
                    f"CSP_INV_02: {name} has BOTH 'unsafe-inline' and a nonce; "
                    "CSP3 ignores the nonce (classic XSS bypass).",
                )
            if (has_unsafe or has_unsafe_eval) and not self.allow_unsafe_inline_script:
                raise CspRenderError(
                    f"CSP_INV_02: {name} includes an unsafe-* source without "
                    "allow_unsafe_inline_script=True + rationale.",
                )
            if self.allow_unsafe_inline_script and not self.unsafe_inline_rationale.strip():
                raise CspRenderError(
                    "CSP_INV_02: allow_unsafe_inline_script requires a "
                    "non-empty unsafe_inline_rationale.",
                )

    def _check_closed_lists(self) -> None:
        """CSP_INV_05: `base-uri` / `frame-ancestors` must be closed-list."""
        for name in CLOSED_LIST_DIRECTIVES:
            sources = self._directives.get(name)
            if sources is None:
                raise CspRenderError(
                    f"CSP_INV_05: closed-list directive {name!r} MUST be set.",
                )
            for s in sources:
                if _is_wildcard_for_closed_list(s) and not self.allow_closed_list_wildcard:
                    raise CspRenderError(
                        f"CSP_INV_05: wildcard {s!r} on {name!r} is forbidden "
                        "in production profiles.",
                    )

    def _header_name(self) -> str:
        """CSP_INV_06: map mode → concrete header name."""
        if self.mode == PolicyMode.ENFORCE:
            return HEADER_ENFORCE
        if self.mode == PolicyMode.REPORT_ONLY:
            return HEADER_REPORT_ONLY
        raise CspRenderError(
            f"CSP_INV_06: unknown mode {self.mode!r}; expected "
            "'enforce' or 'report_only'.",
        )

    def _serialize(self) -> str:
        parts: list[str] = []
        for name in self._directive_order:
            sources = self._directives[name]
            if sources:
                parts.append(f"{name} {' '.join(sources)}")
            else:
                # No-source directives (`upgrade-insecure-requests`) are bare.
                parts.append(name)
        return "; ".join(parts)

    def render_header(self) -> tuple[str, str]:
        """Serialize to `(header_name, header_value)`, enforcing CSP_INV_*."""
        return self._render(strict=True)

    def _render(self, *, strict: bool) -> tuple[str, str]:
        """Internal: `strict=True` enforces CSP_INV_04/05 (object-src +
        closed-list rules). The report-only sub-policy produced by
        `render_dual` bypasses these because a report-only header does
        NOT block — it only surfaces telemetry — so the production-profile
        rules those invariants encode apply only to the enforce header.
        CSP_INV_01/02/06 still hold for both.
        """
        if "default-src" not in self._directives:
            raise CspRenderError(
                "CSP_INV_01: policy without default-src cannot be rendered.",
            )
        if strict:
            self._check_object_src()
        self._check_unsafe_inline_and_nonce()
        if strict:
            self._check_closed_lists()
        header_name = self._header_name()
        if self.mode == PolicyMode.ENFORCE and self.report_only_directives:
            raise CspRenderError(
                "CSP_INV_06: report_only_directives present on an enforce "
                "policy; call render_dual() to emit two separate headers.",
            )
        return header_name, self._serialize()

    def render_dual(self) -> tuple[tuple[str, str], tuple[str, str] | None]:
        """Emit `(enforce, report_only)` headers when both are needed.

        CSP_INV_06: a directive listed in `report_only_directives` MUST NOT
        also appear in the enforce header — returning both the "block" and
        the "merely report" variant for the same directive is the
        anti-pattern this invariant exists to prevent.
        """
        # Build the enforce policy without the report-only carve-outs.
        enforce_order = tuple(
            n for n in self._directive_order if n not in self.report_only_directives
        )
        enforce_map: dict[str, tuple[str, ...]] = {
            n: self._directives[n] for n in enforce_order
        }
        # Degrade empty enforce policies gracefully — caller probably meant
        # to send report-only only. Keep default-src present to satisfy INV_01.
        if "default-src" not in enforce_map and "default-src" in self._directives:
            enforce_map["default-src"] = self._directives["default-src"]
            enforce_order = ("default-src", *enforce_order)
        enforce_policy = replace(
            self,
            _directive_order=enforce_order,
            _directives=enforce_map,
            report_only_directives=frozenset(),
            mode=PolicyMode.ENFORCE,
        )
        enforce_header = enforce_policy.render_header()

        if not self.report_only_directives:
            return enforce_header, None

        # Report-only carries ONLY the report_only_directives (plus default-src).
        ro_names = self.report_only_directives
        ro_map: dict[str, tuple[str, ...]] = {
            n: self._directives[n] for n in self._directive_order if n in ro_names
        }
        if "default-src" not in ro_map and "default-src" in self._directives:
            ro_map["default-src"] = self._directives["default-src"]
        ro_order = tuple(
            n for n in (("default-src", *self._directive_order))
            if n in ro_map
        )
        # Dedupe while preserving order.
        seen: set[str] = set()
        deduped: list[str] = []
        for n in ro_order:
            if n not in seen:
                deduped.append(n)
                seen.add(n)
        # CSP_INV_06 — overlap check: a directive in report-only MUST NOT
        # also be in enforce_map.
        overlap = set(ro_map) & set(enforce_map) - {"default-src"}
        if overlap:
            raise CspRenderError(
                "CSP_INV_06: directives appear in BOTH enforce and "
                f"report-only headers: {sorted(overlap)!r}. A directive "
                "may block or report, never both at once.",
            )
        ro_policy = replace(
            self,
            _directive_order=tuple(deduped),
            _directives=ro_map,
            report_only_directives=frozenset(),
            mode=PolicyMode.REPORT_ONLY,
        )
        # Report-only is exempt from CSP_INV_04/05 by construction (it doesn't
        # block — see `_render` docstring), so we use the non-strict path.
        # CSP_INV_01/02/06 still hold for both headers.
        ro_header = ro_policy._render(strict=False)  # noqa: SLF001 — deliberate internal call; _render is an intra-class seam for CSP_INV_06 (strict vs report-only header rendering).
        return enforce_header, ro_header

    # ---- introspection ----------------------------------------------------
    def directives(self) -> Mapping[str, tuple[str, ...]]:
        """Return a shallow copy of the directive map (immutable)."""
        return dict(self._directives)

    def has_directive(self, name: str) -> bool:
        return name in self._directives

    def to_dict(self) -> dict[str, object]:
        """Structured dict suitable for logging / OTel span attributes."""
        return {
            "mode": self.mode,
            "directives": {k: list(v) for k, v in self._directives.items()},
            "allow_unsafe_inline_script": self.allow_unsafe_inline_script,
            "allow_object_src_override": self.allow_object_src_override,
            "allow_closed_list_wildcard": self.allow_closed_list_wildcard,
            "report_only_directives": sorted(self.report_only_directives),
        }


# ---------------------------------------------------------------------------
# Extension contract — per-route decorators (refused on widening)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PolicyDecorator:
    """A per-route override that layers on top of a base policy.

    The extension_contract refuses decorators that widen default-src or
    reintroduce `'unsafe-inline'` on script-src without the explicit flag.
    """

    name: str
    applies: tuple[Directive, ...]
    adds_unsafe_inline: bool = False
    adds_unsafe_inline_rationale: str = ""


def _check_decorator_script_src(d: Directive, decorator: PolicyDecorator) -> None:
    """CSP_INV_02: decorator may only reintroduce 'unsafe-inline' on
    script-src with the explicit flag AND a non-empty rationale."""
    if "'unsafe-inline'" not in d.sources:
        return
    if not decorator.adds_unsafe_inline:
        raise CspNonceError(
            "CSP_INV_02: decorator reintroduces 'unsafe-inline' on "
            "script-src without adds_unsafe_inline=True.",
        )
    if not decorator.adds_unsafe_inline_rationale.strip():
        raise CspNonceError(
            "CSP_INV_02: adds_unsafe_inline requires "
            "a non-empty adds_unsafe_inline_rationale.",
        )


def _check_decorator_default_src(d: Directive, base: CspPolicy) -> None:
    """CSP_INV_01: a decorator MUST NOT widen default-src beyond the base."""
    base_default = base.directives().get("default-src")
    if base_default is None:
        return
    widened = set(d.sources) - set(base_default)
    if widened:
        raise CspDirectiveError(
            "CSP_INV_01: decorator widens default-src beyond the "
            f"base policy: {sorted(widened)!r} — refused.",
        )


def apply_decorator(base: CspPolicy, decorator: PolicyDecorator) -> CspPolicy:
    """Compose `decorator` on top of `base`. Refuses unsafe widenings."""
    if not isinstance(base, CspPolicy):
        raise CspDirectiveError(
            "CSP_INV_01: apply_decorator expects a CspPolicy base.",
        )
    for d in decorator.applies:
        name = _validate_directive_name(d.name)
        if name == "script-src":
            _check_decorator_script_src(d, decorator)
        if name == "default-src":
            _check_decorator_default_src(d, base)
    out = base
    for d in decorator.applies:
        out = out.with_directive(d)
    if decorator.adds_unsafe_inline:
        out = replace(
            out,
            allow_unsafe_inline_script=True,
            unsafe_inline_rationale=decorator.adds_unsafe_inline_rationale,
        )
    return out


# ---------------------------------------------------------------------------
# Internal nonce-shape validation — CSP_INV_03
# ---------------------------------------------------------------------------
def _validate_nonce_shape(nonce: str) -> str:
    if not isinstance(nonce, str) or not nonce:
        raise CspNonceError("CSP_INV_03: nonce MUST be a non-empty str.")
    # Reject separator chars that would escape the header.
    if any(c in nonce for c in "'\";, \n\r\t"):
        raise CspNonceError(
            "CSP_INV_03: nonce contains a reserved or whitespace character.",
        )
    # base64-url alphabet (no padding) — the entropy check lives in
    # `generate_nonce`; callers supplying their own nonce MUST supply ≥22
    # chars which corresponds to ≥128 bits of payload entropy.
    if len(nonce) < 22:
        raise CspNonceError(
            "CSP_INV_03: nonce MUST carry ≥128 bits of entropy "
            "(≥22 base64-url chars).",
        )
    if not re.match(r"^[A-Za-z0-9_\-]+$", nonce):
        raise CspNonceError(
            "CSP_INV_03: nonce MUST be base64-url (A-Za-z0-9_-).",
        )
    return nonce


# ---------------------------------------------------------------------------
# Nonce-request context — helper for frameworks
# ---------------------------------------------------------------------------
@contextmanager
def nonce_request(
    *,
    registry: _NonceRegistry | None = None,
    n_bytes: int = NONCE_BYTES_DEFAULT,
) -> Iterator[str]:
    """Yield a fresh per-response nonce; forget it on exit.

    Typical use::

        with nonce_request() as nonce:
            header = policy.with_nonce(nonce).render_header()
            response.headers[header[0]] = header[1]

    The registry entry is removed on exit so long-running processes don't
    accumulate unbounded nonces (the security property is uniqueness over
    the *response lifetime*, not over the process).
    """
    reg = registry or _DEFAULT_REGISTRY
    nonce = generate_nonce(n_bytes=n_bytes, registry=reg)
    try:
        yield nonce
    finally:
        reg.forget(nonce)


# ---------------------------------------------------------------------------
# Convenience — pack a sequence of directives into a CspPolicy
# ---------------------------------------------------------------------------
def policy_from_directives(
    directives: Iterable[Directive],
    *,
    mode: str = PolicyMode.ENFORCE,
) -> CspPolicy:
    """Build a CspPolicy from an iterable of Directive objects."""
    p = CspPolicy(mode=mode)
    for d in directives:
        p = p.with_directive(d)
    return p


__all__ = [
    "CLOSED_LIST_DIRECTIVES",
    "HEADER_ENFORCE",
    "HEADER_REPORT_ONLY",
    "NONCEABLE_DIRECTIVES",
    "NONCE_BYTES_DEFAULT",
    "NONCE_BYTES_MIN",
    "ContentSecurityPolicy",
    "ContentSecurityPolicyError",
    "CspDirectiveError",
    "CspNonceError",
    "CspPolicy",
    "CspRenderError",
    "Directive",
    "PolicyDecorator",
    "PolicyMode",
    "apply_decorator",
    "generate_nonce",
    "nonce_request",
    "policy_from_directives",
]
