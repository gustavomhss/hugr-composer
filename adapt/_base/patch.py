"""Phase-4 ``patch()`` primitives shared by every compose tool.

AST-safe edits to existing Python source files.  Every helper:

* ``ast.parse`` the **resulting** source before any byte hits disk — refuse to
  write a file that wouldn't import.
* Writes atomically (tempfile in the same directory + ``os.replace``) so a crash
  mid-write never leaves a half-written file the next phase would try to parse.
* De-duplicates via a *fingerprint* substring — second run with the same
  fingerprint is a no-op returning ``False``.

Public surface (frozen by WP-WAVE0-F1):

* ``PatchError`` — raised for any patch failure (parse error, missing target).
* ``patch_add_import(file, *, module, name, alias=None)``
* ``patch_append_class_body_after_field(file, *, class_name, after_field, new_fields)``
* ``patch_append_router_endpoint(file, *, endpoint_block, fingerprint)``
* ``patch_append_module_block(file, *, block, fingerprint)``
* ``atomic_write(file, content)``

Hard rules:

* Indentation is captured from the source token's ``col_offset`` — NEVER assumed.
* Fingerprint check uses raw-substring containment (matches existing behaviour;
  no regex magic).
"""

from __future__ import annotations

import ast
import contextlib
import os
import tempfile
from pathlib import Path


class PatchError(Exception):
    """Raised when an AST-safe patch cannot be applied."""


# ---------------------------------------------------------------------------
# Atomic write
# ---------------------------------------------------------------------------


def atomic_write(file_path: Path, content: str) -> None:
    """Write *content* to *file_path* atomically.

    Strategy: write to a sibling ``NamedTemporaryFile`` in the same directory,
    then ``os.replace`` — atomic on POSIX, near-atomic on Windows.  The temp
    file lives in the destination's parent so the ``replace`` is a rename
    inside one filesystem.

    Args:
        file_path: Absolute destination path.
        content: UTF-8 text content to write.
    """
    file_path.parent.mkdir(parents=True, exist_ok=True)
    # Refuse to write a file that wouldn't parse — last line of defence.
    try:
        ast.parse(content)
    except SyntaxError as exc:
        raise PatchError(
            f"atomic_write refused: would write unparseable {file_path}: {exc}"
        ) from exc
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{file_path.name}.",
        suffix=".tmp",
        dir=str(file_path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp_path, file_path)
    except Exception:
        # Best-effort cleanup; the original target is untouched either way.
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _verify_parses(source: str, *, where: Path) -> None:
    """Raise :class:`PatchError` if *source* doesn't parse."""
    try:
        ast.parse(source)
    except SyntaxError as exc:
        raise PatchError(f"AST parse failed for {where}: {exc}") from exc


# ---------------------------------------------------------------------------
# Public patchers
# ---------------------------------------------------------------------------


def patch_add_import(
    file_path: Path,
    *,
    module: str,
    name: str,
    alias: str | None = None,
) -> bool:
    """Append ``from <module> import <name> [as <alias>]`` if not already present.

    Args:
        file_path: Existing source file to patch.
        module: Module to import from (e.g. ``"fastapi"``).
        name: Imported symbol (e.g. ``"HTTPException"``).
        alias: Optional ``as`` alias.

    Returns:
        ``True`` if the file was modified, ``False`` if the import already existed.
    """
    if not file_path.exists():
        raise PatchError(f"patch_add_import target missing: {file_path}")
    src = file_path.read_text()
    line = f"from {module} import {name} as {alias}" if alias else f"from {module} import {name}"
    if line in src:
        return False
    # Insert after the last existing top-level import to keep imports grouped.
    tree = ast.parse(src)
    last_import_line = 0
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            end = getattr(node, "end_lineno", node.lineno)
            if end and end > last_import_line:
                last_import_line = end
    src_lines = src.splitlines(keepends=True)
    if last_import_line == 0:
        new_src = line + "\n" + src
    else:
        before = "".join(src_lines[:last_import_line])
        after = "".join(src_lines[last_import_line:])
        if not before.endswith("\n"):
            before += "\n"
        new_src = before + line + "\n" + after
    _verify_parses(new_src, where=file_path)
    atomic_write(file_path, new_src)
    return True


