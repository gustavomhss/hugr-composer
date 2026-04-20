"""StreamSubject primitive — hierarchical dot-separated routing names.

Mirrors the catalog Protocol for `events.StreamSubject`. Module load performs
zero I/O.

Invariant IDs cited by this module:

- SS_INV_01: Subject names MUST NOT contain null, whitespace, '.', '*' or '>'
  inside a token because these are the reserved separators.
- SS_INV_02: The '>' wildcard SHALL appear only as the final token of a
  pattern and match one or more remaining tokens.
- SS_INV_03: The '*' wildcard MUST match exactly one token, never zero and
  never multiple.
- SS_INV_04: Names starting with '$' are FORBIDDEN for user subjects because
  that prefix is reserved for system use.
- SS_INV_05: Publishers ALWAYS send to a fully specified subject; wildcards
  CANNOT appear in a publish call.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Final

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TOKEN_WILDCARD: Final[str] = "*"  # noqa: S105 — NATS subject wildcard, not a secret (SS_INV_03)
GREEDY_WILDCARD: Final[str] = ">"
SYSTEM_PREFIX: Final[str] = "$"
RESERVED_CHARS: Final[frozenset[str]] = frozenset({".", "*", ">"})


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------
class StreamSubjectError(ValueError):
    """Raised when a subject name or pattern violates an invariant."""


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------
def _token_has_reserved(token: str) -> bool:
    if not token:
        return True
    for ch in token:
        if ch in RESERVED_CHARS:
            return True
        if ch.isspace() or ch == "\x00":
            return True
    return False


def validate_subject_name(name: str) -> str:
    """SS_INV_01 + SS_INV_04 + SS_INV_05: concrete publishable subject."""
    if not isinstance(name, str) or not name:
        raise StreamSubjectError(
            "SS_INV_01: subject name MUST be a non-empty string.",
        )
    if name.startswith(SYSTEM_PREFIX):
        raise StreamSubjectError(
            f"SS_INV_04: subject names starting with {SYSTEM_PREFIX!r} "
            f"are FORBIDDEN for user subjects.",
        )
    tokens = name.split(".")
    for tok in tokens:
        if tok in (TOKEN_WILDCARD, GREEDY_WILDCARD):
            raise StreamSubjectError(
                f"SS_INV_05: publishable subject {name!r} MUST NOT contain "
                f"wildcards; got token {tok!r}.",
            )
        if _token_has_reserved(tok):
            raise StreamSubjectError(
                f"SS_INV_01: token {tok!r} in subject {name!r} contains a "
                f"reserved or whitespace character.",
            )
    return name


def validate_pattern(pattern: str) -> str:
    """SS_INV_02 + SS_INV_03: validate a pattern used for matching."""
    if not isinstance(pattern, str) or not pattern:
        raise StreamSubjectError("pattern MUST be a non-empty string.")
    tokens = pattern.split(".")
    for i, tok in enumerate(tokens):
        if tok == GREEDY_WILDCARD:
            # SS_INV_02: '>' MUST be the last token.
            if i != len(tokens) - 1:
                raise StreamSubjectError(
                    f"SS_INV_02: greedy wildcard {GREEDY_WILDCARD!r} MUST "
                    f"appear only as the FINAL token of a pattern, "
                    f"got {pattern!r}.",
                )
            continue
        if tok == TOKEN_WILDCARD:
            continue
        if _token_has_reserved(tok):
            raise StreamSubjectError(
                f"pattern token {tok!r} in {pattern!r} contains a reserved "
                f"or whitespace character.",
            )
    return pattern


# ---------------------------------------------------------------------------
# Primitive — frozen dataclass (value type)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class StreamSubject:
    """A fully-specified publishable subject name.

    Construction enforces SS_INV_01, SS_INV_04, SS_INV_05. Use
    `matches(pattern)` to test routing.
    """

    name: str

    def __post_init__(self) -> None:
        validate_subject_name(self.name)

    def matches(self, pattern: str) -> bool:
        """SS_INV_02 + SS_INV_03: hierarchical match rules.

        - '*' matches exactly one token.
        - '>' matches one or more trailing tokens, ONLY as final token.
        - Literal tokens match byte-for-byte.
        """
        validate_pattern(pattern)
        name_tokens = self.name.split(".")
        pattern_tokens = pattern.split(".")
        for i, tok in enumerate(pattern_tokens):
            if tok == GREEDY_WILDCARD:
                # SS_INV_02: greedy matches one or more remaining tokens.
                return i < len(name_tokens)
            if i >= len(name_tokens):
                return False
            if tok == TOKEN_WILDCARD:
                # SS_INV_03: matches exactly one token — covered by position advance.
                continue
            if tok != name_tokens[i]:
                return False
        # No '>' encountered → lengths must match exactly (SS_INV_03).
        return len(pattern_tokens) == len(name_tokens)


# ---------------------------------------------------------------------------
# In-memory subscriber registry (stateful companion for runtime invariant tests)
# ---------------------------------------------------------------------------
class SubjectRegistry:
    """Stateful registry of subscribers keyed by pattern.

    A publication with a concrete StreamSubject fans out to every subscriber
    whose pattern matches; registrations and unregistrations are thread-safe.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs: dict[str, list[str]] = {}  # pattern -> list of subscriber ids
        self._seq: int = 0
        self._delivered: list[tuple[str, str, int]] = []  # (pattern, subject, seq)

    def subscribe(self, pattern: str, subscriber_id: str) -> None:
        validate_pattern(pattern)
        if not subscriber_id:
            raise StreamSubjectError("subscriber_id MUST be non-empty.")
        with self._lock:
            self._subs.setdefault(pattern, []).append(subscriber_id)

    def unsubscribe(self, pattern: str, subscriber_id: str) -> None:
        with self._lock:
            subs = self._subs.get(pattern, [])
            if subscriber_id in subs:
                subs.remove(subscriber_id)

    def publish(self, subject: StreamSubject) -> int:
        """Return the number of subscribers that matched this publication."""
        with self._lock:
            self._seq += 1
            seq = self._seq
            count = 0
            for pattern, sub_ids in self._subs.items():
                if subject.matches(pattern):
                    for sid in sub_ids:
                        self._delivered.append((pattern, subject.name, seq))
                        _ = sid  # bookkeeping; real impl would route to sid
                        count += 1
            return count

    def deliveries(self) -> list[tuple[str, str, int]]:
        with self._lock:
            return list(self._delivered)


__all__ = [
    "GREEDY_WILDCARD",
    "RESERVED_CHARS",
    "SYSTEM_PREFIX",
    "TOKEN_WILDCARD",
    "StreamSubject",
    "StreamSubjectError",
    "SubjectRegistry",
    "validate_pattern",
    "validate_subject_name",
]
