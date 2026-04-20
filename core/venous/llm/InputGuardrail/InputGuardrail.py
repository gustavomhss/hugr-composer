"""InputGuardrail primitive — pre-model validator chain (NeMo / Guardrails AI shape).

Implements the catalog Protocol for `llm.InputGuardrail`: a chain of pre-inference
validators that run against user text BEFORE it reaches the model, each emitting
a deterministic `GuardDecision` of action `allow` / `redact` / `block`. A `block`
verdict short-circuits the chain (and the pipeline). `redact` rewrites the text in
flight so downstream guards only see the sanitized version. `allow` lets the text
through unchanged.

Invariant IDs cited by this module:

- GUARD-INV-01: `evaluate()` MUST be deterministic for a given `(text, context)`
  unless the guardrail's `name` ends with the `:probabilistic` suffix. The chain
  also MUST be deterministic as a whole (same inputs → same verdicts).
- GUARD-INV-02: A `block` decision MUST halt the pipeline; callers CANNOT silently
  downgrade it. The reference `Chain.apply()` raises `GuardBlocked` on block.
- GUARD-INV-03: `redact` decisions MUST return a non-null `redacted_text`; they MUST
  NEVER leak the original text under a redact verdict (the original is dropped
  from downstream evaluation entirely).
- GUARD-INV-04: Every decision MUST carry a non-empty `reason` so downstream audit
  can explain the verdict.
- GUARD-INV-05: Guardrails MUST NEVER store raw blocked inputs in clear form; the
  reference chain hashes blocked inputs (BLAKE2b, 16-byte digest) before recording.

The primitive is stateful because the reference `Chain` records a bounded,
append-only audit trail of verdicts so operators can inspect what was blocked /
redacted. The audit log never stores clear-text for blocked inputs (INV-05).
"""

from __future__ import annotations

import hashlib
import re
import threading
from collections.abc import Iterable, Mapping, Sequence
from typing import Final, Literal, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ALLOWED_ACTIONS: Final[frozenset[str]] = frozenset({"allow", "redact", "block"})
PROBABILISTIC_SUFFIX: Final[str] = ":probabilistic"
MAX_AUDIT_ENTRIES: Final[int] = 1_000
BLOCKED_HASH_BYTES: Final[int] = 16

# Well-known PII markers (deterministic baseline; tune per deployment).
_EMAIL_RE: Final[re.Pattern[str]] = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)
_SSN_RE: Final[re.Pattern[str]] = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CREDIT_CARD_RE: Final[re.Pattern[str]] = re.compile(r"\b(?:\d[ -]?){13,19}\b")

# Classic prompt-injection markers (NeMo Guardrails + Guardrails AI heuristics).
_INJECTION_MARKERS: Final[tuple[str, ...]] = (
    "ignore previous instructions",
    "ignore the above",
    "disregard the system prompt",
    "you are now",
    "reveal the system prompt",
    "developer mode",
    "jailbreak",
    "</system>",
    "<|im_start|>system",
)


# ---------------------------------------------------------------------------
# Protocol surface (mirrors catalog api_signature verbatim)
# ---------------------------------------------------------------------------
@runtime_checkable
class GuardDecision(Protocol):
    action: Literal["allow", "redact", "block"]
    reason: str
    redacted_text: str | None


@runtime_checkable
class InputGuardrail(Protocol):
    name: str

    def evaluate(
        self, text: str, context: dict[str, str]
    ) -> GuardDecision: ...


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class InputGuardrailInvariantError(ValueError):
    """Raised when a runtime call violates an InputGuardrail invariant."""


class GuardBlocked(PermissionError):  # noqa: N818 — GUARD-INV-02 public verb name, not *Error suffix
    """Raised by `Chain.apply()` when any guardrail returns a `block` verdict.

    GUARD-INV-02: callers CANNOT silently downgrade a block to allow — the chain
    raises, rather than returning a sentinel that could be ignored.
    """

    def __init__(self, guard_name: str, reason: str, hashed_input: str) -> None:
        super().__init__(f"{guard_name}: {reason}")
        self.guard_name: str = guard_name
        self.reason: str = reason
        self.hashed_input: str = hashed_input


# ---------------------------------------------------------------------------
# Runtime invariant validators
# ---------------------------------------------------------------------------
def validate_action(action: str) -> str:
    """GUARD-INV-02/03: action MUST be one of the catalog literals."""
    if not isinstance(action, str) or action not in ALLOWED_ACTIONS:
        raise InputGuardrailInvariantError(
            f"GUARD-INV-02: action MUST be one of {sorted(ALLOWED_ACTIONS)}, "
            f"got {action!r}."
        )
    return action


