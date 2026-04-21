"""ADAPT tool: add custom middleware to an existing FastAPI project.

Writes a middleware module and patches the middleware stack registration
so the new middleware is inserted at the correct position in Starlette's
LIFO processing order.

Usage::

    from generators.tools.add_middleware import add_middleware

    result = add_middleware(
        project_dir="/path/to/existing-project",
        name="RateLimitMiddleware",
        code='''
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import Response

    class RateLimitMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            # TODO: implement rate limiting
            return await call_next(request)
    ''',
        position="before_logging",
    )
"""

from __future__ import annotations

MCP_TOOL = {
    'name': 'fastapi_meta_add_middleware',
    'description': 'Add custom middleware to the stack at the correct position.',
    'tags': ['adapt'],
    'entry': 'add_middleware',
    'annotations': {'readOnlyHint': False},
}

import re
import textwrap
from pathlib import Path

from generators.tools._layout import resolve_app_root


# ---------------------------------------------------------------------------
# Position anchors
# ---------------------------------------------------------------------------

# Starlette processes middleware in LIFO order (last added = first to
# execute).  The default stack from ``generate_middleware_stack`` registers
# in this order:
#
#   1. RequestLoggingMiddleware   (last to execute on request)
#   2. SecurityHeadersMiddleware
#   3. CORSMiddleware
#   4. CorrelationMiddleware      (first to execute on request)
#
# So the execution order on an incoming request is:
#   Correlation -> CORS -> Security -> Logging -> App
#
# The *position* parameter controls where the new middleware is injected
# relative to these anchors.

_POSITION_ANCHORS = {
    "outermost": "CorrelationMiddleware",
    "after_cors": "CORSMiddleware",
    "before_logging": "RequestLoggingMiddleware",
    "innermost": None,  # append at the very top (first registered)
}

_VALID_POSITIONS = tuple(_POSITION_ANCHORS.keys())


