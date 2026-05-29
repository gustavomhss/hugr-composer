"""Generator for Pydantic v2 input (create/update) schemas."""

from __future__ import annotations

from pathlib import Path

# Mapping from user-friendly type names to (python_type, field_constraints).
# field_constraints is a dict of keyword args for ``Field(...)``.
_TYPE_MAP: dict[str, tuple[str, dict[str, object]]] = {
    "str": ("str", {"max_length": 255}),
    "text": ("str", {"max_length": 65_535}),
    "int": ("int", {"ge": 0, "le": 2_147_483_647}),
    "float": ("float", {"ge": 0.0}),
    "bool": ("bool", {}),
    "Decimal": ("Decimal", {"ge": 0, "max_digits": 12, "decimal_places": 2}),
    "decimal": ("Decimal", {"ge": 0, "max_digits": 12, "decimal_places": 2}),
    "date": ("date", {}),
    "datetime": ("datetime", {}),
    "EmailStr": ("EmailStr", {"max_length": 255}),
    "email": ("EmailStr", {"max_length": 255}),
    "url": ("HttpUrl", {}),
    "password": ("str", {"min_length": 8, "max_length": 128}),
    "uuid": ("UUID", {}),
}


def generate_input_schema(
    output_dir: str,
    name: str,
    fields: dict[str, str],
    validators: dict[str, str] | None = None,
) -> dict:
    """Generate a Pydantic v2 input schema (for create requests).

    The generated schema sets ``model_config = ConfigDict(extra="forbid")``
    so unknown fields are rejected at validation time. Note: it does NOT
    set ``strict=True`` — JSON-payload coercion (``"42"`` → 42, ``"9.99"``
    → Decimal) is intentionally still allowed so HTTP request bodies
    don't need every field pre-coerced client-side. Codex 3 F-013 closed
    the prior drift where this docstring + emitted notes advertised a
    strict-mode contract the code did not deliver. Per-field
    constraints:

    * String fields always have ``max_length``.
    * Numeric fields have ``ge`` / ``le`` bounds.
    * Password fields: ``min_length=8, max_length=128`` PLUS the
      project ``password_strength_validator`` (digit + uppercase +
      blocklist) when ``schemas/password_policy.py`` is also present
      (Codex 3 F-008).
    * Email fields: ``EmailStr`` with ``max_length=255``.
    * Optional fields are typed as ``T | None = None``.

    Args:
        output_dir: Directory root (``schemas/`` subdir is created
            automatically).
        name: Model name in PascalCase (e.g. ``User``).
        fields: Mapping of field_name -> type hint string.  Accepted
            values match the keys in ``_TYPE_MAP`` (``str``, ``text``,
            ``int``, ``float``, ``bool``, ``Decimal``, ``date``,
            ``datetime``, ``EmailStr``, ``email``, ``url``,
            ``password``, ``uuid``).  Suffix a type with ``?`` to mark
            it optional (e.g. ``"str?"``).
        validators: Optional mapping of field_name -> validator body
            (Python expression string).  Each entry generates a
            ``@field_validator`` classmethod.

    Returns:
        Dict with ``files_created`` and ``notes``.
    """
    out = Path(output_dir) / "schemas"
    out.mkdir(parents=True, exist_ok=True)

    class_name = name if name[0].isupper() else name.capitalize()

    # ------------------------------------------------------------------
    # Collect imports
    # ------------------------------------------------------------------
    stdlib_imports: set[str] = set()
    pydantic_imports: set[str] = {"BaseModel", "ConfigDict", "Field"}
    extra_pydantic_imports: set[str] = set()
    need_field_validator = bool(validators)

    # Codex 3 F-008: when the schema declares a ``password`` field, wire
    # the project-wide ``password_strength_validator`` into the emitted
    # class. The generated User schemas (and any future password-bearing
    # input schema) thus enforce digit + uppercase + blocklist instead of
    # just length — closing the "policy generated but never applied"
    # drift the hunt caught.
    password_fields: list[str] = []
    for fname, raw in fields.items():
        if raw.rstrip("?") == "password":
            password_fields.append(fname)
    if password_fields:
        pydantic_imports.add("field_validator")

    if need_field_validator:
        pydantic_imports.add("field_validator")

    parsed_fields: list[
        tuple[str, str, bool, dict[str, object]]
    ] = []  # (name, py_type, optional, constraints)

    for field_name, raw_type in fields.items():
        optional = raw_type.endswith("?")
        type_key = raw_type.rstrip("?")
        entry = _TYPE_MAP.get(type_key, ("str", {"max_length": 255}))
        py_type, constraints = entry

        if py_type == "Decimal":
            stdlib_imports.add("decimal")
        if py_type in ("date", "datetime"):
            stdlib_imports.add("datetime")
        if py_type == "EmailStr":
            extra_pydantic_imports.add("EmailStr")
        if py_type == "HttpUrl":
            extra_pydantic_imports.add("HttpUrl")
        if py_type == "UUID":
            stdlib_imports.add("uuid")

        parsed_fields.append((field_name, py_type, optional, dict(constraints)))

    # ------------------------------------------------------------------
    # Build import block
    # ------------------------------------------------------------------
    import_lines: list[str] = []
    import_lines.append(f'"""Input schema for {class_name}."""')
    import_lines.append("")
    import_lines.append("from __future__ import annotations")
    import_lines.append("")

    # stdlib
    if "datetime" in stdlib_imports:
        # Only import what we need
        dt_names: list[str] = []
        for _, py_type, _, _ in parsed_fields:
            if py_type == "date" and "date" not in dt_names:
                dt_names.append("date")
            if py_type == "datetime" and "datetime" not in dt_names:
                dt_names.append("datetime")
        import_lines.append(f"from datetime import {', '.join(sorted(dt_names))}")
    if "decimal" in stdlib_imports:
        import_lines.append("from decimal import Decimal")
    if "uuid" in stdlib_imports:
        import_lines.append("from uuid import UUID")
    if stdlib_imports:
        import_lines.append("")

    # pydantic
    all_pydantic = sorted(pydantic_imports | extra_pydantic_imports)
    import_lines.append(f"from pydantic import {', '.join(all_pydantic)}")
    # F-008: pull the project password policy validator at module level
    # whenever the schema declares a password field.
    if password_fields:
        import_lines.append("from app.schemas.password_policy import password_strength_validator")
    import_lines.append("")
    import_lines.append("")

    # ------------------------------------------------------------------
    # Build class
    # ------------------------------------------------------------------
    class_lines: list[str] = []
    class_lines.append(f"class {class_name}Create(BaseModel):")
    class_lines.append(f'    """Schema for creating a new {class_name}."""')
    class_lines.append("")
    class_lines.append('    model_config = ConfigDict(extra="forbid")')
    class_lines.append("")

    for field_name, py_type, optional, constraints in parsed_fields:
        # Resolve display type
        display = _display_type(py_type)

        # Build Field(...) kwargs string
        field_kwargs = _format_field_kwargs(constraints)

        if optional:
            if field_kwargs:
                class_lines.append(
                    f"    {field_name}: {display} | None = Field(default=None, {field_kwargs})"
                )
            else:
                class_lines.append(f"    {field_name}: {display} | None = None")
        else:
            if field_kwargs:
                class_lines.append(f"    {field_name}: {display} = Field({field_kwargs})")
            else:
                class_lines.append(f"    {field_name}: {display}")

    # ------------------------------------------------------------------
    # Password policy validator hook (Codex 3 F-008)
    #
    # For every password-typed field, attach the project-wide
    # ``password_strength_validator`` (defined in
    # ``app/schemas/password_policy.py``). The emitted class line uses
    # ``field_validator`` declaratively so the policy applies to every
    # path that constructs the model (route body, internal callers,
    # tests).
    # ------------------------------------------------------------------
    if password_fields:
        class_lines.append("")
        class_lines.append("    # Codex 3 F-008: enforce the project password policy")
        class_lines.append("    # on every password field.")
        for pf in password_fields:
            class_lines.append(
                f'    _validate_{pf} = field_validator("{pf}")(password_strength_validator)'
            )

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------
    if validators:
        class_lines.append("")
        for v_field, v_body in validators.items():
            method_name = f"validate_{v_field}"
            class_lines.append(f'    @field_validator("{v_field}")')
            class_lines.append("    @classmethod")
            class_lines.append(f"    def {method_name}(cls, v: object) -> object:")
            # Indent each line of the validator body
            for body_line in v_body.strip().splitlines():
                class_lines.append(f"        {body_line}")
            class_lines.append("")

    # ------------------------------------------------------------------
    # Update schema (partial, all fields optional)
    # ------------------------------------------------------------------
    class_lines.append("")
    class_lines.append("")
    class_lines.append(f"class {class_name}Update(BaseModel):")
    class_lines.append(f'    """Schema for partially updating a {class_name}."""')
    class_lines.append("")
    class_lines.append('    model_config = ConfigDict(extra="forbid")')
    class_lines.append("")

    for field_name, py_type, _optional, constraints in parsed_fields:
        display = _display_type(py_type)
        field_kwargs = _format_field_kwargs(constraints)

        if field_kwargs:
            class_lines.append(
                f"    {field_name}: {display} | None = Field(default=None, {field_kwargs})"
            )
        else:
            class_lines.append(f"    {field_name}: {display} | None = None")

    # ------------------------------------------------------------------
    # Assemble & write
    # ------------------------------------------------------------------
    full_content = "\n".join(import_lines + class_lines) + "\n"

    file_path = out / f"{name.lower()}.py"
    file_path.write_text(full_content)

    notes = [
        f"Generated schemas/{name.lower()}.py with {class_name}Create and {class_name}Update.",
        # F-013: drop the false "strict=True" claim. The emitted
        # ConfigDict only sets extra="forbid"; JSON coercion is allowed.
        f'{len(parsed_fields)} field(s), extra="forbid", all constraints applied.',
    ]
    if password_fields:
        notes.append(
            "Password field(s) "
            + ", ".join(password_fields)
            + " gated by app.schemas.password_policy.password_strength_validator (F-008)."
        )
    if validators:
        notes.append(
            f"{len(validators)} custom field_validator(s) added: "
            + ", ".join(validators.keys())
            + "."
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


def _format_field_kwargs(constraints: dict[str, object]) -> str:
    """Format a constraints dict as keyword-arg string for ``Field(...)``."""
    if not constraints:
        return ""
    parts: list[str] = []
    for k, v in constraints.items():
        if isinstance(v, str):
            parts.append(f"{k}={v!r}")
        else:
            parts.append(f"{k}={v}")
    return ", ".join(parts)