def validate_reason(reason: str) -> str:
    """GUARD-INV-04: reason MUST be a non-empty string."""
    if not isinstance(reason, str) or not reason.strip():
        raise InputGuardrailInvariantError(
            "GUARD-INV-04: every decision MUST carry a non-empty reason."
        )
    return reason


def validate_redacted_text(action: str, redacted_text: str | None, text: str) -> str | None:
    """GUARD-INV-03: `redact` MUST return redacted_text and NEVER the original.

    For `allow` / `block` the `redacted_text` SHALL be `None` (contract hygiene).
    """
    if action == "redact":
        if redacted_text is None:
            raise InputGuardrailInvariantError(
                "GUARD-INV-03: redact decisions MUST return non-null redacted_text."
            )
        if redacted_text == text:
            raise InputGuardrailInvariantError(
                "GUARD-INV-03: redact decisions MUST NOT return the original text."
            )
        return redacted_text
    # allow / block: redacted_text SHALL be None.
    if redacted_text is not None:
        raise InputGuardrailInvariantError(
            "GUARD-INV-03: non-redact decisions MUST have redacted_text=None, "
            f"got {redacted_text!r} under action={action!r}."
        )
    return None


def validate_guard_name(name: str) -> str:
    """GUARD-INV-01: guard name MUST be a non-empty string (`:probabilistic`
    suffix marks a non-deterministic guardrail)."""
    if not isinstance(name, str) or not name.strip():
        raise InputGuardrailInvariantError(
            "GUARD-INV-01: guardrail name MUST be a non-empty string."
        )
    return name


def is_probabilistic(name: str) -> bool:
    """Helper for GUARD-INV-01 determinism exemption."""
    return name.endswith(PROBABILISTIC_SUFFIX)


def hash_input(text: str) -> str:
    """GUARD-INV-05: hash blocked inputs before recording (BLAKE2b, 16 bytes)."""
    return hashlib.blake2b(
        text.encode("utf-8"), digest_size=BLOCKED_HASH_BYTES
    ).hexdigest()


# ---------------------------------------------------------------------------
# Decision value object
# ---------------------------------------------------------------------------
class Decision:
    """`GuardDecision` value object enforcing invariants at construction.

    `__slots__` prevents accidental attribute poisoning that would break
    GUARD-INV-01 determinism guarantees; callers SHOULD treat Decision as
    immutable — construct a new one rather than mutate fields.
    """

    __slots__ = ("action", "reason", "redacted_text")

    action: Literal["allow", "redact", "block"]
    reason: str
    redacted_text: str | None

    def __init__(
        self,
        *,
        action: Literal["allow", "redact", "block"],
        reason: str,
        redacted_text: str | None = None,
        original_text: str = "",
    ) -> None:
        validate_action(action)
        validate_reason(reason)
        validate_redacted_text(action, redacted_text, original_text)
        self.action = action
        self.reason = reason
        self.redacted_text = redacted_text

    def __repr__(self) -> str:
        redacted_marker: str | None = (
            "<redacted>" if self.redacted_text is not None else None
        )
        return (
            f"Decision(action={self.action!r}, reason={self.reason!r}, "
            f"redacted_text={redacted_marker!r})"
        )


def _allow(reason: str) -> Decision:
    return Decision(action="allow", reason=reason)


def _redact(reason: str, redacted_text: str, original_text: str) -> Decision:
    return Decision(
        action="redact",
        reason=reason,
        redacted_text=redacted_text,
        original_text=original_text,
    )


def _block(reason: str) -> Decision:
    return Decision(action="block", reason=reason)


# ---------------------------------------------------------------------------
# Built-in guardrails (deterministic — NeMo/Guardrails AI validator-chain shape)
# ---------------------------------------------------------------------------
class PIIRedactor:
    """Redact emails, SSNs, and credit-card-shaped digit runs.

    Deterministic: identical `(text, context)` → identical verdict.
    """

    def __init__(self, name: str = "pii_redactor") -> None:
        self.name: str = validate_guard_name(name)

    def evaluate(self, text: str, context: dict[str, str]) -> Decision:
        _ = context  # context reserved for role-based policy; unused here.
        if not isinstance(text, str):
            raise InputGuardrailInvariantError(
                "GUARD-INV-04: text MUST be a string."
            )
        redacted = _EMAIL_RE.sub("[REDACTED_EMAIL]", text)
        redacted = _SSN_RE.sub("[REDACTED_SSN]", redacted)
        redacted = _CREDIT_CARD_RE.sub("[REDACTED_CARD]", redacted)
        if redacted == text:
            return _allow("no PII detected")
        return _redact("PII patterns redacted", redacted, text)


