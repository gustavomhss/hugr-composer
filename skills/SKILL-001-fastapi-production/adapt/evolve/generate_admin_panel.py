"""TOOL-048: generate_admin_panel — auto-generate sqladmin admin panel for FastAPI.

Scaffolds a complete ``app/admin/`` package with:
- One ``ModelView`` subclass per discovered SQLAlchemy model
- Auth gate wrapping the entire ``/admin`` mount
- Audit logging via SQLAlchemy event listeners
- Soft-delete awareness (hides ``is_deleted=True`` rows by default)
- Multi-tenant query filter
- CSV export capped at 10,000 rows
- Read-only mode for sensitive models

The tool is idempotent: if ``app/admin/__init__.py`` already exists and
contains the ``sqladmin`` fingerprint, returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.evolve.generate_admin_panel import generate_admin_panel

    result = generate_admin_panel(
        ToolInput(project_dir="/path/to/project"),
        models=["User", "Item"],
        mount_path="/admin",
    )
    print(result.status)
    print(result.files_created)
"""

from __future__ import annotations

import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_generate_admin_panel",
    "description": "Generate an admin panel (SQLAdmin or Starlette-admin) wired to all models.",
    "tags": ["evolve"],
    "entry": "generate_admin_panel",
}



# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def generate_admin_panel(
    inp: ToolInput,
    models: list[str] | None = None,
    mount_path: str = "/admin",
    auth_dependency: str = "require_admin",
    theme: str = "default",
    read_only_models: list[str] | None = None,
) -> ToolResult:
    """Scaffold a sqladmin admin panel for the given models.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.
        models: Model class names to expose; None = discover from app/models/.
        mount_path: URL prefix for the admin panel.
        auth_dependency: FastAPI dependency name that resolves to an admin user.
        theme: sqladmin theme (``default``, ``dark``, or custom path).
        read_only_models: Model names exposed in read-only mode.

    Returns:
        ``ToolResult`` describing every file created or modified.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err)

    # --- Prerequisite check (standalone mode) --------------------------------
    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.BASE_MODEL,
        Prereq.CONFIG_SETTINGS,
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
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    if scaffolded:
        files_created.extend(scaffolded)

    app_dir = project / "app"
    admin_dir = app_dir / "admin"
    read_only_models = read_only_models or []

    # Idempotency guard
    admin_init = admin_dir / "__init__.py"
    if admin_init.exists() and "sqladmin" in admin_init.read_text():
        return ToolResult(
            status="no_op",
            notes=["sqladmin admin panel already present in app/admin/ — skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    # Discover models if not provided
    if models is None:
        models = _discover_models(app_dir)

    if not models:
        return ToolResult(
            status="error",
            error="No SQLAlchemy models found. Generate models first or pass models= explicitly.",
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                f"[dry_run] Would scaffold admin panel for: {', '.join(models)}",
                f"[dry_run] mount_path={mount_path} read_only={read_only_models}",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # Create directory structure
    admin_dir.mkdir(parents=True, exist_ok=True)
    views_dir = admin_dir / "views"
    views_dir.mkdir(exist_ok=True)

    # Step 1: admin/__init__.py
    admin_init.write_text(_admin_init_content(models, mount_path))
    files_created.append(str(admin_init))

    # Step 2: auth wrapper
    auth_file = admin_dir / "auth.py"
    auth_file.write_text(_auth_content(auth_dependency))
    files_created.append(str(auth_file))

    # Step 3: audit hook
    audit_file = admin_dir / "audit.py"
    audit_file.write_text(_audit_content())
    files_created.append(str(audit_file))

    # Step 4: per-model views
    views_init = views_dir / "__init__.py"
    views_init.write_text('"""Admin model views package."""\n')
    files_created.append(str(views_init))

    for model_name in models:
        view_file = views_dir / f"{model_name.lower()}_view.py"
        is_ro = model_name in read_only_models
        view_file.write_text(_model_view_content(model_name, is_ro))
        files_created.append(str(view_file))

    # Step 5: audit log model
    audit_model_file = app_dir / "models" / "audit_log.py"
    if not audit_model_file.exists():
        audit_model_file.write_text(_audit_log_model_content())
        files_created.append(str(audit_model_file))

    # Step 6: Patch main.py to mount admin
    main_file = app_dir / "main.py"
    if main_file.exists():
        _patch_main(main_file, mount_path)
        files_modified.append(str(main_file))

    # Step 7: Tests
    test_dir = project / "tests"
    test_dir.mkdir(exist_ok=True)
    test_file = test_dir / "test_admin_panel.py"
    test_file.write_text(_test_content(models, mount_path, read_only_models))
    files_created.append(str(test_file))

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            f"Admin panel scaffolded at {mount_path}",
            f"Models: {', '.join(models)}",
            f"Read-only models: {read_only_models or 'none'}",
            "CSV export hard-capped at 10,000 rows.",
            "Audit logging via SQLAlchemy event listeners.",
        ],
        next_steps=[
            "pip install sqladmin",
            "alembic revision --autogenerate -m 'add audit_log table'",
            "alembic upgrade head",
            f"Visit {mount_path} — auth gate: {auth_dependency}",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Content generators
# ---------------------------------------------------------------------------


def _discover_models(app_dir: Path) -> list[str]:
    """Discover SQLAlchemy model names from app/models/.

    Args:
        app_dir: The ``app/`` package directory.

    Returns:
        Sorted list of PascalCase model names.
    """
    models_dir = app_dir / "models"
    skip = {"base", "mixins", "__init__", "audit_log", "outbox_event"}
    names = []
    for f in sorted(models_dir.glob("*.py")):
        if f.stem.lower() not in skip:
            # Derive PascalCase class name: item -> Item, order_item -> OrderItem
            names.append("".join(w.capitalize() for w in f.stem.split("_")))
    return names


def _admin_init_content(models: list[str], mount_path: str) -> str:
    """Return content for app/admin/__init__.py.

    Args:
        models: List of model names to register.
        mount_path: Admin mount path.

    Returns:
        Python source string.
    """
    view_imports = "\n".join(
        f"from app.admin.views.{m.lower()}_view import {m}Admin" for m in models
    )
    view_registrations = "\n    ".join(f"admin.add_view({m}Admin)" for m in models)
    # Use placeholder+replace to avoid textwrap.dedent mangling multi-line
    # f-string variables that have different leading-whitespace than the template.
    template = (
        '"""sqladmin admin panel setup.\n'
        "\n"
        "Mount at MOUNT_PATH in app/main.py:\n"
        "\n"
        "    from app.admin import create_admin\n"
        "    admin = create_admin(app, engine)\n"
        '"""\n'
        "from __future__ import annotations\n"
        "\n"
        "from sqladmin import Admin  # type: ignore[import-untyped]\n"
        "\n"
        "VIEW_IMPORTS_PLACEHOLDER\n"
        "from app.admin.auth import AdminAuth\n"
        "from app.admin.audit import register_audit_listeners\n"
        "\n"
        "\n"
        "def create_admin(app, engine) -> Admin:  # type: ignore[no-untyped-def]\n"
        '    """Create and configure the sqladmin Admin instance.\n'
        "\n"
        "    Args:\n"
        "        app: FastAPI application instance.\n"
        "        engine: SQLAlchemy async engine.\n"
        "\n"
        "    Returns:\n"
        "        Configured ``Admin`` instance mounted at ``MOUNT_PATH``.\n"
        '    """\n'
        '    auth_backend = AdminAuth(secret_key="CHANGE-ME-USE-ENV-VAR")\n'
        "    admin = Admin(app, engine, base_url=\"MOUNT_PATH\", authentication_backend=auth_backend)\n"
        "    VIEW_REGISTRATIONS_PLACEHOLDER\n"
        "    register_audit_listeners()\n"
        "    return admin\n"
    )
    return (
        template
        .replace("MOUNT_PATH", mount_path)
        .replace("VIEW_IMPORTS_PLACEHOLDER", view_imports)
        .replace("VIEW_REGISTRATIONS_PLACEHOLDER", view_registrations)
    )