def patch_append_class_body_after_field(
    file_path: Path,
    *,
    class_name: str,
    after_field: str,
    new_fields: list[str],
) -> bool:
    """Append ``new_fields`` to ``class_name``'s body, just after ``after_field``.

    Indentation is read from the ``after_field`` source token (NOT assumed): if the
    target field is at column 4, the new fields are written at column 4 too.  This
    is what kills the silent-dedent class-body bug that any string-replace approach
    is vulnerable to.

    Idempotent: if any of *new_fields* is already present in the source verbatim,
    returns ``False`` without writing.

    Args:
        file_path: Source file to patch.
        class_name: Name of the target class.
        after_field: Existing annotated/assigned attribute to anchor after.
        new_fields: Lines (without indentation) to insert.

    Returns:
        ``True`` if the file was modified, ``False`` on no-op.
    """
    if not file_path.exists():
        raise PatchError(f"patch_append_class_body_after_field missing: {file_path}")
    src = file_path.read_text()
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        raise PatchError(f"source unparseable: {file_path}: {exc}") from exc

    target_cls: ast.ClassDef | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            target_cls = node
            break
    if target_cls is None:
        return False  # class not present — caller's guard

    anchor: ast.stmt | None = None
    for stmt in target_cls.body:
        target_name: str | None = None
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            target_name = stmt.target.id
        elif isinstance(stmt, ast.Assign):
            for t in stmt.targets:
                if isinstance(t, ast.Name):
                    target_name = t.id
                    break
        if target_name == after_field:
            anchor = stmt
            break
    if anchor is None:
        return False  # anchor field not present — caller's guard

    indent = " " * anchor.col_offset
    if all(f.strip() in src for f in new_fields):
        return False

    src_lines = src.splitlines(keepends=True)
    end_line = getattr(anchor, "end_lineno", anchor.lineno)  # 1-based, inclusive
    insertion_idx = end_line  # insert AFTER the anchor line
    new_lines = [f"{indent}{f.rstrip()}\n" for f in new_fields]
    new_src = (
        "".join(src_lines[:insertion_idx]) + "".join(new_lines) + "".join(src_lines[insertion_idx:])
    )
    _verify_parses(new_src, where=file_path)
    atomic_write(file_path, new_src)
    return True


def _append_with_fingerprint(file_path: Path, *, block: str, fingerprint: str) -> bool:
    """Shared helper for the two append-style patchers."""
    if not file_path.exists():
        raise PatchError(f"append target missing: {file_path}")
    src = file_path.read_text()
    if fingerprint in src:
        return False
    sep = "" if src.endswith("\n") else "\n"
    new_src = src + sep + block
    if not new_src.endswith("\n"):
        new_src += "\n"
    _verify_parses(new_src, where=file_path)
    atomic_write(file_path, new_src)
    return True


def patch_append_router_endpoint(
    file_path: Path,
    *,
    endpoint_block: str,
    fingerprint: str,
) -> bool:
    """Append a router endpoint to an existing FastAPI route module.

    Fingerprint-guarded: if *fingerprint* already appears in the source, returns
    ``False`` without writing.  The resulting file is ast.parsed before write.

    Args:
        file_path: ``app/api/routes/<x>.py``.
        endpoint_block: Full block to append (imports + ``@router.<verb>(...)`` + handler).
        fingerprint: Substring whose presence means "already applied" (e.g. the new
            handler's name).

    Returns:
        ``True`` if appended, ``False`` if the fingerprint was already present.
    """
    return _append_with_fingerprint(file_path, block=endpoint_block, fingerprint=fingerprint)


def patch_append_module_block(
    file_path: Path,
    *,
    block: str,
    fingerprint: str,
) -> bool:
    """Append a free module-level block (e.g. a new function + imports) to a file.

    Fingerprint-guarded; ast.parsed before write; atomic.

    Args:
        file_path: Target ``.py`` file.
        block: Text to append.
        fingerprint: Substring whose presence means "already applied".

    Returns:
        ``True`` if appended, ``False`` if the fingerprint was already present.
    """
    return _append_with_fingerprint(file_path, block=block, fingerprint=fingerprint)
