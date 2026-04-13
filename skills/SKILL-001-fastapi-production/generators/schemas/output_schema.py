"""Generator for Pydantic v2 output (response) schemas."""

from __future__ import annotations

import textwrap
from pathlib import Path

# Mapping from user-friendly type names to the Python annotation used in
# the *output* schema.  These are simpler than input schemas because
# output schemas don't carry ``Field(...)`` constraints — they just
# reflect the ORM model shape.
_TYPE_MAP: dict[str, str] = {
    "str": "str",
    "text": "str",
    "int": "int",
    "float": "float",
    "bool": "bool",
    "Decimal": "Decimal",
    "decimal": "Decimal",
    "date": "date",
    "datetime": "datetime",
    "EmailStr": "EmailStr",
    "email": "EmailStr",
    "url": "str",
    "password": "str",  # will be excluded by default
    "uuid": "UUID",
}

# Fields that are NEVER exposed in API responses.
_DEFAULT_EXCLUDE: list[str] = ["hashed_password", "password"]

# Name patterns (substrings) that mark a field as sensitive.
# Any field whose name contains one of these substrings is automatically
# excluded from Public output schemas, regardless of explicit exclude_fields.
_SENSITIVE_SUBSTRINGS: tuple[str, ...] = ("_encrypted", "_secret", "_hashed", "_hash")


def generate_output_schema(
    output_dir: str,
    name: str,
    fields: dict[str, str],
    exclude_fields: list[str] | None = None,
) -> dict:
    """Generate a Pydantic v2 output (public response) schema.

    The generated schema:

    * Uses ``model_config = ConfigDict(from_attributes=True)`` for
      seamless ORM -> schema conversion.
    * Always includes ``id: UUID`` and ``created_at: datetime | None``.
    * Automatically excludes sensitive fields (``hashed_password``,
      ``password`` by default).

    Args:
        output_dir: Directory root (``schemas/`` subdir is created
            automatically).
        name: Model name in PascalCase (e.g. ``User``).
        fields: Mapping of field_name -> type hint string.  Same keys
            accepted as :func:`generate_input_schema`.  Suffix with
            ``?`` to mark optional.
        exclude_fields: Field names to strip from the output.  Defaults
            to ``["hashed_password", "password"]``.

    Returns:
        Dict with ``files_created`` and ``notes``.
    """
    out = Path(output_dir) / "schemas"
    out.mkdir(parents=True, exist_ok=True)

    class_name = name if name[0].isupper() else name.capitalize()
    excluded = set(exclude_fields if exclude_fields is not None else _DEFAULT_EXCLUDE)

    # ------------------------------------------------------------------
    # Determine which fields survive the exclusion
    # ------------------------------------------------------------------
    surviving: list[tuple[str, str, bool]] = []  # (name, py_type, optional)
    for field_name, raw_type in fields.items():
        if field_name in excluded:
            continue
        # Auto-exclude fields whose names contain sensitive substrings
        # (e.g. ssn_encrypted, stripe_secret, password_hashed).
        if any(substr in field_name for substr in _SENSITIVE_SUBSTRINGS):
            excluded.add(field_name)
            continue
        optional = raw_type.endswith("?")
        type_key = raw_type.rstrip("?")
        py_type = _TYPE_MAP.get(type_key, "str")
        surviving.append((field_name, py_type, optional))

    # ------------------------------------------------------------------
    # Build public schema class body (no imports — we APPEND to the
    # existing input-schema file so ``{name}Create``, ``{name}Update``,
    # and ``{name}Public`` all live in ``schemas/{name}.py``).
    # ------------------------------------------------------------------
    class_lines: list[str] = []
    class_lines.append("")
    class_lines.append("")
    class_lines.append(f"class {class_name}Public(BaseModel):")
    class_lines.append(f'    """Public response schema for {class_name}."""')
    class_lines.append("")
    class_lines.append("    model_config = ConfigDict(from_attributes=True)")
    class_lines.append("")
    class_lines.append("    id: UUID")

    for field_name, py_type, optional in surviving:
        display = _display_type(py_type)
        if optional:
            class_lines.append(f"    {field_name}: {display} | None = None")
        else:
            class_lines.append(f"    {field_name}: {display}")

    class_lines.append("    created_at: datetime | None = None")

    # ------------------------------------------------------------------
    # Determine which imports the existing input schema file is missing
    # and inject them before the first ``class`` statement.
    # ------------------------------------------------------------------
    file_path = out / f"{name.lower()}.py"
    if not file_path.exists():
        # Fallback: produce a standalone file (rare — only if caller
        # invokes output_schema without first calling input_schema).
        file_path.write_text(
            '"""Output schema for ' + class_name + '."""\n\n'
            "from __future__ import annotations\n\n"
            "from datetime import datetime\n"
            "from uuid import UUID\n\n"
            "from pydantic import BaseModel, ConfigDict\n"
        )

    existing = file_path.read_text()
    needed_symbols: set[str] = {"BaseModel", "ConfigDict"}

    # Datetime imports
    if "from datetime import" not in existing:
        dt_needed: set[str] = {"datetime"}
        for _, py_type, _ in surviving:
            if py_type == "date":
                dt_needed.add("date")
        existing = _inject_import(
            existing,
            f"from datetime import {', '.join(sorted(dt_needed))}",
        )
    else:
        # Ensure `datetime` is in the existing datetime import line
        existing = _ensure_in_import(existing, "datetime", "datetime")

    if "from uuid import UUID" not in existing:
        existing = _inject_import(existing, "from uuid import UUID")

    # Decimal?
    has_decimal = any(py_type == "Decimal" for _, py_type, _ in surviving)
    if has_decimal and "from decimal import Decimal" not in existing:
        existing = _inject_import(existing, "from decimal import Decimal")

    # EmailStr via pydantic
    needs_email = any(py_type == "EmailStr" for _, py_type, _ in surviving)
    if needs_email:
        needed_symbols.add("EmailStr")

    for sym in needed_symbols:
        existing = _ensure_in_import(existing, "pydantic", sym)

    # Append the new class(es)
    if not existing.endswith("\n"):
        existing += "\n"
    full_content = existing + "\n".join(class_lines) + "\n"
    file_path.write_text(full_content)

    excluded_actual = [f for f in excluded if f in {fn for fn, _ in fields.items()}]
    notes = [
        f"Appended {class_name}Public to schemas/{name.lower()}.py.",
        f"{len(surviving)} field(s) exposed, id and created_at always included.",
    ]
    if excluded_actual:
        notes.append(
            f"Excluded sensitive field(s): {', '.join(sorted(excluded_actual))}."
        )

    return {"files_created": [str(file_path)], "notes": notes}