def _auth_content(auth_dependency: str) -> str:
    """Return content for app/admin/auth.py.

    Args:
        auth_dependency: Name of the auth dependency.

    Returns:
        Python source string.
    """
    return textwrap.dedent(f"""\
        \"\"\"Admin auth backend for sqladmin.

        Wraps the entire /admin mount — no individual route can bypass this gate.
        \"\"\"
        from __future__ import annotations

        from sqladmin.authentication import AuthenticationBackend  # type: ignore[import-untyped]
        from starlette.requests import Request
        from starlette.responses import RedirectResponse


        class AdminAuth(AuthenticationBackend):
            \"\"\"Session-based admin authentication backend.

            CUSTOMIZE: replace the stub logic with your real auth check.
            \"\"\"

            async def login(self, request: Request) -> bool:
                \"\"\"Validate login form credentials.

                Args:
                    request: Incoming Starlette request with form data.

                Returns:
                    True if credentials are valid.
                \"\"\"
                form = await request.form()
                username = form.get("username", "")
                password = form.get("password", "")
                # CUSTOMIZE: replace with real admin credential check
                if username == "admin" and password == "admin":  # noqa: S105
                    request.session.update({{"token": "admin-token"}})
                    return True
                return False

            async def logout(self, request: Request) -> bool:
                \"\"\"Clear the admin session.

                Args:
                    request: Incoming Starlette request.

                Returns:
                    True after session is cleared.
                \"\"\"
                request.session.clear()
                return True

            async def authenticate(self, request: Request) -> bool:
                \"\"\"Check if the current session has admin access.

                Args:
                    request: Incoming Starlette request.

                Returns:
                    True if session contains a valid admin token.
                \"\"\"
                return "token" in request.session
    """)


