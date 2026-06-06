"""TOOL-025: add_sqladmin — add a production-grade admin panel to a FastAPI project.

Writes an ``app/admin/`` package containing a SQLAdmin setup module,
authentication backend (superuser-gated), and auto-generated ModelView
classes for every SQLAlchemy model discovered in ``app/models/__init__.py``.

The tool is idempotent: a second run detects ``setup_admin`` in
``app/admin/setup.py`` and returns ``status="no_op"``.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_resiliency_add_sqladmin",
    "description": "Add a production-grade admin panel (SQLAdmin) with superuser-only auth and auto-generated model views.",
    "tags": ["extend", "infrastructure"],
    "entry": "add_sqladmin",
}


def add_sqladmin(
    inp: ToolInput,
    *,
    admin_path: str = "/admin",
    admin_title: str = "Admin Panel",
    require_superuser: bool = True,
) -> ToolResult:
    """Add a production-grade SQLAdmin panel to a FastAPI project.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and
            optional ``dry_run`` flag.
        admin_path: URL path where the admin panel is mounted.
        admin_title: Title displayed in the admin panel header.
        require_superuser: Whether only superusers can access the panel.

    Returns:
        ``ToolResult`` with status, files_created, files_modified,
        notes, and next_steps.
    """
    start = time.monotonic()
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_ms(start))

    from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.BASE_MODEL,
        Prereq.MODELS_INIT,
        Prereq.CONFIG_SETTINGS,
        Prereq.REQUIREMENTS_TXT,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=[
                "These prerequisites cannot be auto-created.",
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
            ],
            execution_time_ms=_ms(start),
        )

    files_created: list[str] = []
    if scaffolded:
        files_created.extend(scaffolded)

    project = Path(inp.project_dir)
    app_dir = project / "app"

    setup_file = app_dir / "admin" / "setup.py"
    if setup_file.exists() and "setup_admin" in setup_file.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "setup_admin already present in app/admin/setup.py — SQLAdmin already installed, skipped."
            ],
            execution_time_ms=_ms(start),
        )

    models_init = app_dir / "models" / "__init__.py"
    models = _discover_models(models_init) if models_init.exists() else [("User", "app.models.user")]
    model_names = [name for name, _ in models]
    require_str = "True" if require_superuser else "False"

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/admin/__init__.py, app/admin/setup.py,",
                "         app/admin/auth.py, app/admin/views.py.",
                f"         admin_path={admin_path!r}, admin_title={admin_title!r}, "
                f"require_superuser={require_superuser}.",
                f"         Models: {', '.join(model_names)}.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_ms(start),
        )

    files_modified: list[str] = []
    admin_dir = app_dir / "admin"
    admin_dir.mkdir(parents=True, exist_ok=True)

    init_file = admin_dir / "__init__.py"
    render_to(_HERE, "admin_init.py.tmpl", dest=init_file, substitutions={})
    files_created.append(str(init_file))

    auth_file = admin_dir / "auth.py"
    _write_and_replace(
        "auth.py.tmpl",
        auth_file,
        {"REQUIRE_SUPERUSER_PLACEHOLDER": require_str},
    )
    files_created.append(str(auth_file))

    views_file = admin_dir / "views.py"
    views_content = _build_views_content(models)
    views_file.write_text(views_content)
    files_created.append(str(views_file))

    setup_file.parent.mkdir(parents=True, exist_ok=True)
    _write_and_replace(
        "setup.py.tmpl",
        setup_file,
        {"ADMIN_PATH_PLACEHOLDER": admin_path, "ADMIN_TITLE_PLACEHOLDER": admin_title},
    )
    files_created.append(str(setup_file))

    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file, admin_path, admin_title, require_str)
        files_modified.append(str(config_file))

    main_file = app_dir / "main.py"
    if main_file.exists():
        _patch_main(main_file)
        files_modified.append(str(main_file))

    requirements_file = project / "requirements.txt"
    if requirements_file.exists():
        _patch_requirements(requirements_file)
        files_modified.append(str(requirements_file))

    env_example = project / ".env.example"
    if env_example.exists():
        _patch_env_example(env_example)
        files_modified.append(str(env_example))

    _emit_project_test(project, files_created)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "SQLAdmin panel added: setup module, auth backend "
            "(superuser-gated), auto-generated ModelView views.",
            f"Admin mounted at {admin_path!r} with title {admin_title!r}.",
            f"ModelView classes generated for: {', '.join(model_names)}.",
            "SessionMiddleware registered in setup_admin() for cookie-based sessions.",
            "sqladmin is imported lazily inside setup_admin() — app boots without it.",
            "Sensitive columns (hashed_password, secret_enc, entry_hash, prev_hash) excluded.",
        ],
        next_steps=[
            "pip install -r requirements.txt  # installs sqladmin + itsdangerous",
            "Restart the FastAPI app so the admin panel is mounted.",
            f"Visit {admin_path} and log in with a superuser account.",
        ],
        execution_time_ms=_ms(start),
    )


def _write_and_replace(tmpl_name: str, dest: Path, replacements: dict[str, str]) -> None:
    """Read a template verbatim and apply plain-string replacements.

    Args:
        tmpl_name: Template filename under templates/.
        dest: Destination path to write.
        replacements: Dict of marker -> replacement string.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = (_HERE / "templates" / tmpl_name).read_text()
    for marker, value in replacements.items():
        content = content.replace(marker, value)
    dest.write_text(content)