class PromptInjectionBlocker:
    """Block well-known prompt-injection markers (case-insensitive)."""

    def __init__(
        self,
        name: str = "prompt_injection_blocker",
        *,
        markers: Sequence[str] | None = None,
    ) -> None:
        self.name: str = validate_guard_name(name)
        self._markers: tuple[str, ...] = tuple(
            m.lower() for m in (markers if markers is not None else _INJECTION_MARKERS)
        )

    def evaluate(self, text: str, context: dict[str, str]) -> Decision:
        _ = context
        if not isinstance(text, str):
            raise InputGuardrailInvariantError(
                "GUARD-INV-04: text MUST be a string."
            )
        low = text.lower()
        for marker in self._markers:
            if marker in low:
                return _block(f"prompt-injection marker detected: {marker!r}")
        return _allow("no injection markers")


class LengthLimit:
    """Block oversized inputs — classic amplification / DOS mitigation."""

    def __init__(self, name: str = "length_limit", *, max_chars: int = 8_000) -> None:
        self.name: str = validate_guard_name(name)
        if max_chars < 1:
            raise InputGuardrailInvariantError(
                "GUARD-INV-04: max_chars MUST be >= 1."
            )
        self._max_chars: int = max_chars

    def evaluate(self, text: str, context: dict[str, str]) -> Decision:
        _ = context
        if not isinstance(text, str):
            raise InputGuardrailInvariantError(
                "GUARD-INV-04: text MUST be a string."
            )
        if len(text) > self._max_chars:
            return _block(
                f"input length {len(text)} exceeds max_chars={self._max_chars}"
            )
        return _allow("within length limit")


class DenyList:
    """Block any case-insensitive substring hit against a caller-supplied list."""

    def __init__(self, name: str, *, terms: Iterable[str]) -> None:
        self.name: str = validate_guard_name(name)
        normalized = tuple(t.lower() for t in terms if t)
        if not normalized:
            raise InputGuardrailInvariantError(
                "GUARD-INV-04: DenyList MUST be constructed with at least one term."
            )
        self._terms: tuple[str, ...] = normalized

    def evaluate(self, text: str, context: dict[str, str]) -> Decision:
        _ = context
        if not isinstance(text, str):
            raise InputGuardrailInvariantError(
                "GUARD-INV-04: text MUST be a string."
            )
        low = text.lower()
        for term in self._terms:
            if term in low:
                return _block(f"deny-listed term detected: {term!r}")
        return _allow("no deny-listed terms")


# ---------------------------------------------------------------------------
# Stateful validator chain (reference implementation)
# ---------------------------------------------------------------------------
class AuditEntry:
    """One audit-log row. Blocked inputs are stored as a BLAKE2b digest only."""

    __slots__ = ("action", "guard_name", "input_hash", "reason", "seq")

    def __init__(
        self,
        *,
        guard_name: str,
        action: Literal["allow", "redact", "block"],
        reason: str,
        input_hash: str,
        seq: int,
    ) -> None:
        self.guard_name: str = guard_name
        self.action: Literal["allow", "redact", "block"] = action
        self.reason: str = reason
        self.input_hash: str = input_hash
        self.seq: int = seq


class ChainOutcome:
    """Result of a full chain run when no guard blocked."""

    __slots__ = ("final_text", "verdicts")

    def __init__(
        self,
        *,
        final_text: str,
        verdicts: tuple[tuple[str, GuardDecision], ...],
    ) -> None:
        self.final_text: str = final_text
        self.verdicts: tuple[tuple[str, GuardDecision], ...] = verdicts

    def was_redacted(self) -> bool:
        return any(v[1].action == "redact" for v in self.verdicts)