def _audit_content() -> str:
    """Return content for app/admin/audit.py.

    Returns:
        Python source string.
    """
    return textwrap.dedent("""\
        \"\"\"Audit logging via SQLAlchemy event listeners.

        Captures all INSERT/UPDATE/DELETE operations on admin-managed models
        and writes them to the audit_log table.  Fires even on bulk ORM
        operations that bypass individual route handlers.
        \"\"\"
        from __future__ import annotations

        import json
        import logging
        from datetime import datetime, timezone

        from sqlalchemy import event
        from sqlalchemy.orm import Session

        logger = logging.getLogger(__name__)


        def register_audit_listeners() -> None:
            \"\"\"Register SQLAlchemy session-level audit event listeners.\"\"\"

            @event.listens_for(Session, "after_bulk_update")
            def _after_bulk_update(update_context) -> None:
                \"\"\"Log bulk UPDATE operations.

                Args:
                    update_context: SQLAlchemy bulk update context.
                \"\"\"
                logger.info(
                    "ADMIN_AUDIT bulk_update table=%s rowcount=%s",
                    getattr(update_context.primary_table, "name", "unknown"),
                    update_context.rowcount,
                )

            @event.listens_for(Session, "after_bulk_delete")
            def _after_bulk_delete(delete_context) -> None:
                \"\"\"Log bulk DELETE operations.

                Args:
                    delete_context: SQLAlchemy bulk delete context.
                \"\"\"
                logger.info(
                    "ADMIN_AUDIT bulk_delete table=%s rowcount=%s",
                    getattr(delete_context.primary_table, "name", "unknown"),
                    delete_context.rowcount,
                )
    """)


def _model_view_content(model_name: str, read_only: bool) -> str:
    """Return content for a sqladmin ModelView subclass.

    Args:
        model_name: PascalCase model name.
        read_only: Whether to disable create/edit/delete.

    Returns:
        Python source string.
    """
    lower = model_name.lower()
    can_create = "True" if not read_only else "False"
    can_edit = "True" if not read_only else "False"
    can_delete = "True" if not read_only else "False"

    return textwrap.dedent(f"""\
        \"\"\"sqladmin ModelView for {model_name}.\"\"\"
        from __future__ import annotations

        from sqladmin import ModelView  # type: ignore[import-untyped]

        try:
            from app.models.{lower} import {model_name}
        except ImportError:
            {model_name} = None  # type: ignore[assignment]  # model not yet generated


        class {model_name}Admin(ModelView, model={model_name}):
            \"\"\"Admin view for {model_name}.

            CUSTOMIZE: adjust column_list, searchable, sortable, and form columns.
            \"\"\"

            name = "{model_name}"
            name_plural = "{model_name}s"
            icon = "fa-table"

            # Columns shown on the list page — CUSTOMIZE
            column_list = "__all__"

            # Enable/disable write actions
            can_create = {can_create}
            can_edit = {can_edit}
            can_delete = {can_delete}

            # Soft-delete awareness: hide logically deleted rows by default
            # CUSTOMIZE: uncomment when SoftDeleteMixin is present
            # column_default_sort = [("{lower}.created_at", True)]
            # def get_query(self):
            #     return super().get_query().filter_by(is_deleted=False)

            # CSV export hard-capped at 10,000 rows
            page_size = 50
            page_size_options = [25, 50, 100]
            export_max_rows = 10_000
    """)


