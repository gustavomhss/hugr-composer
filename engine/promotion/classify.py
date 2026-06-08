"""Classify every staged primitive into an action-focused verdict.

Default stance: **make it work, don't delete**. Every verdict except
REDUNDANT points to a concrete path-to-functionality (promote it, fill
its shell, extract the motor/adapter pair, or wait for a caller).
REDUNDANT is reserved for items where both motor and adapter already
ship — the user may still choose to keep them as reference copies.

Decision tree (evaluated in order — first match wins):

1. `duplicate_of_registered` set → REDUNDANT
   (same name as a registered primitive; staged copy adds no value).

2. Framework-coupled AND motor registered AND adapter exists
       → REDUNDANT.

3. Framework-coupled AND motor registered AND adapter missing
       → PROMOTE_AS_ADAPTER
       (the staged item can become `_adapters/fastapi/<Motor>Adapter.py`).

4. Framework-coupled AND motor NOT registered
       → EXTRACT_MOTOR_PAIR
       (needs splitting into framework-free primitive + adapter).

5. Physically quarantined (non-framework-coupled)
       → NEEDS_REVIEW (the extraction gate rejected it for a non-framework
       reason; a human must inspect before any signal-driven path can apply).
       Quarantined items short-circuit the signal/shell flow on purpose:
       silently routing them through FILL_AND_PROMOTE or NEEDS_CALLER would
       paper over the underlying rejection rationale.

6. No §A12(b) signal → NEEDS_CALLER.

7. Signal + shell incomplete (REPLACE_ME or stub tests)
       → FILL_AND_PROMOTE (with blockers listing what to fill).

8. Signal + clean shell + (concurrency OR mutable state)
       → PROMOTE_AS_PRIMITIVE (tier=full; requires .tla spec).

9. Signal + clean shell + lite-eligible
       → PROMOTE_AS_PRIMITIVE (tier=lite; requires §B1.7 ratification).

10. Fallthrough → NEEDS_REVIEW.

Every verdict carries a `blockers` list: preconditions the executor must
see resolved before it runs. Non-empty blockers = documentation, not yet
executable.
"""

from __future__ import annotations

from hugr_core.promotion.classify import (
    _classify_single as _core_classify_single,
)
from hugr_core.promotion.classify import (
    _describe_blockers,
    _lite_eligible,
    _motor_is_registered,
    _motor_name,
    _strong,
    _tla_required_reason,
)
from hugr_core.promotion.classify import (
    adapter_exists as _core_adapter_exists,
)
from hugr_core.promotion.classify import (
    classify_all as _core_classify_all,
)
from hugr_core.promotion.classify import (
    classify_primitive as _core_classify_primitive,
)
from hugr_core.promotion.classify import (
    main as _core_main,
)

from engine.promotion.config import build_config

__all__ = [
    "classify_all",
    "classify_primitive",
    "main",
    "_classify_single",
    "_adapter_exists",
    "_motor_name",
    "_motor_is_registered",
    "_lite_eligible",
    "_describe_blockers",
    "_strong",
    "_tla_required_reason",
]


def _adapter_exists(motor: str) -> bool:
    return _core_adapter_exists(build_config(), motor)


def _classify_single(state, signals, registered_names=None):
    # NOTE: pass `_adapter_exists` by NAME so tests that monkeypatch
    # `engine.promotion.classify._adapter_exists` are honoured at call time.
    return _core_classify_single(state, signals, registered_names, adapter_exists=_adapter_exists)


def classify_primitive(primitive_dir, name, namespace, is_quarantined, registered_names, catalog):
    return _core_classify_primitive(
        build_config(), primitive_dir, name, namespace, is_quarantined, registered_names, catalog
    )


def classify_all():
    return _core_classify_all(build_config())


def main() -> int:
    return _core_main(build_config())


if __name__ == "__main__":
    raise SystemExit(main())
