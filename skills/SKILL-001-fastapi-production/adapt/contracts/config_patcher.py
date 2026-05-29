"""Shared helper for patching `app/core/config.py` with new Settings fields.

Replaces hand-rolled `_patch_config` routines that used text-level
replacement (`content.replace("settings = Settings()", new_fields + "\nsettings = Settings()")`).
The hand-rolled pattern breaks when the fixture config has comments or
blank lines between the `Settings` class body and the module-level
`settings = Settings()` instantiation — the "new fields" end up outside
the class with 4-space indentation, which Python then rejects as an
`IndentationError: unexpected indent`.

This module parses `config.py` with `ast`, locates the `Settings` class,
and inserts new field lines INTO the class body — guaranteed to stay
inside the class regardless of layout.

Usage::

    from adapt.contracts.config_patcher import patch_settings_fields, PatchResult

    result = patch_settings_fields(
        app_dir / "core" / "config.py",
        fields=[
            ('TEMPORAL_HOST', 'TEMPORAL_HOST: str = "localhost:7233"'),
            ('TEMPORAL_NAMESPACE', 'TEMPORAL_NAMESPACE: str = "default"'),
        ],
    )
    if result is PatchResult.APPLIED:
        files_modified.append(str(config_file))
    elif result in (PatchResult.TARGET_MISSING, PatchResult.SYNTAX_ERROR):
        notes.append(f"config.py not patched: {result.name}")

Each entry is ``(field_name, field_line)``. `field_name` is used for the
idempotency check: if that token already appears anywhere in `config.py`
the field is not re-added. `field_line` is the raw content WITHOUT
leading indent (the helper adds 4-space indent automatically).

Return values (F-007 — structured PatchResult):

* ``PatchResult.APPLIED`` — file was modified on disk.
* ``PatchResult.ALREADY_PRESENT`` — all requested fields already exist; no-op.
* ``PatchResult.TARGET_MISSING`` — config.py absent OR no ``Settings``
  class was found in it (the helper fell back to module-level append).
* ``PatchResult.SYNTAX_ERROR`` — config.py had a syntax error OR the
  patched output would have introduced one; nothing was written.

Callers SHOULD only treat ``APPLIED`` as "I modified config.py". The
helper is backwards-compatible: ``PatchResult.APPLIED`` is truthy,
every other result is falsy, so ``if patch_settings_fields(...): ...``
still works.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from enum import Enum
from pathlib import Path

_CLASS_INDENT = "    "


class PatchResult(Enum):
    """Outcome of a ``patch_settings_fields`` call.

    Members:
        APPLIED: File was written on disk. Truthy.
        ALREADY_PRESENT: All requested fields already exist. Falsy.
        TARGET_MISSING: config.py absent or has no ``Settings`` class
            shape; module-level fallback may have been written. Falsy.
        SYNTAX_ERROR: Existing file or patched output had a syntax
            error; nothing was written. Falsy.
    """

    APPLIED = "applied"
    ALREADY_PRESENT = "already_present"
    TARGET_MISSING = "target_missing"
    SYNTAX_ERROR = "syntax_error"

    def __bool__(self) -> bool:
        """Truthy only for APPLIED so ``if patch_settings_fields(...)`` keeps working."""
        return self is PatchResult.APPLIED


def patch_settings_fields(
    config_file: Path,
    *,
    fields: Iterable[tuple[str, str]],
) -> PatchResult:
    """Insert new fields into the ``Settings`` class body.

    Returns a ``PatchResult`` describing the outcome. The result is
    backwards-compatible with the old boolean return: ``APPLIED`` is
    truthy, every other value is falsy.

    Idempotent: fields whose `name` token is already present anywhere in
    the file are skipped. A no-op call (all fields already present)
    returns ``ALREADY_PRESENT`` without writing.
    """
    if not config_file.exists():
        return PatchResult.TARGET_MISSING

    content = config_file.read_text(encoding="utf-8")
    missing = [line for name, line in fields if name not in content]
    if not missing:
        return PatchResult.ALREADY_PRESENT

    try:
        tree = ast.parse(content)
    except SyntaxError:
        # Don't corrupt a file that's already broken — surface via return.
        return PatchResult.SYNTAX_ERROR

    settings_cls: ast.ClassDef | None = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Settings":
            settings_cls = node
            break

    if settings_cls is None or not settings_cls.body:
        # No Settings class shape — fall back to module-level append so the
        # field names at least exist + Python parses, but tell the caller we
        # could not honour the contract via TARGET_MISSING.
        if not content.endswith("\n"):
            content += "\n"
        content += "\n" + "\n".join(missing) + "\n"
        config_file.write_text(content, encoding="utf-8")
        return PatchResult.TARGET_MISSING

    last_body_node = settings_cls.body[-1]
    insert_after_line = getattr(last_body_node, "end_lineno", last_body_node.lineno)

    lines = content.splitlines(keepends=True)
    prefix = lines[:insert_after_line]
    suffix = lines[insert_after_line:]
    injected = "".join(f"{_CLASS_INDENT}{line}\n" for line in missing)

    new_content = "".join(prefix) + injected + "".join(suffix)

    # Validate the result is parseable before writing — a small price to
    # pay to guarantee we never corrupt a generated project.
    try:
        ast.parse(new_content)
    except SyntaxError:
        return PatchResult.SYNTAX_ERROR

    config_file.write_text(new_content, encoding="utf-8")
    return PatchResult.APPLIED