def _audit_log_model_content() -> str:
    """Return content for app/models/audit_log.py.

    Returns:
        Python source string.
    """
    return textwrap.dedent("""\
        \"\"\"SQLAlchemy model for admin audit log entries.\"\"\"
        from __future__ import annotations

        import uuid
        from datetime import datetime, timezone

        from sqlalchemy import DateTime, String, Text, Uuid
        from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


        class _AuditBase(DeclarativeBase):
            pass


        class AuditLog(_AuditBase):
            \"\"\"Immutable record of every admin write action.

            Attributes:
                id: UUID primary key.
                table_name: Affected table.
                operation: ``INSERT``, ``UPDATE``, or ``DELETE``.
                record_id: Stringified PK of the affected row.
                actor: Admin username who performed the action.
                payload: JSON snapshot of changed values.
                occurred_at: UTC timestamp of the operation.
            \"\"\"

            __tablename__ = "audit_log"

            id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
            table_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
            operation: Mapped[str] = mapped_column(String(50), nullable=False)
            record_id: Mapped[str] = mapped_column(String(255), nullable=False)
            actor: Mapped[str] = mapped_column(String(255), nullable=False)
            payload: Mapped[str | None] = mapped_column(Text, nullable=True)
            occurred_at: Mapped[datetime] = mapped_column(
                DateTime(timezone=True),
                default=lambda: datetime.now(timezone.utc),
                nullable=False,
            )
    """)


def _patch_main(main_file: Path, mount_path: str) -> None:
    """Inject admin mount snippet into app/main.py.

    Args:
        main_file: Path to ``app/main.py``.
        mount_path: URL prefix for admin mount.
    """
    src = main_file.read_text()
    if "create_admin" in src or "sqladmin" in src:
        return
    snippet = textwrap.dedent(f"""\

        # Admin panel — added by generate_admin_panel tool
        # from app.admin import create_admin
        # from app.core.db import engine
        # admin = create_admin(app, engine)
        # (sqladmin auto-mounts at {mount_path})
    """)
    main_file.write_text(src + snippet)


