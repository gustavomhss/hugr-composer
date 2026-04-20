"""CurrentPrincipal primitive — immutable, read-only authenticated-identity view.

Implements the catalog shape for `auth.CurrentPrincipal` and installs runtime
invariant checkers. The module performs zero I/O at import.

Invariant IDs cited by this module:

- PRINCIPAL-INV-01: the principal MUST be immutable once constructed; no
  field (subject_id, tenant_id, roles, claims, is_anonymous) CAN be mutated
  by a later middleware or consumer.
- PRINCIPAL-INV-02: a successful auth state NEVER carries is_anonymous=True;
  `subject_id != ""` and `is_anonymous=True` are mutually exclusive, and
  `subject_id == ""` MUST imply `is_anonymous=True`.
- PRINCIPAL-INV-03: `roles` MUST be a `frozenset[str]`; a plain set/list/tuple
  is rejected so a consumer CANNOT add a role at call time to bypass
  authorization.
- PRINCIPAL-INV-04: `subject_id` MUST be a stable, non-whitespace string for
  authenticated principals; rotation / silent re-mapping is FORBIDDEN inside
  the primitive (whitespace-only, null-byte, or control chars rejected).
- PRINCIPAL-INV-05: serialization for logs (`for_log()`) MUST omit raw claim
  values by default; sensitive values SHALL be redacted to a fixed marker.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Mapping
import dataclasses
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
REDACTED: Final[str] = "[REDACTED]"
ANONYMOUS_SUBJECT_ID: Final[str] = ""

# Claim keys whose VALUES MUST be redacted on every for_log() call. Keys are
# lower-cased before matching so callers cannot bypass via casing.
SENSITIVE_CLAIM_KEYS: Final[frozenset[str]] = frozenset({
    "password",
    "pwd",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "id_token",
    "authorization",
    "cookie",
    "set-cookie",
    "api_key",
    "apikey",
    "x-api-key",
    "client_secret",
    "private_key",
    "ssn",
    "credit_card",
    "card_number",
    "cvv",
    "pan",
})

_FORBIDDEN_CHARS: Final[frozenset[str]] = frozenset({"\x00", "\r", "\n", "\t"})


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------
class PrincipalInvariantError(ValueError):
    """Raised when a construction or operation violates a Principal invariant."""


# ---------------------------------------------------------------------------
# Provider protocol — the extension contract
# ---------------------------------------------------------------------------
@runtime_checkable
class PrincipalProvider(Protocol):
    """Contract for the single registered provider that binds a principal.

    Middleware decodes the incoming credential and calls the registered
    provider. Downstream code MUST NOT construct a CurrentPrincipal without
    going through the provider; the reference implementation enforces this at
    the call site, not at the type level.
    """

    def resolve(self, credential: str | None) -> CurrentPrincipal: ...


# ---------------------------------------------------------------------------
# Runtime invariant helpers
# ---------------------------------------------------------------------------
def _validate_subject_id(subject_id: str, *, is_anonymous: bool) -> str:
    """PRINCIPAL-INV-02 / PRINCIPAL-INV-04: subject_id sanity + anonymity parity."""
    if not isinstance(subject_id, str):
        raise PrincipalInvariantError(
            "PRINCIPAL-INV-04: subject_id MUST be a str, "
            f"got {type(subject_id).__name__}."
        )
    if is_anonymous:
        if subject_id != ANONYMOUS_SUBJECT_ID:
            raise PrincipalInvariantError(
                "PRINCIPAL-INV-02: an anonymous principal MUST have "
                f"subject_id='', got {subject_id!r}."
            )
        return subject_id
    if subject_id == ANONYMOUS_SUBJECT_ID:
        raise PrincipalInvariantError(
            "PRINCIPAL-INV-02: a non-anonymous principal MUST have a "
            "non-empty subject_id."
        )
    if subject_id.strip() != subject_id or subject_id.strip() == "":
        raise PrincipalInvariantError(
            "PRINCIPAL-INV-04: subject_id MUST NOT be whitespace-padded or "
            f"whitespace-only, got {subject_id!r}."
        )
    _reject_control_chars(subject_id, field_name="subject_id")
    return subject_id


def _reject_control_chars(value: str, *, field_name: str) -> None:
    """PRINCIPAL-INV-04: forbid C0/C1 controls and Unicode bidi-override chars."""
    # Bidi / format overrides that can disguise identifiers in logs and UIs.
    bidi_overrides = frozenset({
        "\u202a", "\u202b", "\u202c", "\u202d", "\u202e",
        "\u2066", "\u2067", "\u2068", "\u2069",
        "\u200e", "\u200f",
    })
    for ch in value:
        if ch in _FORBIDDEN_CHARS or ord(ch) < 0x20 or 0x7f <= ord(ch) <= 0x9f:
            raise PrincipalInvariantError(
                f"PRINCIPAL-INV-04: {field_name} MUST NOT contain control / "
                f"null bytes; offending codepoint U+{ord(ch):04X}."
            )
        if ch in bidi_overrides or unicodedata.category(ch) in {"Cf", "Cc", "Cs", "Co", "Cn"}:
            raise PrincipalInvariantError(
                f"PRINCIPAL-INV-04: {field_name} MUST NOT contain format / "
                f"bidi-override chars; offending codepoint U+{ord(ch):04X}."
            )


def _validate_tenant_id(tenant_id: str | None) -> str | None:
    """PRINCIPAL-INV-04 supporting: tenant_id is either None or a clean string."""
    if tenant_id is None:
        return None
    if not isinstance(tenant_id, str):
        raise PrincipalInvariantError(
            "PRINCIPAL-INV-04: tenant_id MUST be str or None, "
            f"got {type(tenant_id).__name__}."
        )
    if tenant_id == "" or tenant_id.strip() != tenant_id:
        raise PrincipalInvariantError(
            "PRINCIPAL-INV-04: tenant_id MUST be non-empty and not "
            f"whitespace-padded, got {tenant_id!r}."
        )
    _reject_control_chars(tenant_id, field_name="tenant_id")
    return tenant_id


def _validate_roles(roles: object) -> frozenset[str]:
    """PRINCIPAL-INV-03: roles MUST be a frozenset[str]."""
    if not isinstance(roles, frozenset):
        raise PrincipalInvariantError(
            "PRINCIPAL-INV-03: roles MUST be a frozenset[str]; got "
            f"{type(roles).__name__} (plain set/list/tuple are FORBIDDEN to "
            "prevent call-site mutation)."
        )
    for r in roles:
        if not isinstance(r, str) or r == "" or r.strip() != r:
            raise PrincipalInvariantError(
                "PRINCIPAL-INV-03: every role MUST be a non-empty, "
                f"non-padded str; got {r!r}."
            )
    return roles


def _validate_claims(claims: object) -> Mapping[str, str]:
    """PRINCIPAL-INV-01 / PRINCIPAL-INV-05: claims MUST be an immutable Mapping[str,str]."""
    if not isinstance(claims, Mapping):
        raise PrincipalInvariantError(
            "PRINCIPAL-INV-01: claims MUST be a Mapping[str, str]; got "
            f"{type(claims).__name__}."
        )
    for k, v in claims.items():
        if not isinstance(k, str) or k == "":
            raise PrincipalInvariantError(
                "PRINCIPAL-INV-05: claim keys MUST be non-empty str; "
                f"got {k!r}."
            )
        if not isinstance(v, str):
            raise PrincipalInvariantError(
                "PRINCIPAL-INV-05: claim values MUST be str (serialise "
                f"structured values upstream); got {type(v).__name__} for "
                f"key {k!r}."
            )
    # Freeze into a read-only view so a later caller CANNOT mutate.
    return MappingProxyType(dict(claims))


# ---------------------------------------------------------------------------
# The primitive
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class CurrentPrincipal:
    """Read-only view of the authenticated identity for the active request.

    Construction validates every field against the declared invariants; a
    later middleware CANNOT mutate any field because the dataclass is frozen
    and `roles` is a `frozenset`, `claims` is exposed as a MappingProxy.

    Prefer the factory helpers `anonymous()` and `authenticated(...)` over
    direct construction to avoid anonymity-parity mistakes.

    Invariants are cited by ID in `PrincipalInvariantError` messages.
    """

    subject_id: str
    tenant_id: str | None
    roles: frozenset[str]
    claims: Mapping[str, str] = field(default_factory=dict)
    is_anonymous: bool = False

    def __post_init__(self) -> None:
        _validate_subject_id(self.subject_id, is_anonymous=self.is_anonymous)
        _validate_tenant_id(self.tenant_id)
        _validate_roles(self.roles)
        # PRINCIPAL-INV-01: substitute the validated read-only view.
        object.__setattr__(self, "claims", _validate_claims(self.claims))
        if self.is_anonymous and self.roles:
            raise PrincipalInvariantError(
                "PRINCIPAL-INV-02: an anonymous principal MUST have an empty "
                f"role set; got {sorted(self.roles)!r}."
            )


    # ---- read-only convenience API -----------------------------------------
    def has_role(self, role: str) -> bool:
        """Return True iff the principal carries `role` and is not anonymous."""
        if not isinstance(role, str) or role == "":
            return False
        if self.is_anonymous:
            return False
        return role in self.roles

    def has_any_role(self, roles: Iterable[str]) -> bool:
        """Return True iff the principal carries at least one of `roles`."""
        if self.is_anonymous:
            return False
        return any(isinstance(r, str) and r in self.roles for r in roles)

    def has_all_roles(self, roles: Iterable[str]) -> bool:
        """Return True iff the principal carries every role in `roles`."""
        if self.is_anonymous:
            return False
        needed = tuple(roles)
        if not needed:
            return True
        return all(isinstance(r, str) and r in self.roles for r in needed)

    def claim(self, key: str, default: str | None = None) -> str | None:
        """Return the claim value for `key`, or `default` if absent."""
        if not isinstance(key, str):
            return default
        return self.claims.get(key, default)

    def require_role(self, role: str) -> None:
        """Raise `PermissionError` if the principal lacks `role` or is anonymous."""
        if not self.has_role(role):
            raise PermissionError(role)

    def for_log(self) -> dict[str, object]:
        """PRINCIPAL-INV-05: produce a log-safe dict with claim values redacted.

        Keys of sensitive claims are preserved (so operators can see which
        claim was present), but every value is replaced with `[REDACTED]`.
        Non-sensitive claim values are also redacted by default — callers who
        need a specific claim must read it via `.claim(key)` explicitly.
        """
        redacted_claims: dict[str, str] = {}
        for k in self.claims:
            # Every value redacted by default; key preserved for auditability.
            redacted_claims[k] = REDACTED
        return {
            "subject_id": self.subject_id,
            "tenant_id": self.tenant_id,
            "roles": sorted(self.roles),
            "is_anonymous": self.is_anonymous,
            "claims_keys": sorted(redacted_claims),
            "claims": redacted_claims,
        }

    def __hash__(self) -> int:
        # The frozen dataclass would auto-hash all fields, but `claims` is a
        # MappingProxyType which is unhashable. Hash over a tuple of sorted
        # claim items instead; equality (auto-generated) still compares the
        # mappings structurally so the eq/hash contract is preserved.
        return hash((
            self.subject_id,
            self.tenant_id,
            self.roles,
            tuple(sorted(self.claims.items())),
            self.is_anonymous,
        ))

    def __repr__(self) -> str:
        # Never leak claim values through repr; pair with __str__ for logs.
        return (
            f"CurrentPrincipal(subject_id={self.subject_id!r}, "
            f"tenant_id={self.tenant_id!r}, "
            f"roles={sorted(self.roles)!r}, "
            f"claims_keys={sorted(self.claims)!r}, "
            f"is_anonymous={self.is_anonymous})"
        )


# PRINCIPAL-INV-01 post-decoration patch: dataclass's auto-generated
# `__setattr__` / `__delattr__` capture a stale `__class__` closure after
# `slots=True` rewraps the class (Python 3.14 quirk). We replace BOTH with
# clean impls so writes/deletes raise the documented FrozenInstanceError
# instead of a confusing `TypeError: super(type, obj)`.
def _principal_setattr(self: CurrentPrincipal, name: str, value: object) -> None:  # noqa: ARG001
    raise dataclasses.FrozenInstanceError(f"cannot assign to field {name!r}")


def _principal_delattr(self: CurrentPrincipal, name: str) -> None:  # noqa: ARG001
    raise dataclasses.FrozenInstanceError(f"cannot delete field {name!r}")


CurrentPrincipal.__setattr__ = _principal_setattr  # type: ignore[method-assign]
CurrentPrincipal.__delattr__ = _principal_delattr  # type: ignore[method-assign]


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------
def anonymous() -> CurrentPrincipal:
    """Explicit `Anonymous` default — the only valid unauthenticated principal."""
    return CurrentPrincipal(
        subject_id=ANONYMOUS_SUBJECT_ID,
        tenant_id=None,
        roles=frozenset(),
        claims={},
        is_anonymous=True,
    )


def authenticated(
    subject_id: str,
    *,
    tenant_id: str | None = None,
    roles: Iterable[str] = (),
    claims: Mapping[str, str] | None = None,
) -> CurrentPrincipal:
    """Construct an authenticated principal with clear, required inputs.

    `roles` is accepted as any iterable but stored as a frozenset so the
    returned principal satisfies PRINCIPAL-INV-03.
    """
    frozen_roles = frozenset(roles)
    return CurrentPrincipal(
        subject_id=subject_id,
        tenant_id=tenant_id,
        roles=frozen_roles,
        claims=claims or {},
        is_anonymous=False,
    )


# ---------------------------------------------------------------------------
# Reference in-memory provider
# ---------------------------------------------------------------------------
class StaticPrincipalProvider:
    """Reference provider used by tests and single-tenant happy paths.

    Maps a credential string (opaque token) to a principal. Unknown tokens
    resolve to `anonymous()`. Real deployments swap in a JWT / session
    decoder, satisfying the `PrincipalProvider` Protocol.
    """

    def __init__(
        self,
        table: Mapping[str, CurrentPrincipal] | None = None,
    ) -> None:
        self._table: Mapping[str, CurrentPrincipal] = MappingProxyType(
            dict(table or {})
        )

    def resolve(self, credential: str | None) -> CurrentPrincipal:
        if credential is None or credential == "":
            return anonymous()
        return self._table.get(credential, anonymous())

    @property
    def known_credentials(self) -> frozenset[str]:
        return frozenset(self._table.keys())


__all__ = [
    "ANONYMOUS_SUBJECT_ID",
    "REDACTED",
    "SENSITIVE_CLAIM_KEYS",
    "CurrentPrincipal",
    "PrincipalInvariantError",
    "PrincipalProvider",
    "StaticPrincipalProvider",
    "anonymous",
    "authenticated",
]
