"""PromptTemplate primitive — versioned, pinned, parameterized prompts.

Implements the catalog Protocol for `llm.PromptTemplate` and provides a
registry that enforces immutable published versions. Zero I/O at import.

Invariant IDs cited by this module:

- PROMPT-INV-01: rendered output MUST be byte-identical across two calls with
  the same (version, values) pair.
- PROMPT-INV-02: a published version MUST NEVER be mutated; changes SHALL
  produce a new integer version.
- PROMPT-INV-03: render() MUST raise when a declared variable is missing and
  MUST NEVER silently inject an empty string.
- PROMPT-INV-04: fingerprint() MUST cover template text, target_model, and
  variable names; drift in any of them SHALL change the fingerprint.
- PROMPT-INV-05: variable interpolation MUST use explicit delimiters and
  CANNOT treat unescaped user input as template syntax.
"""

from __future__ import annotations

import hashlib
import re
import threading
from collections.abc import Mapping
from typing import Final, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# Explicit delimiter set chosen to avoid collision with model-facing
# system-prompt markers (no angle brackets, no backticks).
VARIABLE_PATTERN: Final[re.Pattern[str]] = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")
VARIABLE_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
MAX_TEMPLATE_BYTES: Final[int] = 1_000_000
MAX_VALUE_BYTES: Final[int] = 200_000


class PromptTemplateInvariantError(ValueError):
    """Raised when a runtime call violates a PromptTemplate invariant."""


# ---------------------------------------------------------------------------
# Protocol surface (mirrors catalog api_signature verbatim)
# ---------------------------------------------------------------------------
@runtime_checkable
class PromptTemplate(Protocol):
    name: str
    version: int
    target_model: str
    variables: tuple[str, ...]

    def render(self, values: Mapping[str, str]) -> str: ...
    def fingerprint(self) -> str: ...