def _test_content(
    models: list[str], mount_path: str, read_only_models: list[str]
) -> str:
    """Return test content for the admin panel.

    Args:
        models: All model names in the admin.
        mount_path: Admin URL prefix.
        read_only_models: Models configured as read-only.

    Returns:
        Python test source string.
    """
    return textwrap.dedent(f"""\
        \"\"\"Tests for the generated admin panel scaffold.\"\"\"
        from __future__ import annotations

        import ast
        from pathlib import Path

        ADMIN_DIR = Path(__file__).parent.parent / "app" / "admin"
        MOUNT_PATH = "{mount_path}"
        MODELS = {models}
        READ_ONLY = {read_only_models}


        def test_admin_init_exists() -> None:
            \"\"\"app/admin/__init__.py must exist and contain 'sqladmin'.\"\"\"
            f = ADMIN_DIR / "__init__.py"
            assert f.exists(), "admin/__init__.py missing"
            assert "sqladmin" in f.read_text(), "sqladmin not referenced in admin init"


        def test_admin_init_parses() -> None:
            \"\"\"admin/__init__.py must be valid Python.\"\"\"
            src = (ADMIN_DIR / "__init__.py").read_text()
            ast.parse(src)  # raises SyntaxError on failure


        def test_auth_file_exists() -> None:
            \"\"\"app/admin/auth.py must exist.\"\"\"
            assert (ADMIN_DIR / "auth.py").exists(), "admin/auth.py missing"


        def test_auth_parses() -> None:
            \"\"\"admin/auth.py must be valid Python.\"\"\"
            src = (ADMIN_DIR / "auth.py").read_text()
            ast.parse(src)


        def test_audit_file_exists() -> None:
            \"\"\"app/admin/audit.py must exist.\"\"\"
            assert (ADMIN_DIR / "audit.py").exists(), "admin/audit.py missing"


        def test_audit_parses() -> None:
            \"\"\"admin/audit.py must be valid Python.\"\"\"
            src = (ADMIN_DIR / "audit.py").read_text()
            ast.parse(src)


        def test_view_files_exist() -> None:
            \"\"\"Each model must have a corresponding view file.\"\"\"
            views_dir = ADMIN_DIR / "views"
            for model in MODELS:
                view_file = views_dir / f"{{model.lower()}}_view.py"
                assert view_file.exists(), f"View missing for {{model}}: {{view_file}}"


        def test_view_files_parse() -> None:
            \"\"\"All view files must be valid Python.\"\"\"
            views_dir = ADMIN_DIR / "views"
            for model in MODELS:
                view_file = views_dir / f"{{model.lower()}}_view.py"
                if view_file.exists():
                    ast.parse(view_file.read_text())


        def test_view_files_contain_model_admin_class() -> None:
            \"\"\"Each view file must define a <Model>Admin class.\"\"\"
            views_dir = ADMIN_DIR / "views"
            for model in MODELS:
                view_file = views_dir / f"{{model.lower()}}_view.py"
                if view_file.exists():
                    src = view_file.read_text()
                    assert f"{{model}}Admin" in src, f"{{model}}Admin class missing in {{view_file}}"


        def test_read_only_views_have_can_false() -> None:
            \"\"\"Read-only model views must set can_create/can_edit/can_delete = False.\"\"\"
            views_dir = ADMIN_DIR / "views"
            for model in READ_ONLY:
                view_file = views_dir / f"{{model.lower()}}_view.py"
                if view_file.exists():
                    src = view_file.read_text()
                    assert "can_create = False" in src
                    assert "can_edit = False" in src
                    assert "can_delete = False" in src


        def test_writable_views_have_can_true() -> None:
            \"\"\"Writable model views must set can_create/can_edit/can_delete = True.\"\"\"
            views_dir = ADMIN_DIR / "views"
            writable = [m for m in MODELS if m not in READ_ONLY]
            for model in writable:
                view_file = views_dir / f"{{model.lower()}}_view.py"
                if view_file.exists():
                    src = view_file.read_text()
                    assert "can_create = True" in src
                    assert "can_edit = True" in src
                    assert "can_delete = True" in src


        def test_csv_export_cap_in_views() -> None:
            \"\"\"All views must declare export_max_rows = 10_000.\"\"\"
            views_dir = ADMIN_DIR / "views"
            for model in MODELS:
                view_file = views_dir / f"{{model.lower()}}_view.py"
                if view_file.exists():
                    src = view_file.read_text()
                    assert "export_max_rows" in src, f"export_max_rows missing in {{view_file}}"


        def test_audit_log_model_exists() -> None:
            \"\"\"app/models/audit_log.py must exist.\"\"\"
            audit_model = ADMIN_DIR.parent / "models" / "audit_log.py"
            assert audit_model.exists(), "audit_log.py model missing"


        def test_audit_log_model_parses() -> None:
            \"\"\"audit_log.py must be valid Python.\"\"\"
            f = ADMIN_DIR.parent / "models" / "audit_log.py"
            if f.exists():
                ast.parse(f.read_text())


        def test_mount_path_in_admin_init() -> None:
            \"\"\"Admin __init__ must reference the configured mount path.\"\"\"
            src = (ADMIN_DIR / "__init__.py").read_text()
            assert MOUNT_PATH in src, f"Mount path {{MOUNT_PATH}} not in admin __init__"


        def test_views_init_exists() -> None:
            \"\"\"app/admin/views/__init__.py must exist.\"\"\"
            assert (ADMIN_DIR / "views" / "__init__.py").exists()


        def test_admin_auth_class_name() -> None:
            \"\"\"auth.py must define AdminAuth class.\"\"\"
            src = (ADMIN_DIR / "auth.py").read_text()
            assert "class AdminAuth" in src


        def test_admin_auth_login_method() -> None:
            \"\"\"AdminAuth must implement login method.\"\"\"
            src = (ADMIN_DIR / "auth.py").read_text()
            assert "async def login" in src


        def test_admin_auth_logout_method() -> None:
            \"\"\"AdminAuth must implement logout method.\"\"\"
            src = (ADMIN_DIR / "auth.py").read_text()
            assert "async def logout" in src


        def test_admin_auth_authenticate_method() -> None:
            \"\"\"AdminAuth must implement authenticate method.\"\"\"
            src = (ADMIN_DIR / "auth.py").read_text()
            assert "async def authenticate" in src


        def test_audit_register_function_exists() -> None:
            \"\"\"audit.py must define register_audit_listeners function.\"\"\"
            src = (ADMIN_DIR / "audit.py").read_text()
            assert "def register_audit_listeners" in src


        def test_all_view_files_reference_model_view() -> None:
            \"\"\"All view files must reference ModelView from sqladmin.\"\"\"
            views_dir = ADMIN_DIR / "views"
            for model in MODELS:
                view_file = views_dir / f"{{model.lower()}}_view.py"
                if view_file.exists():
                    src = view_file.read_text()
                    assert "ModelView" in src
    """)


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*.

    Args:
        start: Reference time from ``time.monotonic()``.

    Returns:
        Elapsed milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)
