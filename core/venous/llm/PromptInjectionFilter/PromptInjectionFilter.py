"""PromptInjectionFilter primitive — quarantine untrusted text for LLM context.

Adapts the public algorithmic patterns from Rebuff (protectai/rebuff) and
Lakera Guard to the HuGR shell: declarative stripping rules, delimiter
wrapping, per-kind pipeline, and an immutable audit trail of stripped
fragments. The filter NEVER executes, renders, or interprets the raw text —
it only transforms it.

Invariant IDs cited by this module:

- PIF-INV-01: quarantine() MUST wrap raw text in explicit delimiters the
  model is instructed to treat as data; raw insertion into system prompts
  is FORBIDDEN.
- PIF-INV-02: Fragments matching known instruction patterns (imperative
  directives, role-override phrases) SHALL be stripped from the body and
  returned in stripped_fragments so auditors can inspect what was removed.
- PIF-INV-03: The filter MUST NEVER execute or interpret the raw text; it
  only transforms text (no eval, no exec, no templating, no subprocess).
- PIF-INV-04: Every quarantined block SHALL declare its kind so downstream
  guardrails can apply kind-specific rules (retrieved vs user vs tool_output).
- PIF-INV-05: Quarantining is NEVER optional for retrieved or tool_output
  content; skipping the filter on those sources is FORBIDDEN.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from typing import Final, Literal, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Allowed `kind` discriminator (PIF-INV-04, PIF-INV-05)
# ---------------------------------------------------------------------------
_KIND_USER: Final[str] = "user"
_KIND_RETRIEVED: Final[str] = "retrieved"
_KIND_TOOL_OUTPUT: Final[str] = "tool_output"

_ALLOWED_KINDS: Final[frozenset[str]] = frozenset({_KIND_USER, _KIND_RETRIEVED, _KIND_TOOL_OUTPUT})
_REQUIRED_KINDS: Final[frozenset[str]] = frozenset({_KIND_RETRIEVED, _KIND_TOOL_OUTPUT})

# ---------------------------------------------------------------------------
# Delimiter sentinels (PIF-INV-01)
# ---------------------------------------------------------------------------
_OPEN_DELIM: Final[str] = "<<<UNTRUSTED:{kind}>>>"
_CLOSE_DELIM: Final[str] = "<<<END UNTRUSTED:{kind}>>>"


# ---------------------------------------------------------------------------
# Protocol surface (matches catalog api_signature verbatim)
# ---------------------------------------------------------------------------
@runtime_checkable
class QuarantinedText(Protocol):
    kind: Literal["user", "retrieved", "tool_output"]
    wrapped: str
    stripped_fragments: tuple[str, ...]


@runtime_checkable
class PromptInjectionFilter(Protocol):
    def quarantine(self, raw: str, kind: str) -> QuarantinedText: ...


# ---------------------------------------------------------------------------
# Invariant-violation marker
# ---------------------------------------------------------------------------
class PromptInjectionInvariantError(RuntimeError):
    """Raised when a PromptInjectionFilter invariant is violated at runtime."""


# ---------------------------------------------------------------------------
# Concrete quarantined-text record
# ---------------------------------------------------------------------------
class QuarantinedBlock:
    """Concrete QuarantinedText — immutable after construction (PIF-INV-03).

    Attributes are class-level annotated (so Protocol membership holds) and
    written exactly once at `__init__` via `object.__setattr__`. Post-init
    attribute rebind raises `AttributeError` — downstream consumers SHALL NOT
    mutate a quarantined block.
    """

    __slots__ = ("kind", "stripped_fragments", "wrapped")

    kind: Literal["user", "retrieved", "tool_output"]
    wrapped: str
    stripped_fragments: tuple[str, ...]

    def __init__(
        self,
        kind: Literal["user", "retrieved", "tool_output"],
        wrapped: str,
        stripped_fragments: tuple[str, ...],
    ) -> None:
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "wrapped", wrapped)
        object.__setattr__(self, "stripped_fragments", stripped_fragments)

    def __setattr__(self, name: str, value: object) -> None:
        # PIF-INV-03: results are not mutated by downstream consumers.
        raise AttributeError(
            f"PIF-INV-03: QuarantinedBlock is immutable; cannot set attribute {name!r}."
        )


# ---------------------------------------------------------------------------
# Stripping-rule adapter contract (extension point)
# ---------------------------------------------------------------------------
class StrippingRule(Protocol):
    """A composable detection/redaction rule.

    `name`   stable identifier used in audit logs.
    `match`  returns an iterable of (start, end) spans to strip from `text`.
    """

    name: str

    def match(self, text: str, kind: str) -> Iterable[tuple[int, int]]: ...


class RegexRule:
    """Reference stripping rule backed by a compiled regex.

    Adapted from Rebuff's detector registry and Lakera Guard's published
    heuristic families (system-prompt override, role reassignment, delimiter
    escape, ignore-previous, tool exfiltration).
    """

    def __init__(self, name: str, pattern: str, *, flags: int = re.IGNORECASE | re.MULTILINE) -> None:
        self.name = name
        self._re = re.compile(pattern, flags)

    def match(self, text: str, kind: str) -> Iterable[tuple[int, int]]:
        _ = kind  # PIF-INV-03 — rule never interprets `text`; only spans are produced.
        return [(m.start(), m.end()) for m in self._re.finditer(text)]


# Curated default rule set — pattern sources: OWASP LLM01, Rebuff, Lakera
# Guard blog. Ordered general → specific so merged spans are stable.
_DEFAULT_RULES: Final[tuple[tuple[str, str], ...]] = (
    # "Ignore previous instructions" family
    ("ignore_previous", r"\b(ignore|disregard|forget)\s+(all\s+)?(prior|previous|above|the\s+above)\s+(instructions?|prompts?|rules?|context)\b.*"),
    # Role override / system prompt override
    ("role_override", r"\b(you\s+are\s+now|act\s+as|pretend\s+to\s+be|from\s+now\s+on\s+you\s+are|new\s+role\s*:)\b[^\n]{0,200}"),
    # Explicit system / developer directive escalation
    ("system_directive", r"(?:^|\n)\s*(?:system|developer|assistant)\s*:\s*[^\n]{1,300}"),
    # Reveal / exfiltrate system prompt
    ("exfiltrate_prompt", r"\b(reveal|print|show|repeat|output|leak)\s+(your\s+)?(system\s+prompt|initial\s+instructions?|hidden\s+instructions?|the\s+prompt)\b.*"),
    # Delimiter / tag injection attempting to close the quarantine
    ("delimiter_injection", r"(?i)<<<\s*/?\s*(?:end\s+)?untrusted[^>]*>>>"),
    # Common jailbreak tokens (DAN-style, "do anything now", override keywords)
    ("jailbreak_token", r"\b(DAN\s+mode|do\s+anything\s+now|developer\s+mode|jailbreak|BYPASS_SAFETY)\b[^\n]{0,200}"),
    # Tool-call exfil
    ("tool_exfil", r"\b(call|invoke|execute|run)\s+(the\s+)?tool\s+[a-zA-Z_][a-zA-Z0-9_]*\s+with\b[^\n]{0,300}"),
)


def default_rules() -> list[StrippingRule]:
    """Return a fresh list of the default stripping rules."""
    return [RegexRule(name, pat) for name, pat in _DEFAULT_RULES]


# ---------------------------------------------------------------------------
# Reference implementation
# ---------------------------------------------------------------------------
class DefaultPromptInjectionFilter:
    """Thread-safe PromptInjectionFilter with a declarative rule pipeline.

    State (why `is_stateful` applies):

    - An append-only ``audit_trail`` of every quarantined block so SREs can
      replay what the filter stripped. Audit entries are tuples of
      ``(kind, fragments)`` — the raw input is NOT stored (PIF-INV-03).
    - A mutable rule pipeline reorderable at runtime via ``add_rule`` /
      ``remove_rule``.

    Adapted algorithm (not re-derived): Rebuff's detector list +
    Lakera Guard's heuristic families. Detection is purely pattern-based;
    ML/LLM detectors may be wired as additional StrippingRule adapters.
    """

    def __init__(
        self,
        rules: Iterable[StrippingRule] | None = None,
        *,
        audit_limit: int = 10_000,
    ) -> None:
        self._rules: list[StrippingRule] = list(rules) if rules is not None else default_rules()
        self._audit_trail: list[tuple[str, tuple[str, ...]]] = []
        self._audit_limit = audit_limit
        self._lock = threading.RLock()

    # ----- rule management --------------------------------------------------
    def add_rule(self, rule: StrippingRule) -> None:
        with self._lock:
            self._rules.append(rule)

    def remove_rule(self, name: str) -> None:
        with self._lock:
            self._rules = [r for r in self._rules if r.name != name]

    @property
    def rule_names(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(r.name for r in self._rules)

    # ----- audit introspection ---------------------------------------------
    @property
    def audit_trail(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        with self._lock:
            return tuple(self._audit_trail)

    def clear_audit(self) -> None:
        with self._lock:
            self._audit_trail.clear()

    # ----- core quarantine entry-point (PIF-INV-01, -02, -04) ---------------
    def quarantine(self, raw: str, kind: str) -> QuarantinedText:
        # PIF-INV-04: kind MUST be one of the allowed discriminators.
        if kind not in _ALLOWED_KINDS:
            raise PromptInjectionInvariantError(
                f"PIF-INV-04: kind must be one of {sorted(_ALLOWED_KINDS)}, got {kind!r}."
            )
        if not isinstance(raw, str):  # pragma: no cover — Protocol already types as str
            raise PromptInjectionInvariantError(
                "PIF-INV-03: raw MUST be a str; no coercion, no interpretation."
            )

        typed_kind: Literal["user", "retrieved", "tool_output"]
        if kind == _KIND_USER:
            typed_kind = "user"
        elif kind == _KIND_RETRIEVED:
            typed_kind = "retrieved"
        else:
            typed_kind = "tool_output"

        # PIF-INV-02: find all spans matched by any rule, merge overlaps, strip.
        with self._lock:
            rules_snapshot = list(self._rules)
        spans: list[tuple[int, int, str]] = []
        for rule in rules_snapshot:
            for start, end in rule.match(raw, kind):
                if start < 0 or end > len(raw) or end <= start:
                    # Defensive: a misbehaving adapter must not corrupt output.
                    continue
                spans.append((start, end, rule.name))

        stripped_body, fragments = _apply_spans(raw, spans)

        # PIF-INV-01: wrap body in explicit delimiters referencing the kind.
        wrapped = f"{_OPEN_DELIM.format(kind=typed_kind)}\n{stripped_body}\n{_CLOSE_DELIM.format(kind=typed_kind)}"

        block = QuarantinedBlock(
            kind=typed_kind,
            wrapped=wrapped,
            stripped_fragments=tuple(fragments),
        )
        with self._lock:
            self._audit_trail.append((typed_kind, tuple(fragments)))
            if len(self._audit_trail) > self._audit_limit:
                # Bounded: drop oldest to keep memory flat on long-running processes.
                self._audit_trail = self._audit_trail[-self._audit_limit:]
        return block


# ---------------------------------------------------------------------------
# Context-assembly helper (PIF-INV-05)
# ---------------------------------------------------------------------------
class ContextAssembler:
    """Build an LLM context from mixed-provenance snippets, enforcing PIF-INV-05.

    Any attempt to add a ``retrieved`` or ``tool_output`` snippet WITHOUT the
    filter raises — direct concatenation is FORBIDDEN.
    """

    def __init__(self, filter_: PromptInjectionFilter) -> None:
        self._filter = filter_
        self._parts: list[str] = []

    def add(self, raw: str, kind: str) -> None:
        if kind in _REQUIRED_KINDS:
            block = self._filter.quarantine(raw, kind)
            self._parts.append(block.wrapped)
            return
        if kind == _KIND_USER:
            block = self._filter.quarantine(raw, kind)
            self._parts.append(block.wrapped)
            return
        raise PromptInjectionInvariantError(
            f"PIF-INV-04/-05: unknown or disallowed kind {kind!r} cannot be appended."
        )

    def add_raw_trusted_system(self, text: str) -> None:
        """Append verbatim system text. Intended ONLY for first-party instructions.

        The method name is deliberately long and self-documenting so reviewers
        spot any caller funnelling retrieved/tool_output here — that usage is
        a PIF-INV-05 violation and MUST fail code review.
        """
        self._parts.append(text)

    def render(self) -> str:
        return "\n".join(self._parts)


def _apply_spans(raw: str, spans: list[tuple[int, int, str]]) -> tuple[str, list[str]]:
    """Return (stripped_body, fragments). Overlapping spans are merged."""
    if not spans:
        return raw, []
    # Sort by start; merge overlapping / adjacent spans.
    spans_sorted = sorted(spans, key=lambda s: (s[0], s[1]))
    merged: list[tuple[int, int]] = []
    cur_start, cur_end = spans_sorted[0][0], spans_sorted[0][1]
    for s, e, _name in spans_sorted[1:]:
        if s <= cur_end:
            cur_end = max(cur_end, e)
        else:
            merged.append((cur_start, cur_end))
            cur_start, cur_end = s, e
    merged.append((cur_start, cur_end))

    fragments: list[str] = []
    out: list[str] = []
    last = 0
    for s, e in merged:
        out.append(raw[last:s])
        fragments.append(raw[s:e])
        last = e
    out.append(raw[last:])
    body = "[REDACTED]".join(out) if fragments else raw
    # Collapse any accidental duplicate redaction markers.
    while "[REDACTED][REDACTED]" in body:
        body = body.replace("[REDACTED][REDACTED]", "[REDACTED]")
    return body, fragments


# ---------------------------------------------------------------------------
# Observability hook (PIF-INV-02 audit trail) — lightweight emitter
# ---------------------------------------------------------------------------
@contextmanager
def observe_quarantine(
    filter_: DefaultPromptInjectionFilter,
    sink: Callable[[str, tuple[str, ...]], None],
) -> Iterator[None]:
    """Fan out audit entries to `sink` for the duration of the context.

    Used by the observability harness (T7) to assert emissions match schema.
    """
    before = len(filter_.audit_trail)
    try:
        yield
    finally:
        for kind, fragments in filter_.audit_trail[before:]:
            sink(kind, fragments)


__all__ = [
    "ContextAssembler",
    "DefaultPromptInjectionFilter",
    "PromptInjectionFilter",
    "PromptInjectionInvariantError",
    "QuarantinedBlock",
    "QuarantinedText",
    "RegexRule",
    "StrippingRule",
    "default_rules",
    "observe_quarantine",
]
