"""ADAPT tool: add a custom endpoint to an existing FastAPI project.

Appends a single endpoint function to an existing (or new) route file.
Handles import deduplication, inline request-body schema generation,
and authentication dependency injection.

Usage::

    from generators.tools.add_endpoint import add_endpoint

    result = add_endpoint(
        project_dir="/path/to/existing-project",
        route_file="api/routes/orders.py",
        method="post",
        path="/{id}/checkout",
        name="checkout_order",
        auth="required",
        request_body={"payment_method": "str", "coupon_code": "str | None"},
        response_model="OrderPublic",
        description="Process checkout for an existing order.",
    )
"""

from __future__ import annotations

MCP_TOOL = {
    'name': 'fastapi_meta_add_endpoint',
    'description': 'Add a custom endpoint to an existing route file.',
    'tags': ['adapt'],
    'entry': 'add_endpoint',
    'annotations': {'readOnlyHint': False},
}

import re
import textwrap
from pathlib import Path

from generators.tools._layout import resolve_app_root

# ---------------------------------------------------------------------------
# Type mapping for inline request-body schemas
# ---------------------------------------------------------------------------

_PYTHON_TYPE_MAP: dict[str, str] = {
    "str": "str",
    "text": "str",
    "int": "int",
    "float": "float",
    "bool": "bool",
    "Decimal": "Decimal",
    "date": "date",
    "datetime": "datetime",
    "EmailStr": "EmailStr",
    "email": "EmailStr",
    "url": "HttpUrl",
    "uuid": "uuid.UUID",
    "UUID": "uuid.UUID",
    "dict": "dict",
    "list": "list",
}