def add_middleware(
    project_dir: str,
    name: str,
    code: str,
    position: str = "before_logging",
) -> dict:
    """Add custom middleware to the project's middleware stack.

    Writes the middleware class to ``middleware/{snake_name}.py`` and
    patches ``middleware/__init__.py`` (the ``register_middleware``
    function) to include it at the correct position.

    If a middleware file with the same name already exists, the
    operation is skipped.

    Args:
        project_dir: Root directory of the existing project.
        name: PascalCase class name (e.g. ``"RateLimitMiddleware"``).
        code: Full Python source of the middleware module.  Must
            define a class matching *name*.
        position: Where to insert in the stack.  One of:

            - ``"outermost"`` — before CorrelationMiddleware (runs
              first on request, last on response).
            - ``"after_cors"`` — between CORS and SecurityHeaders.
            - ``"before_logging"`` (default) — between SecurityHeaders
              and RequestLogging.
            - ``"innermost"`` — after RequestLogging (runs last on
              request, first on response, closest to the app).

    Returns:
        Dict with ``files_created``, ``files_modified``, and ``notes``.
    """
    if position not in _VALID_POSITIONS:
        raise ValueError(
            f"Invalid position {position!r}. "
            f"Choose from: {', '.join(_VALID_POSITIONS)}"
        )

    root = resolve_app_root(project_dir)
    snake = _to_snake(name)

    files_created: list[str] = []
    files_modified: list[str] = []
    notes: list[str] = []

    # ------------------------------------------------------------------
    # 1. Write the middleware module
    # ------------------------------------------------------------------
    mw_dir = root / "middleware"
    mw_dir.mkdir(parents=True, exist_ok=True)

    mw_file = mw_dir / f"{snake}.py"
    if mw_file.exists():
        return {
            "files_created": [],
            "files_modified": [],
            "notes": [
                f"Middleware file middleware/{snake}.py already exists. "
                "Skipped to avoid overwriting."
            ],
        }

    # Normalize leading whitespace (in case the caller passed an
    # indented triple-quoted string)
    cleaned_code = textwrap.dedent(code).strip() + "\n"
    mw_file.write_text(cleaned_code)
    files_created.append(str(mw_file))
    notes.append(f"Created middleware/{snake}.py with class {name}.")

    # ------------------------------------------------------------------
    # 2. Patch middleware/__init__.py (register_middleware)
    # ------------------------------------------------------------------
    init_file = mw_dir / "__init__.py"
    if not init_file.exists():
        notes.append(
            "middleware/__init__.py not found — register the middleware "
            "manually in your app startup."
        )
        return {
            "files_created": files_created,
            "files_modified": files_modified,
            "notes": notes,
        }

    content = init_file.read_text()

    # Guard: already registered
    if name in content:
        notes.append(
            f"{name} is already referenced in middleware/__init__.py. "
            "Skipped patching."
        )
        return {
            "files_created": files_created,
            "files_modified": files_modified,
            "notes": notes,
        }

    # Add import line
    import_line = f"from app.middleware.{snake} import {name}"
    content = _insert_import(content, import_line)

    # Add app.add_middleware() call at the right position
    add_line = f"    app.add_middleware({name})"
    comment_line = f"    # {name}"
    insertion = f"{comment_line}\n{add_line}\n"

    content = _insert_at_position(content, insertion, position)

    init_file.write_text(content)
    files_modified.append(str(init_file))
    notes.append(
        f"Patched middleware/__init__.py: added {name} at position={position!r}."
    )

    return {
        "files_created": files_created,
        "files_modified": files_modified,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_snake(pascal: str) -> str:
    """Convert PascalCase to snake_case."""
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", pascal)
    s = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", s)
    return s.lower()


def _insert_import(content: str, import_line: str) -> str:
    """Insert an import line after the last existing import block."""
    if import_line in content:
        return content

    lines = content.split("\n")

    last_import_idx = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(("from ", "import ")) and not stripped.startswith("# "):
            last_import_idx = i

    insert_idx = last_import_idx + 1 if last_import_idx >= 0 else 0
    lines.insert(insert_idx, import_line)

    return "\n".join(lines)


def _insert_at_position(content: str, insertion: str, position: str) -> str:
    """Insert the ``app.add_middleware(...)`` call at the correct position.

    The strategy depends on the *position*:

    - ``"outermost"``: insert AFTER the ``CorrelationMiddleware``
      ``add_middleware`` call (so the new middleware is registered
      before Correlation, meaning it runs first on request).
    - ``"after_cors"``: insert AFTER the ``CORSMiddleware`` block.
    - ``"before_logging"``: insert BEFORE the
      ``RequestLoggingMiddleware`` call.
    - ``"innermost"``: insert at the very TOP of ``register_middleware``
      body (first line registered = last to execute on request).
    """
    lines = content.split("\n")

    if position == "innermost":
        # Insert right after the def register_middleware line (+ any
        # initial variable assignments like `origins = ...`)
        func_start = _find_func_body_start(lines, "register_middleware")
        if func_start >= 0:
            lines.insert(func_start, "")
            lines.insert(func_start + 1, insertion.rstrip("\n"))
            return "\n".join(lines)

    if position == "before_logging":
        # Insert BEFORE the RequestLoggingMiddleware add_middleware call
        anchor = "RequestLoggingMiddleware"
        idx = _find_add_middleware_line(lines, anchor)
        if idx >= 0:
            # Find the comment line above it (if any) and insert before that
            comment_idx = idx
            if idx > 0 and lines[idx - 1].strip().startswith("#"):
                comment_idx = idx - 1
            lines.insert(comment_idx, insertion.rstrip("\n"))
            lines.insert(comment_idx, "")
            return "\n".join(lines)

    if position == "after_cors":
        # Insert AFTER the CORSMiddleware block (which spans multiple lines)
        anchor = "CORSMiddleware"
        idx = _find_add_middleware_block_end(lines, anchor)
        if idx >= 0:
            lines.insert(idx + 1, "")
            lines.insert(idx + 2, insertion.rstrip("\n"))
            return "\n".join(lines)

    if position == "outermost":
        # Insert AFTER the CorrelationMiddleware call (last registered
        # = first to execute, so adding after it means the new one
        # executes even before Correlation)
        anchor = "CorrelationMiddleware"
        idx = _find_add_middleware_line(lines, anchor)
        if idx >= 0:
            lines.insert(idx + 1, "")
            lines.insert(idx + 2, insertion.rstrip("\n"))
            return "\n".join(lines)

    # Fallback: append at end of function body
    lines.append("")
    lines.append(insertion.rstrip("\n"))
    return "\n".join(lines)


def _find_add_middleware_line(lines: list[str], class_name: str) -> int:
    """Find the line index of ``app.add_middleware(ClassName...)``."""
    for i, line in enumerate(lines):
        if f"add_middleware({class_name}" in line:
            return i
    return -1


def _find_add_middleware_block_end(lines: list[str], class_name: str) -> int:
    """Find the last line of a multi-line ``app.add_middleware(...)`` call."""
    start = _find_add_middleware_line(lines, class_name)
    if start < 0:
        return -1

    # If the call spans multiple lines, find the closing paren
    depth = 0
    for i in range(start, len(lines)):
        depth += lines[i].count("(") - lines[i].count(")")
        if depth <= 0:
            return i

    return start


def _find_func_body_start(lines: list[str], func_name: str) -> int:
    """Find the first statement line inside a function body.

    Returns the index of the first line that is NOT a docstring or
    blank line after the ``def func_name(...)`` declaration.
    """
    in_func = False
    in_docstring = False

    for i, line in enumerate(lines):
        stripped = line.strip()

        if not in_func:
            if re.match(rf"def\s+{func_name}\s*\(", stripped):
                in_func = True
            continue

        # Skip blank lines and docstrings
        if not stripped:
            continue

        if stripped.startswith('"""') or stripped.startswith("'''"):
            if in_docstring:
                in_docstring = False
                continue
            # Single-line docstring
            if stripped.count('"""') >= 2 or stripped.count("'''") >= 2:
                continue
            in_docstring = True
            continue

        if in_docstring:
            continue

        # First real statement in the function body
        return i

    return -1
