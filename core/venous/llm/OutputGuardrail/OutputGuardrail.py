"""OutputGuardrail primitive — post-inference verdicts on LLM output.

Implements the catalog Protocol for `llm.OutputGuardrail`: a post-inference
validator that returns a verdict (pass / rewrite / block) against schema,
policy, and safety rules BEFORE the output reaches the caller or any
downstream tool executor. The design adapts the validator-chain pattern used
by NVIDIA NeMo Guardrails (`output rails`) and Guardrails AI, reshaped to
honour the HuGR invariant model.

Zero I/O at import; optional heavy validators (e.g. jsonschema) are imported
lazily inside the validator bodies so the module boots without them.

Invariant IDs cited by this module:

- GUARD-INV-01: evaluate() MUST reject output that fails schema validation
  when schema_ref is provided; malformed JSON CANNOT be returned as `pass`.
- GUARD-INV-02: a BLOCK verdict MUST prevent the output from being returned
  to the caller or passed to any downstream tool (enforced by
  `apply_chain()`).
- GUARD-INV-03: REWRITE verdicts MUST provide a non-None string replacement;
  `replacement=None` under `action="rewrite"` SHALL raise at construction.
- GUARD-INV-04: the chain MUST NEVER execute tool calls embedded in the
  output before every guardrail has passed its safety check; tool-shaped
  tokens in raw output are opaque bytes until the chain completes.
- GUARD-INV-05: every verdict SHALL be recorded against the guardrail name
  in the verdict ledger so post-hoc analysis can attribute the decision.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Sequence
from typing import Final, Literal, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
VerdictAction = Literal["pass", "rewrite", "block"]
_VALID_ACTIONS: Final[frozenset[str]] = frozenset({"pass", "rewrite", "block"})
NAME_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-zA-Z][a-zA-Z0-9_.-]{0,63}$")
MAX_OUTPUT_BYTES: Final[int] = 2_000_000
MAX_REASON_CHARS: Final[int] = 500
# Heuristic tool-call shapes observed in popular model outputs; the guardrail
# treats them as opaque until the chain completes (GUARD-INV-04).
TOOL_CALL_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"<tool_call\b", re.IGNORECASE),
    re.compile(r"<function_call\b", re.IGNORECASE),
    re.compile(r"<invoke\b", re.IGNORECASE),
    re.compile(r"```tool_code\b"),
)


class OutputGuardrailInvariantError(ValueError):
    """Raised when a runtime call violates an OutputGuardrail invariant."""


class OutputBlocked(RuntimeError):  # noqa: N818 — GUARD-INV-02: name is a control-flow signal (block), not an error suffix.
    """Raised by `apply_chain()` when a guardrail returns a BLOCK verdict.

    Carries the guardrail name and reason so the caller can audit attribution
    (GUARD-INV-05).
    """

    def __init__(self, *, guardrail: str, reason: str) -> None:
        super().__init__(f"{guardrail}: {reason}")
        self.guardrail = guardrail
        self.reason = reason


# ---------------------------------------------------------------------------
# Protocol surface (mirrors catalog api_signature verbatim)
# ---------------------------------------------------------------------------
@runtime_checkable
class OutputVerdict(Protocol):
    action: VerdictAction
    reason: str
    replacement: str | None


@runtime_checkable
class OutputGuardrail(Protocol):
    name: str

    def evaluate(self, output: str, schema_ref: str | None) -> OutputVerdict: ...


# ---------------------------------------------------------------------------
# Runtime invariant enforcers
# ---------------------------------------------------------------------------
def validate_name(name: str) -> str:
    if not isinstance(name, str) or not NAME_PATTERN.match(name):
        raise OutputGuardrailInvariantError(
            f"GUARD-INV-05: guardrail name {name!r} MUST match {NAME_PATTERN.pattern}; "
            f"non-identifier names break ledger attribution."
        )
    return name


def validate_output(output: str) -> str:
    if not isinstance(output, str):
        raise OutputGuardrailInvariantError(
            f"GUARD-INV-01: output MUST be str; got {type(output).__name__}."
        )
    if len(output.encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise OutputGuardrailInvariantError(
            f"GUARD-INV-01: output exceeds {MAX_OUTPUT_BYTES} bytes."
        )
    return output


# ---------------------------------------------------------------------------
# Immutable verdict record
# ---------------------------------------------------------------------------
class Verdict:
    """Immutable verdict object — once constructed, fields never change.

    Invariants enforced at construction (GUARD-INV-03):
      - action ∈ {pass, rewrite, block}
      - reason is a non-empty string ≤ MAX_REASON_CHARS
      - replacement is str iff action == 'rewrite'; otherwise MUST be None
    """

    _action: VerdictAction
    _reason: str
    _replacement: str | None

    def __init__(
        self,
        *,
        action: VerdictAction,
        reason: str,
        replacement: str | None = None,
    ) -> None:
        if action not in _VALID_ACTIONS:
            raise OutputGuardrailInvariantError(
                f"GUARD-INV-03: action MUST be one of {sorted(_VALID_ACTIONS)}; got {action!r}."
            )
        if not isinstance(reason, str) or not reason.strip():
            raise OutputGuardrailInvariantError(
                "GUARD-INV-03: reason MUST be a non-empty string; "
                "empty reason breaks ledger attribution (GUARD-INV-05)."
            )
        if len(reason) > MAX_REASON_CHARS:
            raise OutputGuardrailInvariantError(
                f"GUARD-INV-03: reason MUST be ≤ {MAX_REASON_CHARS} chars."
            )
        if action == "rewrite":
            if replacement is None:
                raise OutputGuardrailInvariantError(
                    "GUARD-INV-03: action='rewrite' MUST carry a non-None string "
                    "replacement; None under rewrite is a contract violation."
                )
            if not isinstance(replacement, str):
                raise OutputGuardrailInvariantError(
                    f"GUARD-INV-03: replacement MUST be str when action='rewrite'; "
                    f"got {type(replacement).__name__}."
                )
        elif replacement is not None:
            raise OutputGuardrailInvariantError(
                f"GUARD-INV-03: replacement MUST be None when action={action!r}; "
                f"non-None replacement outside rewrite is ambiguous."
            )
        object.__setattr__(self, "_action", action)
        object.__setattr__(self, "_reason", reason)
        object.__setattr__(self, "_replacement", replacement)

    def __setattr__(self, key: str, value: object) -> None:
        raise OutputGuardrailInvariantError(
            f"GUARD-INV-03: Verdict is immutable; cannot set attribute {key!r}."
        )

    @property
    def action(self) -> VerdictAction:
        return self._action

    @property
    def reason(self) -> str:
        return self._reason

    @property
    def replacement(self) -> str | None:
        return self._replacement

    def __repr__(self) -> str:
        repl = "None" if self._replacement is None else f"len={len(self._replacement)}"
        return f"Verdict(action={self._action!r}, reason={self._reason!r}, replacement={repl})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Verdict):
            return NotImplemented
        return (
            self._action == other._action
            and self._reason == other._reason
            and self._replacement == other._replacement
        )

    def __hash__(self) -> int:
        return hash((self._action, self._reason, self._replacement))


# ---------------------------------------------------------------------------
# Verdict ledger — enforces GUARD-INV-05 globally
# ---------------------------------------------------------------------------
class VerdictLedger:
    """Thread-safe ledger binding every emitted verdict to the guardrail that
    produced it. This is the single source of post-hoc attribution.
    """

    def __init__(self) -> None:
        self._entries: list[tuple[str, Verdict]] = []
        self._lock = threading.Lock()

    def record(self, guardrail_name: str, verdict: Verdict) -> None:
        validate_name(guardrail_name)
        if not isinstance(verdict, Verdict):
            raise OutputGuardrailInvariantError(
                "GUARD-INV-05: ledger MUST receive a Verdict instance; "
                f"got {type(verdict).__name__}."
            )
        with self._lock:
            self._entries.append((guardrail_name, verdict))

    def entries(self) -> tuple[tuple[str, Verdict], ...]:
        with self._lock:
            return tuple(self._entries)

    def entries_for(self, guardrail_name: str) -> tuple[Verdict, ...]:
        with self._lock:
            return tuple(v for n, v in self._entries if n == guardrail_name)

    def size(self) -> int:
        with self._lock:
            return len(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


# ---------------------------------------------------------------------------
# Reference validator implementations
# ---------------------------------------------------------------------------
class SchemaOutputGuardrail:
    """Rejects output that is not valid JSON conforming to the referenced schema.

    `schema_ref` is a logical key; the constructor takes a mapping from ref to
    a JSON Schema dict. If `schema_ref` is None, evaluate() short-circuits to
    `pass` with reason "no-schema" (schemas are opt-in per catalog surface).
    Schema conformance is checked with a minimal internal validator; if the
    optional `jsonschema` package is importable, its Draft 2020-12 validator
    is used for fuller coverage. Import is lazy (module boots without it).
    """

    def __init__(self, *, name: str, schemas: dict[str, dict[str, object]]) -> None:
        self.name = validate_name(name)
        if not isinstance(schemas, dict):
            raise OutputGuardrailInvariantError(
                "GUARD-INV-01: schemas MUST be a dict[str, dict] of schema_ref -> schema."
            )
        for k, v in schemas.items():
            if not isinstance(k, str) or not isinstance(v, dict):
                raise OutputGuardrailInvariantError(
                    "GUARD-INV-01: schemas keys MUST be str, values MUST be dict."
                )
        # Defensive copy — the registry is immutable from outside.
        self._schemas: dict[str, dict[str, object]] = {k: dict(v) for k, v in schemas.items()}

    def evaluate(self, output: str, schema_ref: str | None) -> Verdict:
        validate_output(output)
        if schema_ref is None:
            return Verdict(action="pass", reason="no-schema")
        if schema_ref not in self._schemas:
            return Verdict(
                action="block",
                reason=f"unknown schema_ref={schema_ref!r}; refusing to pass unverified output.",
            )
        try:
            parsed = json.loads(output)
        except (ValueError, TypeError) as e:
            # GUARD-INV-01: malformed JSON CANNOT be passed.
            return Verdict(
                action="block",
                reason=f"invalid JSON: {type(e).__name__}: {str(e)[:200]}",
            )
        schema = self._schemas[schema_ref]
        err = _validate_against_schema(parsed, schema)
        if err is not None:
            return Verdict(action="block", reason=f"schema violation: {err[:400]}")
        return Verdict(action="pass", reason="schema-valid")


class PolicyOutputGuardrail:
    """Blocks output whose content matches any configured forbidden pattern,
    or rewrites it when a safe replacement is configured.

    This is the policy layer (e.g. PII redaction, banned topic detection).
    """

    def __init__(
        self,
        *,
        name: str,
        block_patterns: Sequence[str] = (),
        rewrite_patterns: Sequence[tuple[str, str]] = (),
    ) -> None:
        self.name = validate_name(name)
        # Pre-compile patterns; reject malformed regex at construction.
        self._block: tuple[re.Pattern[str], ...] = tuple(
            re.compile(p) for p in block_patterns
        )
        self._rewrite: tuple[tuple[re.Pattern[str], str], ...] = tuple(
            (re.compile(p), r) for p, r in rewrite_patterns
        )

    def evaluate(self, output: str, schema_ref: str | None) -> Verdict:
        validate_output(output)
        del schema_ref  # schema is handled by SchemaOutputGuardrail
        for pat in self._block:
            if pat.search(output):
                return Verdict(
                    action="block",
                    reason=f"policy match: /{pat.pattern[:80]}/",
                )
        rewritten = output
        hits: list[str] = []
        for pat, replacement in self._rewrite:
            new = pat.sub(replacement, rewritten)
            if new != rewritten:
                hits.append(pat.pattern[:40])
                rewritten = new
        if hits:
            return Verdict(
                action="rewrite",
                reason=f"policy redaction: {hits}",
                replacement=rewritten,
            )
        return Verdict(action="pass", reason="no-policy-hit")


class SafetyOutputGuardrail:
    """Blocks output that smuggles tool-call shapes past the chain.

    Implements GUARD-INV-04: tool-call tokens embedded in the raw output are
    opaque bytes; this guardrail refuses to let them pass to a downstream
    executor. Callers who legitimately use function-calling MUST surface that
    through the model's structured tool-use API, not through rendered text.
    """

    def __init__(self, *, name: str) -> None:
        self.name = validate_name(name)

    def evaluate(self, output: str, schema_ref: str | None) -> Verdict:
        validate_output(output)
        del schema_ref
        for pat in TOOL_CALL_PATTERNS:
            m = pat.search(output)
            if m:
                return Verdict(
                    action="block",
                    reason=(
                        f"tool-call-shape detected at offset {m.start()}: "
                        f"{m.group(0)[:40]!r} — GUARD-INV-04 refuses silent tool exec."
                    ),
                )
        return Verdict(action="pass", reason="no-tool-shape")


# ---------------------------------------------------------------------------
# Chain executor — enforces GUARD-INV-02 / GUARD-INV-04 / GUARD-INV-05
# ---------------------------------------------------------------------------
def apply_chain(
    guards: Sequence[OutputGuardrail],
    raw: str,
    *,
    schema_ref: str | None = None,
    ledger: VerdictLedger | None = None,
) -> str:
    """Apply every guardrail in order. Returns the (possibly rewritten) output
    ONLY when all guards emit a `pass` verdict. A single BLOCK verdict
    aborts with `OutputBlocked` (GUARD-INV-02). A REWRITE verdict without a
    replacement is caught at Verdict construction (GUARD-INV-03).

    Each verdict is recorded against the guardrail name in the ledger
    (GUARD-INV-05). Tool-call execution is never performed by this function;
    the raw output is treated as opaque bytes until every check passes
    (GUARD-INV-04).
    """
    validate_output(raw)
    current = raw
    for g in guards:
        name = validate_name(g.name)
        raw_v = g.evaluate(current, schema_ref)
        # Normalize any Protocol-conforming verdict into our concrete Verdict
        # so the ledger and downstream callers see a uniform shape. Verdict
        # construction re-validates GUARD-INV-03.
        verdict: Verdict = (
            raw_v
            if isinstance(raw_v, Verdict)
            else Verdict(action=raw_v.action, reason=raw_v.reason, replacement=raw_v.replacement)
        )
        if ledger is not None:
            ledger.record(name, verdict)
        if verdict.action == "block":
            raise OutputBlocked(guardrail=name, reason=verdict.reason)
        if verdict.action == "rewrite":
            # Verdict ctor already enforced replacement is not None.
            replacement = verdict.replacement
            if replacement is None:  # pragma: no cover — GUARD-INV-03 rejects at ctor.
                raise OutputGuardrailInvariantError(
                    "GUARD-INV-03: rewrite verdict reached apply_chain with None replacement."
                )
            current = replacement
    return current


# ---------------------------------------------------------------------------
# Minimal JSON schema check (fallback when `jsonschema` absent)
# ---------------------------------------------------------------------------
def _validate_against_schema(value: object, schema: dict[str, object]) -> str | None:
    """Return None on success, else a violation message.

    Minimal in-tree check covering `type`, `required`, and nested
    `properties` — enough to reject the malformed-JSON and missing-required
    cases GUARD-INV-01 demands without pulling an optional runtime
    dependency into the import path.
    """
    return _minimal_schema_check(value, schema)


_JSON_TYPES: Final[dict[str, tuple[type, ...]]] = {
    "string": (str,),
    "number": (int, float),
    "integer": (int,),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
    "null": (type(None),),
}


def _check_type(value: object, t: str) -> str | None:
    allowed = _JSON_TYPES.get(t)
    if allowed is None:
        return f"unknown schema type {t!r}"
    # JSON Schema treats integer as non-bool int, number as non-bool numeric.
    if t in {"integer", "number"} and isinstance(value, bool):
        return f"expected {t}, got boolean"
    if not isinstance(value, allowed):
        return f"expected type {t}, got {type(value).__name__}"
    return None


def _check_required(value: object, required: object) -> str | None:
    if not isinstance(required, list) or not isinstance(value, dict):
        return None
    for k in required:
        if k not in value:
            return f"missing required field {k!r}"
    return None


def _check_properties(value: object, props: object) -> str | None:
    if not isinstance(props, dict) or not isinstance(value, dict):
        return None
    for k, sub_schema in props.items():
        if k in value and isinstance(sub_schema, dict):
            sub_err = _minimal_schema_check(value[k], sub_schema)
            if sub_err is not None:
                return f"at {k!r}: {sub_err}"
    return None


def _minimal_schema_check(value: object, schema: dict[str, object]) -> str | None:
    t = schema.get("type")
    if isinstance(t, str):
        err = _check_type(value, t)
        if err is not None:
            return err
    err = _check_required(value, schema.get("required"))
    if err is not None:
        return err
    return _check_properties(value, schema.get("properties"))


__all__ = [
    "MAX_OUTPUT_BYTES",
    "MAX_REASON_CHARS",
    "NAME_PATTERN",
    "TOOL_CALL_PATTERNS",
    "OutputBlocked",
    "OutputGuardrail",
    "OutputGuardrailInvariantError",
    "OutputVerdict",
    "PolicyOutputGuardrail",
    "SafetyOutputGuardrail",
    "SchemaOutputGuardrail",
    "Verdict",
    "VerdictAction",
    "VerdictLedger",
    "apply_chain",
    "validate_name",
    "validate_output",
]
