"""Machine-measured state inspection — skill shim over hugr_core.promotion.state.

The generic AST/file inspection lives in the shared core; this shim binds
skill-001's registry path + framework-coupling vocabulary and preserves the
public surface (``SKILL_ROOT``, ``measure``, the ``_detect_*`` / ``_count_*``
helpers) so existing imports keep resolving.
"""

from __future__ import annotations

from hugr_core.promotion.state import (
    _count_loc,
    _count_replace_me,
    _detect_concurrency,
    _detect_mutable_class_state,
    _has_tla,
    _invariants_stubbed,
    _origin_primitive_score,
    _primary_py,
    _quarantine_metadata,
    _shape_hash,
)
from hugr_core.promotion.state import (
    _detect_framework_imports as _core_detect_framework_imports,
)
from hugr_core.promotion.state import (
    _registered_primitive_names as _core_registered_primitive_names,
)
from hugr_core.promotion.state import (
    measure as _core_measure,
)

from engine.promotion.config import (
    _FRAMEWORK_MODULES,
    _IMPLICIT_FRAMEWORK_TOKENS,
    SKILL_ROOT,
    build_config,
)

__all__ = [
    "SKILL_ROOT",
    "measure",
    "_count_replace_me",
    "_detect_concurrency",
    "_detect_mutable_class_state",
    "_detect_framework_imports",
    "_registered_primitive_names",
    "_count_loc",
    "_has_tla",
    "_invariants_stubbed",
    "_origin_primitive_score",
    "_primary_py",
    "_quarantine_metadata",
    "_shape_hash",
]


def _detect_framework_imports(py_path):
    return _core_detect_framework_imports(py_path, _FRAMEWORK_MODULES, _IMPLICIT_FRAMEWORK_TOKENS)


def _registered_primitive_names():
    return _core_registered_primitive_names(SKILL_ROOT / "engine" / "primitives_by_concern.yaml")


def measure(primitive_dir, name, namespace, is_quarantined, registered_names=None):
    return _core_measure(
        build_config(), primitive_dir, name, namespace, is_quarantined, registered_names
    )
