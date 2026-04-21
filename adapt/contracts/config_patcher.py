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

    from adapt.contracts.config_patcher import patch_settings_fields

    patch_settings_fields(
        app_dir / "core" / "config.py",
        fields=[
            ('TEMPORAL_HOST', 'TEMPORAL_HOST: str = "localhost:7233"'),
            ('TEMPORAL_NAMESPACE', 'TEMPORAL_NAMESPACE: str = "default"'),
        ],
    )

Each entry is ``(field_name, field_line)``. `field_name` is used for the
idempotency check: if that token already appears anywhere in `config.py`
the field is not re-added. `field_line` is the raw content WITHOUT
leading indent (the helper adds 4-space indent automatically).
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable


_CLASS_INDENT = "    "


def patch_settings_fields(
    config_file: Path,
    *,
    fields: Iterable[tuple[str, str]],
) -> bool:
    """Insert new fields into the ``Settings`` class body.

    Returns True if the file was modified, False otherwise.

    Idempotent: fields whose `name` token is already present anywhere in
    the file are skipped. A no-op call (all fields already present)
    returns False without writing.
    """
    if not config_file.exists():
        return False

    content = config_file.read_text(encoding="utf-8")
    missing = [line for name, line in fields if name not in content]
    if not missing:
        return False

    try:
        tree = ast.parse(content)
    except SyntaxError:
        # Don't corrupt a file that's already broken — surface via return.
        return False

    settings_cls: ast.ClassDef | None = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Settings":
            settings_cls = node
            break

    if settings_cls is None or not settings_cls.body:
        # No Settings class. Fall back to module-level append (unindented)
        # so at minimum the field names exist and Python parses the file.
        # Callers relying on `settings.FIELD` will need to adapt.
        if not content.endswith("\n"):
            content += "\n"
        content += "\n" + "\n".join(missing) + "\n"
        config_file.write_text(content, encoding="utf-8")
        return True

    last_body_node = settings_cls.body[-1]
    insert_after_line = getattr(
        last_body_node, "end_lineno", last_body_node.lineno
    )

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
        return False

    config_file.write_text(new_content, encoding="utf-8")
    return True