def _resolve_type(raw: str) -> tuple[str, set[str]]:
    """Resolve a type hint string and return (resolved, extra_imports).

    Handles ``str | None``, ``list[str]``, and bare types from
    ``_PYTHON_TYPE_MAP``.  Returns the resolved type hint and a set of
    any extra imports needed (e.g. ``{"from decimal import Decimal"}``).
    """
    extra: set[str] = set()

    # Handle Optional / union with None
    is_optional = False
    inner = raw.strip()
    if inner.endswith("| None"):
        is_optional = True
        inner = inner.replace("| None", "").strip()
    elif inner.startswith("Optional["):
        is_optional = True
        inner = inner[9:-1].strip()

    resolved = _PYTHON_TYPE_MAP.get(inner, inner)

    # Track extra imports
    if resolved == "Decimal":
        extra.add("from decimal import Decimal")
    if resolved in ("date", "datetime"):
        extra.add(f"from datetime import {resolved}")
    if resolved == "EmailStr":
        extra.add("from pydantic import EmailStr")
    if resolved == "HttpUrl":
        extra.add("from pydantic import HttpUrl")
    if "uuid.UUID" in resolved:
        extra.add("import uuid")

    if is_optional:
        resolved = f"{resolved} | None"

    return resolved, extra


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def add_endpoint(
    project_dir: str,
    route_file: str,
    method: str,
    path: str,
    name: str,
    auth: str = "required",
    request_body: dict[str, str] | None = None,
    response_model: str | None = None,
    description: str = "",
) -> dict:
    """Add a single endpoint to an existing (or new) route file.

    If the route file does not exist it is created with a fresh
    ``APIRouter`` and the necessary imports.  If it already exists the
    endpoint is appended and only missing imports are added.

    It is safe to call multiple times — if a function with *name*
    already exists in the file the operation is skipped.

    Args:
        project_dir: Root directory of the existing project.
        route_file: Relative path to the route file
            (e.g. ``"api/routes/orders.py"``).
        method: HTTP method — ``"get"``, ``"post"``, ``"put"``,
            ``"patch"``, or ``"delete"``.
        path: URL path fragment (e.g. ``"/{id}/checkout"``).
        name: Python function name for the endpoint.
        auth: Authentication level.  ``"required"`` injects
            ``CurrentUser``, ``"superuser"`` injects
            ``CurrentSuperuser``, ``"none"`` skips auth entirely.
        request_body: Optional mapping of ``{field: type}`` to generate
            an inline Pydantic model named ``{Name}Body``.  When
            ``None`` the endpoint has no request body.
        response_model: Optional return-type class name
            (e.g. ``"OrderPublic"``).  When ``None`` the endpoint
            returns ``dict``.
        description: Docstring for the generated endpoint function.

    Returns:
        Dict with ``files_created``, ``files_modified``, and ``notes``.
    """
    root = resolve_app_root(project_dir)
    method = method.lower()
    if method not in ("get", "post", "put", "patch", "delete"):
        raise ValueError(f"Invalid HTTP method: {method!r}")

    file_path = root / route_file
    files_created: list[str] = []
    files_modified: list[str] = []
    notes: list[str] = []

    is_new_file = not file_path.exists()

    # ------------------------------------------------------------------
    # Read or scaffold the route file
    # ------------------------------------------------------------------
    if is_new_file:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        content = _scaffold_route_file(route_file)
        files_created.append(str(file_path))
        notes.append(f"Created new route file: {route_file}")
    else:
        content = file_path.read_text()
        files_modified.append(str(file_path))

    # ------------------------------------------------------------------
    # Guard: skip if function already exists
    # ------------------------------------------------------------------
    if re.search(rf"^(async\s+)?def\s+{name}\s*\(", content, re.MULTILINE):
        return {
            "files_created": [],
            "files_modified": [],
            "notes": [
                f"Function {name!r} already exists in {route_file}. "
                "Skipped to avoid duplicates."
            ],
        }

    # ------------------------------------------------------------------
    # Collect imports needed by this endpoint
    # ------------------------------------------------------------------
    needed_imports: list[str] = []
    extra_type_imports: set[str] = set()

    # Auth dependency
    if auth == "required":
        needed_imports.append("from app.api.deps import CurrentUser")
    elif auth == "superuser":
        needed_imports.append("from app.api.deps import CurrentSuperuser")

    # Session is always needed
    needed_imports.append("from app.core.session import SessionDep")

    # HTTPException + status (always useful)
    needed_imports.append(
        "from fastapi import APIRouter, HTTPException, Query, status"
    )

    # Pydantic BaseModel for inline schema
    if request_body:
        needed_imports.append("from pydantic import BaseModel")

    # ------------------------------------------------------------------
    # Build inline request-body schema (if provided)
    # ------------------------------------------------------------------
    schema_block = ""
    body_cls_name = ""
    if request_body:
        # PascalCase the function name: "checkout_order" -> "CheckoutOrder"
        pascal = "".join(part.capitalize() for part in name.split("_") if part)
        body_cls_name = f"{pascal}Body"
        field_lines: list[str] = []
        for field_name, type_hint in request_body.items():
            resolved, extras = _resolve_type(type_hint)
            extra_type_imports.update(extras)
            field_lines.append(f"    {field_name}: {resolved}")

        schema_block = (
            f"\n\nclass {body_cls_name}(BaseModel):\n"
            + "\n".join(field_lines)
            + "\n"
        )

    # ------------------------------------------------------------------
    # Build endpoint function
    # ------------------------------------------------------------------
    params: list[str] = ["session: SessionDep"]

    if auth == "required":
        params.append("current_user: CurrentUser")
    elif auth == "superuser":
        params.append("current_user: CurrentSuperuser")

    if request_body:
        params.append(f"body: {body_cls_name}")

    return_type = response_model if response_model else "dict"
    docstring = description if description else f"{method.upper()} {path}"

    # Decorator
    decorator = f'@router.{method}("{path}")'
    if method == "post":
        decorator = f'@router.{method}("{path}", status_code=status.HTTP_201_CREATED)'

    # Build the endpoint as a plain string with explicit indentation to avoid
    # textwrap.dedent indentation pitfalls when params_str is interpolated.
    # CRITICAL: this code lives at MODULE level (column 0), NOT inside any class.
    params_lines = "\n".join(f"    {p}," for p in params)
    placeholder_return = "{}" if return_type == "dict" else f"{return_type}.model_construct()"
    endpoint_block = (
        "\n\n\n"
        f"{decorator}\n"
        f"async def {name}(\n"
        f"{params_lines}\n"
        f") -> {return_type}:\n"
        f'    """{docstring}\n\n'
        f'    TODO: implement business logic.\n'
        f'    """\n'
        f"    # TODO: implement\n"
        f"    return {placeholder_return}  # type: ignore[return-value]\n"
    )

    # ------------------------------------------------------------------
    # Merge imports into existing content (deduplicate)
    # ------------------------------------------------------------------
    all_imports = list(extra_type_imports) + needed_imports
    imports_to_add: list[str] = []
    for imp in all_imports:
        # Extract the key symbols to check for presence
        if imp.strip() not in content:
            # More nuanced check: for "from X import A, B" lines,
            # just check if the main module reference is present
            imports_to_add.append(imp)

    imports_to_add = _deduplicate_imports(imports_to_add, content)

    if imports_to_add:
        content = _insert_imports(content, imports_to_add)

    # ------------------------------------------------------------------
    # Append schema (if any) + endpoint to the file
    # ------------------------------------------------------------------
    content = content.rstrip("\n")
    if schema_block:
        content += schema_block
    content += endpoint_block
    content += "\n"

    file_path.write_text(content)

    notes.append(
        f"Added {method.upper()} {path} -> {name}() to {route_file}."
    )
    if request_body:
        notes.append(f"Generated inline schema {body_cls_name} for request body.")
    if auth != "none":
        notes.append(f"Auth: {auth} (injected via dependency).")

    return {
        "files_created": files_created,
        "files_modified": files_modified,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _scaffold_route_file(route_file: str) -> str:
    """Return boilerplate content for a brand-new route file."""
    # Derive a tag from the filename (e.g. "orders" from "api/routes/orders.py")
    stem = Path(route_file).stem
    tag = stem.replace("_", " ").title().replace(" ", "")

    return textwrap.dedent(f'''\
        """Routes for {tag}."""

        from __future__ import annotations

        from fastapi import APIRouter, HTTPException, Query, status

        from app.core.session import SessionDep

        router = APIRouter(prefix="/{stem}", tags=["{stem}"])
    ''')


def _deduplicate_imports(
    candidates: list[str], existing_content: str,
) -> list[str]:
    """Filter out imports whose symbols are already present in the file.

    Handles both exact line matches and symbol-level deduplication
    (e.g. if ``CurrentUser`` is already imported via a different line,
    we skip adding a second import for it).
    """
    result: list[str] = []
    for imp in candidates:
        line = imp.strip()
        # Exact line already present
        if line in existing_content:
            continue

        # For "from X import Y" — check if Y is already imported
        m = re.match(r"from\s+\S+\s+import\s+(.+)", line)
        if m:
            symbols = [s.strip() for s in m.group(1).split(",")]
            # If ALL symbols are already present, skip
            if all(sym in existing_content for sym in symbols):
                continue

        # For bare "import X" — check if that exact import exists
        m2 = re.match(r"import\s+(\S+)", line)
        if m2 and f"import {m2.group(1)}" in existing_content:
            continue

        result.append(line)

    return result


def _insert_imports(content: str, imports: list[str]) -> str:
    """Insert import lines after the last existing import block."""
    lines = content.split("\n")

    # Find the last import line index
    last_import_idx = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(("from ", "import ")) and not stripped.startswith("# "):
            last_import_idx = i

    insert_idx = last_import_idx + 1 if last_import_idx >= 0 else 0

    for imp in reversed(imports):
        lines.insert(insert_idx, imp)

    return "\n".join(lines)
