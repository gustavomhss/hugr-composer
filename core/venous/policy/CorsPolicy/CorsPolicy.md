# CorsPolicy

## What it does (plain language)

`CorsPolicy` actively blocks cross-origin browser requests that do not come
from an explicitly allowed origin. It is a deny-by-default evaluator: an
incoming `Origin` header is only echoed back when it matches a bound
matcher, and requested headers are filtered to the configured allowlist.
This closes the classic CORS (Cross-Origin Resource Sharing) footgun where
`*` reflection combined with credentials leaks authenticated session data.

## Regulation anchors

| Standard | Control | Role |
|---|---|---|
| OWASP ASVS 4.0.3 | **V14.5** HTTP Request Header Validation (CORS) | Allowlist-based enforcement, no `*` reflection. |
| OWASP Top 10 2021 | **A05:2021** Security Misconfiguration | CORS hardening baseline. |
| RFC 6454 | Section 4 (The Origin of a URI) | Origin shape: scheme + host + optional port. |
| Fetch Living Standard | CORS protocol | Preflight, `Vary: Origin`, `Access-Control-Max-Age` semantics. |

## API surface (catalog fidelity)

```python
@dataclass(frozen=True)
class CorsDecision:
    allow_origin: str | None
    allow_methods: tuple[str, ...]
    allow_headers: tuple[str, ...]
    allow_credentials: bool
    max_age_seconds: int

class CorsPolicy(Protocol):
    def evaluate(
        self,
        origin: str,
        method: str,
        requested_headers: tuple[str, ...],
    ) -> CorsDecision: ...
```

The reference implementation is `ClosedAllowlistCorsPolicy`, assembled via
the `build_policy(...)` helper.

## Invariants

| ID | Rule |
|---|---|
| CP_INV_01 | `evaluate()` NEVER echoes an `Origin` that is not in the allowlist. `allow_origin=None` is the deny signal. |
| CP_INV_02 | `allow_credentials=True` FORBIDS `*` and requires a single exact origin — enforced at bind and at request. |
| CP_INV_03 | `vary_origin` is pinned True; `vary_origin=False` is refused at bind and again at `evaluate()`. |
| CP_INV_04 | `max_age_seconds ∈ [0, 86400]`; out-of-range and non-int values rejected. |
| CP_INV_05 | Origin literal `'null'` is REJECTED in credentialed mode and is never bindable as an exact entry. |

## Error model

- `CorsPolicyError` (subclass of `ValueError`) on any invariant violation at
  matcher construction, policy construction, or `evaluate()` in credentialed
  mode for `'null'` origin.
- Non-credentialed denies are silent: `CorsDecision(allow_origin=None, ...)`.
  Callers translate this to a 403 or simply omit CORS response headers —
  they MUST NOT fall back to wildcard reflection.

## Security considerations

- **Deny-by-default.** Empty matcher sets are refused. There is no `*`
  reflection path and no regex that can expand to `.*`, `.+`, or the empty
  string; `RegexOriginMatcher` refuses such patterns at bind time.
- **Credentials + exact origin coupling.** Even when a suffix/regex matcher
  accepts an origin, a credentialed decision requires that origin be in the
  exact-origin set. Suffix-only credentialed policies are refused at bind.
- **`Vary: Origin` is mandatory.** Without it, HTTP caches can serve a
  response meant for origin A to a request from origin B. The flag is
  pinned True and re-checked at `evaluate()` to survive frozen-dataclass
  mutation attempts via `object.__setattr__`.
- **`Access-Control-Max-Age` ceiling.** A 24-hour cap bounds the blast
  radius of an accidentally-allowed header/method: attackers cannot pin
  browsers to a stale preflight result for days.
- **`'null'` is hostile.** Sandboxed iframes, `data:` URIs, and local
  `file://` documents all emit `Origin: null`, collapsing distinct
  principals. Credentialed mode refuses it outright.

## Extension contract

Origin matchers are Protocol plugins:

```python
class OriginMatcher(Protocol):
    def matches(self, origin: str) -> bool: ...
```

Built-ins:

- `ExactOriginMatcher(origin)` — exact string match; refuses `*`, `'null'`,
  and non-`scheme://host[:port]` shapes.
- `SuffixTenantMatcher(scheme, suffix)` — `https://<tenant>.<suffix>` with
  `suffix` starting with `.` and containing at least one label separator;
  one level deep, never path/query.
- `RegexOriginMatcher(pattern, review_ticket)` — governance-reviewed
  (ticket required); rejects `.*`, `.+`, empty, and any pattern that
  accepts the empty string.

New matcher types register by implementing `OriginMatcher`.

## Usage

```python
from CorsPolicy import build_policy, CorsPolicyError

policy = build_policy(
    exact_origins=["https://app.example.com"],
    allowed_methods=["GET", "POST", "OPTIONS"],
    allowed_headers=["Content-Type", "Authorization"],
    allow_credentials=True,
    max_age_seconds=3_600,
)

decision = policy.evaluate(
    origin="https://app.example.com",
    method="OPTIONS",
    requested_headers=("Content-Type", "Authorization"),
)

if decision.allow_origin is None:
    # Deny — do NOT emit CORS headers; return 403 if preflight.
    ...
else:
    response_headers["Access-Control-Allow-Origin"] = decision.allow_origin
    response_headers["Access-Control-Allow-Credentials"] = str(decision.allow_credentials).lower()
    response_headers["Access-Control-Allow-Methods"] = ", ".join(decision.allow_methods)
    response_headers["Access-Control-Allow-Headers"] = ", ".join(decision.allow_headers)
    response_headers["Access-Control-Max-Age"] = str(decision.max_age_seconds)
    response_headers["Vary"] = "Origin"
```

## Provenance

- OWASP ASVS 4.0.3 V14.5 — HTTP Request Header Validation (CORS).
- OWASP Top 10 2021 A05:2021 — Security Misconfiguration.
- RFC 6454 — The Web Origin Concept.
- Fetch Living Standard — CORS protocol.

## Alternatives considered

- **Framework default middleware with `origin='*'`.** Incompatible with
  credentials; leaks authenticated responses to any caller.
- **Nginx / ingress-level CORS.** Cannot inspect auth state or per-tenant
  origin lists; static configuration only.
- **Per-route ad-hoc header writing.** Reinvents the matcher each time;
  the single-line footgun (`response['Access-Control-Allow-Origin'] =
  request.headers['Origin']`) is exactly what this primitive removes.

## Compose with:

- **Browser edge hardening** → `RouterPipeline` + `ContentSecurityPolicy`
  CORS + CSP compose into one edge policy: cross-origin requests are rejected and inline-script injection is blocked at render time.

- **No `*` with credentials** → `CsrfGuard` + `RequestGuard`
  Credentialed routes never reflect `*`; CSRF binds the request to the session and Guard authorizes it — three checks, one decision.

- **Preflight caching** → `MiddlewarePipeline` + `CorrelationContext`
  Preflight decisions are cacheable and logged with correlation; operators see which origins actually hit the service.
