"""Phase-3 ``write()`` primitives — template loading + rendering.

Templates are plain text under each tool's ``templates/`` directory and use
``string.Template`` (``$name`` / ``${name}``) — NOT Jinja, NOT f-strings.
Strict substitution: any missing key raises ``KeyError`` so a typoed
substitution fails loudly instead of silently emitting ``$foo`` into a source
file.

Public surface (frozen by WP-WAVE0-F1):

* ``TemplateError``
* ``load_template(caller_dir, name)``
* ``render(caller_dir, name, substitutions)``
* ``render_to(caller_dir, name, *, dest, substitutions)``

Hard rules:

* Strict substitution (``.substitute`` not ``.safe_substitute``).
* ``ast.parse`` the rendered result before write.
* ``render_to`` is atomic + creates parent dirs.
* Defence in depth: refuses to write outside ``caller_dir.parent`` is intentionally
  NOT enforced here (templates may legitimately emit into any project path); the
  tool entrypoint is responsible for keeping ``dest`` inside ``project_dir``.
"""

from __future__ import annotations

import ast
import contextlib
import os
import tempfile
from pathlib import Path
from string import Template


class TemplateError(Exception):
    """Raised when a template is missing, malformed, or renders to bad source."""


def _templates_dir(caller_dir: Path) -> Path:
    return caller_dir / "templates"


def load_template(caller_dir: Path, name: str) -> Template:
    """Load ``<caller_dir>/templates/<name>`` as a ``string.Template``.

    Args:
        caller_dir: The tool package directory (typically ``Path(__file__).parent``).
        name: File name under the ``templates/`` subdirectory.

    Returns:
        A ``string.Template`` ready for ``.substitute``.

    Raises:
        TemplateError: When the file does not exist.
    """
    path = _templates_dir(caller_dir) / name
    if not path.is_file():
        raise TemplateError(f"template not found: {path}")
    return Template(path.read_text())


def render(
    caller_dir: Path,
    name: str,
    substitutions: dict[str, str],
) -> str:
    """Render ``<caller_dir>/templates/<name>`` with strict substitution.

    Args:
        caller_dir: The tool package directory.
        name: File name under ``templates/``.
        substitutions: Mapping of ``$name`` placeholders to their values.

    Returns:
        Rendered text.

    Raises:
        TemplateError: On missing key, malformed template, or unparseable result.
    """
    tpl = load_template(caller_dir, name)
    try:
        rendered = tpl.substitute(substitutions)
    except KeyError as exc:
        raise TemplateError(f"template {name}: missing substitution key {exc!s}") from exc
    except ValueError as exc:
        raise TemplateError(f"template {name}: malformed placeholder: {exc}") from exc
    return rendered


def render_to(
    caller_dir: Path,
    name: str,
    *,
    dest: Path,
    substitutions: dict[str, str],
) -> Path:
    """Render a template, ``ast.parse``-verify, and atomically write to *dest*.

    Args:
        caller_dir: The tool package directory.
        name: File name under ``templates/``.
        dest: Destination path (parent dirs are created).
        substitutions: Mapping passed to :func:`render`.

    Returns:
        The destination path.

    Raises:
        TemplateError: On render failure or unparseable result.
    """
    rendered = render(caller_dir, name, substitutions)
    # Only enforce parseability for ``.py`` outputs.  Non-Python templates
    # (none today; reserved for future ``.html``/``.toml``) pass through.
    if dest.suffix == ".py":
        try:
            ast.parse(rendered)
        except SyntaxError as exc:
            raise TemplateError(
                f"rendered template {name} does not parse as Python: {exc}"
            ) from exc
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{dest.name}.",
        suffix=".tmp",
        dir=str(dest.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(rendered)
        os.replace(tmp_path, dest)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise
    return dest