def _discover_models(models_init: Path) -> list[tuple[str, str]]:
    """Extract (class_name, module_path) pairs from app/models/__init__.py.

    Reading the real module path from each ``from app.models.<mod> import
    <Name>`` statement (rather than guessing ``<name>.lower()``) is required:
    multi-word models live in snake_case modules (``EmailDelivery`` →
    ``app.models.email_delivery``), so the lowercase-no-underscore guess
    produced an unimportable path and broke admin boot in tool chains.

    Args:
        models_init: Path to app/models/__init__.py.

    Returns:
        Sorted list of (class_name, module_path) pairs; falls back to
        ``[("User", "app.models.user")]``.
    """
    try:
        tree = ast.parse(models_init.read_text())
    except SyntaxError:
        return [("User", "app.models.user")]
    pairs: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.startswith("app.models.")
        ):
            for alias in node.names:
                real_name = alias.asname or alias.name
                if real_name[0].isupper() and real_name != "Base":
                    pairs.append((real_name, node.module))
    return sorted(pairs) if pairs else [("User", "app.models.user")]


def _build_views_content(models: list[tuple[str, str]]) -> str:
    """Generate app/admin/views.py source for all discovered models.

    Args:
        models: List of (class_name, module_path) pairs to generate views for.

    Returns:
        Complete Python source code as a string.
    """
    header = (_HERE / "templates" / "views_header.py.tmpl").read_text()
    imports_block = "\n".join(
        f"from {module} import {name}" for name, module in models
    )
    view_classes = [_build_single_view(name) for name, _ in models]
    model_admins_list = ", ".join(f"{name}Admin" for name, _ in models)
    return (
        header
        + imports_block
        + "\n\n"
        + "\n\n".join(view_classes)
        + "\n\n"
        + f"MODEL_ADMINS: list[type] = [{model_admins_list}]\n"
    )


def _build_single_view(name: str) -> str:
    """Generate a single ModelView class for the given model name.

    Args:
        name: The model class name (e.g. "User").

    Returns:
        Python class definition as a string.
    """
    can_delete = "False" if name == "User" else "True"
    icon = "fa-solid fa-user" if name == "User" else "fa-solid fa-database"
    if name.endswith("s"):
        plural = name + "es"
    elif name.endswith("y"):
        plural = name[:-1] + "ies"
    else:
        plural = name + "s"
    return (
        f"class {name}Admin(ModelView, model={name}):\n"
        f'    """Admin view for the {name} model."""\n\n'
        "    column_exclude_list = [\n"
        '        "hashed_password", "secret_enc", "entry_hash", "prev_hash",\n'
        "    ]\n"
        '    column_sortable_list = "__all__"\n'
        f"    can_delete = {can_delete}\n"
        f'    name = "{name}"\n'
        f'    name_plural = "{plural}"\n'
        f'    icon = "{icon}"\n'
    )


def _emit_project_test(project: Path, created: list[str]) -> None:
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_sqladmin_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_sqladmin_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


def _patch_config(config_file: Path, admin_path: str, admin_title: str, require_str: str) -> None:
    src = config_file.read_text()
    if "ADMIN_PATH" in src:
        return
    block = (
        "\n"
        "    # --- Admin panel — added by add_sqladmin tool ---\n"
        f'    ADMIN_PATH: str = "{admin_path}"\n'
        f'    ADMIN_TITLE: str = "{admin_title}"\n'
        f"    ADMIN_REQUIRE_SUPERUSER: bool = {require_str}\n"
    )
    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    if anchor in src:
        src = src.replace(anchor, anchor + "\n" + block.lstrip("\n"))
    else:
        settings_line = "settings = Settings()"
        if settings_line in src:
            src = src.replace(settings_line, block.lstrip("\n") + "\n\n" + settings_line)
        else:
            src = src.rstrip("\n") + "\n" + block
    config_file.write_text(src)


def _patch_main(main_file: Path) -> None:
    src = main_file.read_text()
    if "setup_admin" in src:
        return
    lines = src.splitlines()
    new_lines: list[str] = []
    admin_import_added = False
    admin_setup_added = False
    for i, line in enumerate(lines):
        new_lines.append(line)
        if (
            not admin_import_added
            and line.startswith("from app.")
            and (i + 1 >= len(lines) or not lines[i + 1].startswith(("from ", "import ")))
        ):
            new_lines.append("from app.admin.setup import setup_admin")
            admin_import_added = True
        if not admin_setup_added and "register_middleware(app" in line:
            new_lines.append("")
            new_lines.append("# --- SQLAdmin panel ---")
            new_lines.append("setup_admin(app)")
            admin_setup_added = True
    if not admin_setup_added:
        if not admin_import_added:
            new_lines.insert(0, "from app.admin.setup import setup_admin")
        new_lines.append("")
        new_lines.append("setup_admin(app)")
    result = "\n".join(new_lines)
    if src.endswith("\n") and not result.endswith("\n"):
        result += "\n"
    main_file.write_text(result)


def _patch_requirements(requirements_file: Path) -> None:
    src = requirements_file.read_text()
    additions: list[str] = []
    if "sqladmin" not in src:
        additions.append("sqladmin>=0.19.0")
    if "itsdangerous" not in src:
        additions.append("itsdangerous>=2.2.0")
    if not additions:
        return
    trailing = "" if src.endswith("\n") else "\n"
    requirements_file.write_text(src + trailing + "\n".join(additions) + "\n")


def _patch_env_example(env_example: Path) -> None:
    src = env_example.read_text()
    if "ADMIN_PATH" in src:
        return
    trailing = "" if src.endswith("\n") else "\n"
    block = (
        "\n"
        "# --- SQLAdmin panel (add_sqladmin) ---\n"
        "# ADMIN_PATH=/admin\n"
        "# ADMIN_TITLE=Admin Panel\n"
        "# ADMIN_REQUIRE_SUPERUSER=true\n"
    )
    env_example.write_text(src + trailing + block)


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