# ---------------------------------------------------------------------------
# Runtime invariant enforcers
# ---------------------------------------------------------------------------
def validate_name(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise PromptTemplateInvariantError(
            "PROMPT-INV-02: name MUST be a non-empty string."
        )
    return name


def validate_version(version: int) -> int:
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise PromptTemplateInvariantError(
            "PROMPT-INV-02: version MUST be a positive integer."
        )
    return version


def validate_variables(variables: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(variables, tuple):
        raise PromptTemplateInvariantError(
            "PROMPT-INV-04: variables MUST be a tuple of identifier strings."
        )
    seen: set[str] = set()
    for v in variables:
        if not isinstance(v, str) or not VARIABLE_NAME_PATTERN.match(v):
            raise PromptTemplateInvariantError(
                f"PROMPT-INV-04: variable name {v!r} MUST match {VARIABLE_NAME_PATTERN.pattern}."
            )
        if v in seen:
            raise PromptTemplateInvariantError(
                f"PROMPT-INV-04: variable {v!r} declared twice; duplicates FORBIDDEN."
            )
        seen.add(v)
    return variables


def _extract_template_variables(text: str) -> tuple[str, ...]:
    """Return declared variables in first-occurrence order."""
    seen: set[str] = set()
    out: list[str] = []
    for m in VARIABLE_PATTERN.finditer(text):
        name = m.group(1)
        if name not in seen:
            seen.add(name)
            out.append(name)
    return tuple(out)


# ---------------------------------------------------------------------------
# Reference implementation
# ---------------------------------------------------------------------------
class FrozenPromptTemplate:
    """Immutable prompt template — once constructed, content never changes.

    The constructor validates the invariants; attribute assignment is disabled
    via __setattr__ override so PROMPT-INV-02 cannot be violated from outside.
    """

    _name: str
    _version: int
    _target_model: str
    _text: str
    _variables: tuple[str, ...]
    _fp: str

    def __init__(
        self,
        *,
        name: str,
        version: int,
        target_model: str,
        text: str,
        variables: tuple[str, ...],
    ) -> None:
        validate_name(name)
        validate_version(version)
        if not isinstance(target_model, str) or not target_model:
            raise PromptTemplateInvariantError(
                "PROMPT-INV-04: target_model MUST be a non-empty string."
            )
        if not isinstance(text, str):
            raise PromptTemplateInvariantError(
                "PROMPT-INV-01: template text MUST be a string."
            )
        if len(text.encode("utf-8")) > MAX_TEMPLATE_BYTES:
            raise PromptTemplateInvariantError(
                f"PROMPT-INV-01: template text MUST be ≤ {MAX_TEMPLATE_BYTES} bytes."
            )
        validate_variables(variables)
        declared = _extract_template_variables(text)
        declared_set = set(declared)
        given_set = set(variables)
        if declared_set != given_set:
            missing = declared_set - given_set
            extra = given_set - declared_set
            raise PromptTemplateInvariantError(
                f"PROMPT-INV-03: declared variables {sorted(given_set)} MUST match "
                f"template placeholders {sorted(declared_set)}; "
                f"missing_in_declaration={sorted(missing)}, "
                f"missing_in_template={sorted(extra)}."
            )

        # Use object.__setattr__ so __setattr__ override does not bite us during init.
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_version", version)
        object.__setattr__(self, "_target_model", target_model)
        object.__setattr__(self, "_text", text)
        object.__setattr__(self, "_variables", tuple(variables))
        object.__setattr__(self, "_fp", self._compute_fingerprint())

    def __setattr__(self, key: str, value: object) -> None:
        raise PromptTemplateInvariantError(
            f"PROMPT-INV-02: published template is immutable; "
            f"cannot set attribute {key!r}. Create a new version instead."
        )

    # ----- public Protocol surface --------------------------------------------
    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> int:
        return self._version

    @property
    def target_model(self) -> str:
        return self._target_model

    @property
    def variables(self) -> tuple[str, ...]:
        return self._variables

    @property
    def text(self) -> str:
        return self._text

    def render(self, values: Mapping[str, str]) -> str:
        """Substitute declared variables. Raises on missing values (PROMPT-INV-03)."""
        if not isinstance(values, Mapping):
            raise PromptTemplateInvariantError(
                "PROMPT-INV-03: values MUST be a Mapping[str, str]."
            )
        declared = set(self._variables)
        provided = set(values.keys())
        missing = declared - provided
        if missing:
            raise PromptTemplateInvariantError(
                f"PROMPT-INV-03: missing values for declared variables {sorted(missing)}; "
                f"empty-string default is FORBIDDEN."
            )
        extra = provided - declared
        if extra:
            raise PromptTemplateInvariantError(
                f"PROMPT-INV-05: values contain undeclared keys {sorted(extra)}; "
                f"extra keys rejected to prevent smuggled template injection."
            )
        for k, v in values.items():
            if not isinstance(v, str):
                raise PromptTemplateInvariantError(
                    f"PROMPT-INV-05: value for {k!r} MUST be str; got {type(v).__name__}."
                )
            if len(v.encode("utf-8")) > MAX_VALUE_BYTES:
                raise PromptTemplateInvariantError(
                    f"PROMPT-INV-05: value for {k!r} exceeds {MAX_VALUE_BYTES} bytes."
                )

        # Single-pass substitution — values are treated as literal data, not
        # as template syntax. Any `{{` in a value survives verbatim.
        def _substitute(match: re.Match[str]) -> str:
            varname = match.group(1)
            return values[varname]

        return VARIABLE_PATTERN.sub(_substitute, self._text)

    def fingerprint(self) -> str:
        return self._fp

    def _compute_fingerprint(self) -> str:
        canonical = (
            f"name={self._name}\x1f"
            f"version={self._version}\x1f"
            f"target_model={self._target_model}\x1f"
            f"variables={','.join(sorted(self._variables))}\x1f"
            f"text={self._text}"
        )
        return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Registry — enforces PROMPT-INV-02 globally across (name, version)
# ---------------------------------------------------------------------------
class PromptRegistry:
    """Register prompt templates by (name, version). Re-registration FORBIDDEN."""

    def __init__(self) -> None:
        self._by_key: dict[tuple[str, int], FrozenPromptTemplate] = {}
        self._lock = threading.Lock()

    def register(self, tpl: FrozenPromptTemplate) -> None:
        key = (tpl.name, tpl.version)
        with self._lock:
            if key in self._by_key:
                existing = self._by_key[key]
                if existing.fingerprint() == tpl.fingerprint():
                    # Idempotent registration of identical object is benign.
                    return
                raise PromptTemplateInvariantError(
                    f"PROMPT-INV-02: (name={tpl.name!r}, version={tpl.version}) already "
                    f"registered with fingerprint {existing.fingerprint()}; "
                    f"mutation FORBIDDEN. Publish a new version instead."
                )
            self._by_key[key] = tpl

    def resolve(self, name: str, version: int) -> FrozenPromptTemplate:
        key = (name, version)
        with self._lock:
            if key not in self._by_key:
                raise PromptTemplateInvariantError(
                    f"PROMPT-INV-02: unknown (name={name!r}, version={version}); "
                    f"default fallback FORBIDDEN."
                )
            return self._by_key[key]

    def versions(self, name: str) -> tuple[int, ...]:
        with self._lock:
            return tuple(sorted(v for (n, v) in self._by_key if n == name))


__all__ = [
    "MAX_TEMPLATE_BYTES",
    "MAX_VALUE_BYTES",
    "VARIABLE_NAME_PATTERN",
    "VARIABLE_PATTERN",
    "FrozenPromptTemplate",
    "PromptRegistry",
    "PromptTemplate",
    "PromptTemplateInvariantError",
    "validate_name",
    "validate_variables",
    "validate_version",
]