class Chain:
    """Ordered pipeline of `InputGuardrail`s.

    States:
        open   → can call `apply()` / `apply_with_outcome()`
        sealed → further `apply()` rejected (operator froze the chain)

    State transitions:
        open --seal()-->  sealed
        sealed is terminal.

    The chain is stateful because it records a bounded audit trail. The audit
    NEVER stores clear text for blocked inputs (GUARD-INV-05).
    """

    def __init__(self, guards: Sequence[InputGuardrail]) -> None:
        if not guards:
            raise InputGuardrailInvariantError(
                "GUARD-INV-02: Chain MUST be constructed with at least one guard."
            )
        names: list[str] = []
        for g in guards:
            validate_guard_name(g.name)
            names.append(g.name)
        if len(set(names)) != len(names):
            raise InputGuardrailInvariantError(
                f"GUARD-INV-01: duplicate guard names in chain: {names}"
            )
        self._guards: tuple[InputGuardrail, ...] = tuple(guards)
        self._audit: list[AuditEntry] = []
        self._seq: int = 0
        self._state: Literal["open", "sealed"] = "open"
        self._lock = threading.Lock()

    # ----- state ------------------------------------------------------------
    @property
    def state(self) -> Literal["open", "sealed"]:
        with self._lock:
            return self._state

    def seal(self) -> None:
        with self._lock:
            self._state = "sealed"

    @property
    def audit(self) -> tuple[AuditEntry, ...]:
        with self._lock:
            return tuple(self._audit)

    @property
    def guards(self) -> tuple[InputGuardrail, ...]:
        return self._guards

    # ----- apply ------------------------------------------------------------
    def apply(self, text: str, context: Mapping[str, str] | None = None) -> str:
        """Run the chain; raise GuardBlocked on block; return (possibly redacted) text."""
        outcome = self.apply_with_outcome(text, context)
        return outcome.final_text

    def apply_with_outcome(
        self, text: str, context: Mapping[str, str] | None = None
    ) -> ChainOutcome:
        if not isinstance(text, str):
            raise InputGuardrailInvariantError(
                "GUARD-INV-04: text MUST be a string."
            )
        ctx: dict[str, str] = dict(context) if context is not None else {}
        with self._lock:
            if self._state == "sealed":
                raise InputGuardrailInvariantError(
                    "GUARD-INV-02: chain is sealed; further apply() calls rejected."
                )

        current = text
        verdicts: list[tuple[str, GuardDecision]] = []
        for guard in self._guards:
            decision: GuardDecision = guard.evaluate(current, dict(ctx))
            # Re-validate — trust-but-verify boundary (defense in depth).
            validate_action(decision.action)
            validate_reason(decision.reason)
            validate_redacted_text(decision.action, decision.redacted_text, current)
            verdicts.append((guard.name, decision))
            if decision.action == "block":
                # GUARD-INV-05: hash the CURRENT text before recording.
                self._record(guard.name, decision, hash_input(current))
                raise GuardBlocked(
                    guard_name=guard.name,
                    reason=decision.reason,
                    hashed_input=hash_input(current),
                )
            if decision.action == "redact":
                # GUARD-INV-03: redact swaps the text for downstream guards.
                redacted = decision.redacted_text
                if redacted is None:
                    raise InputGuardrailInvariantError(
                        "GUARD-INV-03: redact verdict MUST carry redacted_text."
                    )
                current = redacted
            self._record(guard.name, decision, hash_input(current))
        return ChainOutcome(final_text=current, verdicts=tuple(verdicts))

    # ----- internal ---------------------------------------------------------
    def _record(
        self, guard_name: str, decision: GuardDecision, input_hash: str
    ) -> None:
        """Append one audit row; bounded ring to prevent unbounded memory growth."""
        with self._lock:
            self._seq += 1
            entry = AuditEntry(
                guard_name=guard_name,
                action=decision.action,
                reason=decision.reason,
                input_hash=input_hash,
                seq=self._seq,
            )
            self._audit.append(entry)
            if len(self._audit) > MAX_AUDIT_ENTRIES:
                # Drop the oldest entry — ring buffer.
                del self._audit[0]


__all__ = [
    "ALLOWED_ACTIONS",
    "BLOCKED_HASH_BYTES",
    "MAX_AUDIT_ENTRIES",
    "PROBABILISTIC_SUFFIX",
    "AuditEntry",
    "Chain",
    "ChainOutcome",
    "Decision",
    "DenyList",
    "GuardBlocked",
    "GuardDecision",
    "InputGuardrail",
    "InputGuardrailInvariantError",
    "LengthLimit",
    "PIIRedactor",
    "PromptInjectionBlocker",
    "hash_input",
    "is_probabilistic",
    "validate_action",
    "validate_guard_name",
    "validate_reason",
    "validate_redacted_text",
]