# -- Helpers ---------------------------------------------------------------


def _display_type(py_type: str) -> str:
    """Convert internal type name to display string for annotations."""
    if py_type == "Decimal":
        return "Decimal"
    if py_type == "date":
        return "date"
    if py_type == "datetime":
        return "datetime"
    if py_type == "UUID":
        return "UUID"
    return py_type


def _inject_import(source: str, import_line: str) -> str:
    """Insert *import_line* before the first ``class`` definition."""
    if import_line in source:
        return source
    lines = source.splitlines()
    # Find the first ``class`` line and insert just before it, with a
    # blank line separator if none exists.
    for i, line in enumerate(lines):
        if line.startswith("class "):
            # Walk back over blank lines to the last import block
            insert_at = i
            while insert_at > 0 and lines[insert_at - 1] == "":
                insert_at -= 1
            lines.insert(insert_at, import_line)
            return "\n".join(lines) + ("\n" if source.endswith("\n") else "")
    # No class found — append at end
    return source + import_line + "\n"


def _ensure_in_import(source: str, module: str, symbol: str) -> str:
    """Ensure *symbol* is imported from *module* in *source*.

    Handles both ``from <module> import a, b`` and inserts a new import
    line if none exists yet.
    """
    import re as _re
    pattern = _re.compile(
        rf"^from {_re.escape(module)} import (?P<names>.+)$", _re.MULTILINE
    )
    match = pattern.search(source)
    if match:
        names = [n.strip() for n in match.group("names").split(",")]
        if symbol in names:
            return source
        names.append(symbol)
        new_line = f"from {module} import {', '.join(sorted(set(names)))}"
        return source[: match.start()] + new_line + source[match.end():]
    # No existing ``from module`` line — inject a fresh one
    return _inject_import(source, f"from {module} import {symbol}")
