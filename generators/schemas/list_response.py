"""Generator for paginated list-response wrapper schema.

This generator APPENDS the ``{Name}sPublic`` class to the existing
``schemas/{name}.py`` file (created by ``generate_input_schema`` and
extended by ``generate_output_schema``), so each entity has a single
schema file containing ``Create``, ``Update``, ``Public``, and
``sPublic`` classes.
"""

from __future__ import annotations

from pathlib import Path

from generators._pluralize import pluralize


def generate_list_response(
    output_dir: str,
    name: str,
) -> dict:
    """Append a paginated list-response schema to ``schemas/{name}.py``.

    Produces (and appends) a ``{Plural}Public`` model wrapping a list of
    ``{Name}Public`` items plus a total ``count``::

        class UsersPublic(BaseModel):
            data: list[UserPublic]
            count: int

    Uses English pluralization rules (Category -> Categories, not Categorys).

    Args:
        output_dir: Directory root (``schemas/`` subdir is created
            automatically).
        name: Model name in PascalCase (e.g. ``User``).

    Returns:
        Dict with ``files_created`` and ``notes``.
    """
    out = Path(output_dir) / "schemas"
    out.mkdir(parents=True, exist_ok=True)

    class_name = name if name[0].isupper() else name.capitalize()
    plural_class = pluralize(class_name) + "Public"

    file_path = out / f"{name.lower()}.py"
    if not file_path.exists():
        # Fallback — produce a tiny standalone file
        file_path.write_text(
            '"""Schemas for ' + class_name + '."""\n\n'
            "from __future__ import annotations\n\n"
            "from pydantic import BaseModel\n"
        )

    existing = file_path.read_text()

    # If the class is already present, skip (idempotent)
    if f"class {plural_class}(" in existing:
        return {
            "files_created": [str(file_path)],
            "notes": [
                f"{plural_class} already present in schemas/{name.lower()}.py. Skipped.",
            ],
        }

    # Ensure pydantic.BaseModel is imported
    if "BaseModel" not in existing:
        existing = existing.rstrip() + "\nfrom pydantic import BaseModel\n"

    new_class = (
        "\n\n"
        f"class {plural_class}(BaseModel):\n"
        f'    """Paginated response containing a list of {class_name} items.\n'
        "\n"
        "    Attributes:\n"
        f"        data: The page of {class_name} records.\n"
        "        count: Total number of matching records (before pagination).\n"
        '    """\n'
        "\n"
        f"    data: list[{class_name}Public]\n"
        "    count: int\n"
    )

    if not existing.endswith("\n"):
        existing += "\n"
    file_path.write_text(existing + new_class)

    return {
        "files_created": [str(file_path)],
        "notes": [
            f"Appended {plural_class} to schemas/{name.lower()}.py.",
        ],
    }
