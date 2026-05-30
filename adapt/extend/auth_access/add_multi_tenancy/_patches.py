"""Source-patch helpers for add_multi_tenancy.

Each ``patch_*`` function applies a textual / AST surgical edit to an existing
emitted project file (User model, auth deps, signup route, conftest, business
model, CRUD, main, routes init). Idempotent: every helper short-circuits when
its fingerprint is already present.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from adapt._base import load_template, render


def patch_models_init(models_init: Path, class_imports: list[tuple[str, str]]) -> None:
    if not models_init.exists():
        return
    content = models_init.read_text()
    new_lines: list[str] = []
    for module, cls in class_imports:
        marker = f"from app.models.{module} import {cls}"
        if marker in content:
            continue
        new_lines.append(f"{marker}  # noqa: F401")
    if not new_lines:
        return
    if not content.endswith("\n"):
        content += "\n"
    content += "\n".join(new_lines) + "\n"
    models_init.write_text(content)


def discover_models(app_dir: Path) -> list[str]:
    models_dir = app_dir / "models"
    routes_dir = app_dir / "api" / "routes"
    skip = {"base", "user", "mixins", "tenant", "__init__"}
    available_routes: set[str] = set()
    if routes_dir.exists():
        for r in routes_dir.glob("*.py"):
            if r.stem != "__init__":
                available_routes.add(r.stem)
    names = []
    for f in sorted(models_dir.glob("*.py")):
        stem = f.stem
        if stem in skip or stem not in available_routes:
            continue
        try:
            tree = ast.parse(f.read_text())
        except SyntaxError:
            continue
        base_subclasses = [
            n.name
            for n in ast.walk(tree)
            if isinstance(n, ast.ClassDef)
            and any(
                (isinstance(b, ast.Name) and b.id == "Base")
                or (isinstance(b, ast.Attribute) and b.attr == "Base")
                for b in n.bases
            )
        ]
        base_subclasses = [c for c in base_subclasses if c.lower() == stem]
        names.extend(base_subclasses)
    return sorted(names)


def write_mixin(here: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    new_imports = [
        "from __future__ import annotations",
        "import uuid",
        "from sqlalchemy import ForeignKey, Uuid",
        "from sqlalchemy.orm import Mapped, declared_attr, mapped_column",
    ]
    mixin_body = load_template(here, "mixin_body.py.tmpl").template
    if dest.exists():
        existing = dest.read_text()
        lines_to_add = [imp for imp in new_imports if imp not in existing]
        if lines_to_add:
            existing = existing.rstrip("\n") + "\n" + "\n".join(lines_to_add) + "\n"
        dest.write_text(existing + mixin_body)
    else:
        header = load_template(here, "mixins_header.py.tmpl").template
        dest.write_text(header + mixin_body)


def patch_user_model(user_file: Path) -> None:
    src = user_file.read_text()
    if "tenant_id" in src:
        return
    if "ForeignKey" not in src:
        m = re.search(r"(from sqlalchemy import\s*\()", src)
        if m:
            src = src[: m.end()] + "\n    ForeignKey," + src[m.end() :]
        elif "from sqlalchemy import" in src:
            src = src.replace("from sqlalchemy import", "from sqlalchemy import ForeignKey,", 1)
    pk_marker = "id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)"
    tenant_col = (
        "\n    # Identity-bound tenancy: NULL == global/system/unassigned (bootstrap)."
        "\n    tenant_id: Mapped[uuid.UUID | None] = mapped_column("
        '\n        Uuid, ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=True, index=True'
        "\n    )"
    )
    if pk_marker in src:
        src = src.replace(pk_marker, pk_marker + tenant_col, 1)
        _verify_attr_in_class(src, "User", "tenant_id")
        user_file.write_text(src)
        return
    m = re.search(r"class User\([^)]*\):\n", src)
    if not m:
        return
    insert_at = m.end()
    src = src[:insert_at] + "    " + tenant_col.lstrip() + "\n" + src[insert_at:]
    _verify_attr_in_class(src, "User", "tenant_id")
    user_file.write_text(src)


def _verify_attr_in_class(src: str, class_name: str, attr: str) -> None:
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                target = None
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    target = item.target.id
                elif isinstance(item, ast.Assign):
                    for t in item.targets:
                        if isinstance(t, ast.Name):
                            target = t.id
                if target == attr:
                    return
    raise RuntimeError(f"{attr} not found inside class {class_name} after patching — tool bug.")


def patch_auth_deps(here: Path, deps_file: Path) -> None:
    src = deps_file.read_text()
    if "resolve_tenant" in src:
        return
    if "from fastapi import" in src and "Request" not in src.split("\n\n", 1)[0]:
        src = re.sub(
            r"from fastapi import ([^\n]+)",
            lambda m: (
                f"from fastapi import {m.group(1)}"
                if "Request" in m.group(1)
                else f"from fastapi import Request, {m.group(1)}"
            ),
            src,
            count=1,
        )
    src = src.replace(
        "async def get_current_user(\n    session: SessionDep,",
        "async def get_current_user(\n    request: Request,\n    session: SessionDep,",
        1,
    )
    src = src.replace(
        "    if user is None or not user.is_active:\n        raise _CREDENTIALS_ERROR\n\n    return user",
        "    if user is None or not user.is_active:\n        raise _CREDENTIALS_ERROR\n\n"
        "    # Identity-bound tenancy: set the request tenant context from the\n"
        "    # AUTHENTICATED user (and validate any X-Tenant-ID against membership).\n"
        "    await resolve_tenant(session, user, request)\n\n    return user",
        1,
    )
    helper = load_template(here, "resolve_tenant_helper.py.tmpl").template
    deps_file.write_text(src.rstrip("\n") + "\n" + helper)


def patch_signup_tenant(users_file: Path) -> bool:
    src = users_file.read_text()
    if "_mt_signup_tenant" in src:
        return False
    sig = (
        "async def signup(\n"
        "    request: Request,\n"
        "    session: SessionDep,\n"
        "    body: UserCreate,\n"
        ") -> UserPublic:"
    )
    if sig not in src:
        return False
    if "from app.models.tenant import Tenant as _MTTenant" not in src:
        marker = "from app.schemas.message import Message\n"
        helper_imports = (
            "from sqlalchemy import select as _mt_select\n"
            "from app.models.tenant import Tenant as _MTTenant\n"
        )
        if marker in src:
            src = src.replace(marker, marker + helper_imports, 1)
        else:
            src = helper_imports + src
    anchor = '    obj_in = body.model_dump()\n    obj_in["hashed_password"] = get_password_hash(obj_in.pop("password"))'
    inject = (
        "    obj_in = body.model_dump()\n"
        '    obj_in["hashed_password"] = get_password_hash(obj_in.pop("password"))\n'
        "    # _mt_signup_tenant: bind the new user to the tenant named in X-Tenant-ID.\n"
        '    _mt_slug = request.headers.get("X-Tenant-ID")\n'
        "    if _mt_slug:\n"
        "        _mt_stmt = (\n"
        "            _mt_select(_MTTenant)\n"
        "            .where(_MTTenant.slug == _mt_slug)\n"
        "            .execution_options(skip_tenant_filter=True)\n"
        "        )\n"
        "        _mt_tenant = (await session.execute(_mt_stmt)).scalar_one_or_none()\n"
        '        if _mt_tenant is not None and _mt_tenant.status == "active":\n'
        '            obj_in["tenant_id"] = _mt_tenant.id'
    )
    if anchor not in src:
        return False
    src = src.replace(anchor, inject, 1)
    users_file.write_text(src)
    return True


class ConftestPatchAnchorMismatchError(RuntimeError):
    """Raised when patch_test_conftest cannot locate one of its anchor strings.

    The conftest patcher relies on exact-string ``str.replace`` calls
    against the base scaffold's emitted conftest. If upstream changes a
    single byte in the anchor, ``replace`` silently returns the original
    string and the patch becomes a no-op — the tool would then report
    success while the conftest stays unpatched (so multi-tenant tests
    would fail with cryptic ``tenant_id`` AttributeErrors at runtime).

    This exception names the specific anchor that failed so a maintainer
    can diff the scaffold against the patcher and fix one or the other.
    """


def _replace_or_raise(src: str, anchor: str, replacement: str, anchor_name: str) -> str:
    """Run ``src.replace(anchor, replacement, 1)`` and raise on no-op.

    Args:
        src: Current source text.
        anchor: Exact-match anchor to look for.
        replacement: Replacement text.
        anchor_name: Human-readable name of the anchor (used in the
            exception message when the replace is a silent no-op).

    Returns:
        Modified source text.

    Raises:
        ConftestPatchAnchorMismatchError: When ``anchor`` is not present in
            ``src`` (the replace would be a no-op).
    """
    new = src.replace(anchor, replacement, 1)
    if new == src:
        raise ConftestPatchAnchorMismatchError(
            f"patch_test_conftest: anchor '{anchor_name}' not found in conftest — "
            f"upstream scaffold likely drifted. Re-align the anchor in "
            f"add_multi_tenancy/_patches.py::patch_test_conftest against the "
            f"current conftest emitted by generators.orchestrator."
        )
    return new


def patch_test_conftest(conftest_file: Path) -> bool:
    src = conftest_file.read_text()
    if "_MT_TENANT_SLUG" in src:
        return False
    # F-E: each str.replace below MUST actually change the source.
    # A silent no-op (anchor drifted upstream) would leave the conftest
    # half-patched and tests would explode with confusing errors. Raise
    # immediately with the specific anchor name so the failure is
    # actionable instead of mysterious.
    if "from app.models.user import User" in src:
        src = _replace_or_raise(
            src,
            "from app.models.user import User",
            "from app.models.user import User\n"
            "from app.models.tenant import Tenant\n"
            '\n_MT_TENANT_SLUG = "test-tenant"',
            "user_import",
        )
    else:
        src = _replace_or_raise(
            src,
            "from app.main import app",
            "from app.main import app\n"
            "from app.models.tenant import Tenant\n"
            '\n_MT_TENANT_SLUG = "test-tenant"',
            "main_import",
        )
    create_all_anchor = (
        "    async with engine_test.begin() as conn:\n"
        "        await conn.run_sync(Base.metadata.create_all)\n\n"
        "    async with async_session_test() as sess:\n"
        "        yield sess"
    )
    create_all_replacement = (
        "    async with engine_test.begin() as conn:\n"
        "        await conn.run_sync(Base.metadata.create_all)\n\n"
        "    async with async_session_test() as sess:\n"
        "        # multi-tenancy: seed a tenant every test user belongs to.\n"
        "        import uuid as _mt_uuid\n"
        "        _mt_tenant = Tenant(\n"
        "            id=_mt_uuid.uuid4(), slug=_MT_TENANT_SLUG,\n"
        '            name="Test Tenant", status="active",\n'
        "        )\n"
        "        sess.add(_mt_tenant)\n"
        "        await sess.commit()\n"
        '        sess.info["mt_tenant_id"] = _mt_tenant.id\n'
        "        yield sess"
    )
    # This anchor is OPTIONAL — older conftests may not emit the
    # session fixture in this exact form. Use the silent variant.
    if create_all_anchor in src:
        src = src.replace(create_all_anchor, create_all_replacement, 1)
    src = _replace_or_raise(
        src,
        "        is_active=True,\n        is_superuser=True,\n    )",
        "        is_active=True,\n        is_superuser=True,\n"
        '        tenant_id=session.info.get("mt_tenant_id"),\n    )',
        "superuser_fixture",
    )
    src = _replace_or_raise(
        src,
        "        is_active=True,\n        is_superuser=False,\n    )",
        "        is_active=True,\n        is_superuser=False,\n"
        '        tenant_id=session.info.get("mt_tenant_id"),\n    )',
        "regularuser_fixture",
    )
    src = _replace_or_raise(
        src,
        "    transport = ASGITransport(app=app)\n"
        '    async with AsyncClient(transport=transport, base_url="http://test") as ac:',
        "    transport = ASGITransport(app=app)\n"
        "    async with AsyncClient(\n"
        '        transport=transport, base_url="http://test",\n'
        '        headers={"X-Tenant-ID": _MT_TENANT_SLUG},\n'
        "    ) as ac:",
        "asgi_transport",
    )
    conftest_file.write_text(src)
    return True


def patch_model(model_file: Path, model_name: str) -> None:
    src = model_file.read_text()
    if "TenantScopedMixin" in src:
        return
    table_name = model_name.lower() + "s"
    if "from app.models.mixins import TenantScopedMixin" not in src:
        src = src.replace(
            "from app.models.base import Base",
            "from app.models.base import Base\nfrom app.models.mixins import TenantScopedMixin",
        )
    if "Index" not in src:
        m = re.search(r"(from sqlalchemy import\s*\()", src)
        if m:
            src = src[: m.end()] + "\n    Index," + src[m.end() :]
        elif "from sqlalchemy import" in src:
            src = src.replace("from sqlalchemy import", "from sqlalchemy import Index,", 1)
    src = src.replace(
        "class " + model_name + "(Base):",
        "class " + model_name + "(TenantScopedMixin, Base):",
    )
    index_block = (
        "\n"
        "    __table_args__ = (\n"
        f'        Index("ix_{table_name}_tenant_created", "tenant_id", "created_at"),\n'
        "    )\n"
    )
    candidate = src.rstrip("\n") + "\n" + index_block
    _verify_table_args_in_class(candidate, model_name)
    model_file.write_text(candidate)


def _verify_table_args_in_class(src: str, model_name: str) -> None:
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "__table_args__":
                    raise RuntimeError(
                        f"__table_args__ was emitted at MODULE scope in {model_name} model "
                        f"— index would never be registered.  This is a tool bug."
                    )
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == model_name:
            for item in node.body:
                if isinstance(item, ast.Assign):
                    for t in item.targets:
                        if isinstance(t, ast.Name) and t.id == "__table_args__":
                            return
    raise RuntimeError(
        f"__table_args__ not found inside class {model_name} after patching — "
        f"the composite tenant index was not registered."
    )


def patch_crud(here: Path, crud_file: Path, model_name: str) -> None:
    src = crud_file.read_text()
    if "require_current_tenant" in src:
        return
    header = render(
        here,
        "crud_helper.py.tmpl",
        {"lower": model_name.lower(), "model": model_name},
    )
    crud_file.write_text(src + header)


def patch_main(main_file: Path) -> None:
    src = main_file.read_text()
    if "TenantMiddleware" in src and "tenant_filter" in src:
        return
    if "tenant_filter" not in src:
        marker = "from app.core.logging import configure_logging"
        filter_import = "\nimport app.core.tenant_filter  # noqa: F401  — activates global filter"
        if marker in src:
            src = src.replace(marker, marker + filter_import)
        else:
            src = "import app.core.tenant_filter  # noqa: F401\n" + src
    if "TenantMiddleware" not in src:
        middleware_import = "\nfrom app.api.middleware.tenant import TenantMiddleware"
        register_marker = "register_middleware(app, settings)"
        if register_marker in src:
            src = src.replace(
                register_marker,
                middleware_import.lstrip("\n")
                + "\n"
                + register_marker
                + '\napp.add_middleware(TenantMiddleware, resolver="header")',
            )
        else:
            src = src + "\nfrom app.api.middleware.tenant import TenantMiddleware\n"
            src = src + '\napp.add_middleware(TenantMiddleware, resolver="header")\n'
    main_file.write_text(src)


def patch_routes_init(routes_init: Path) -> None:
    src = routes_init.read_text()
    if "tenant_router" in src:
        return
    addition = (
        "\n"
        "# --- Tenant admin routes — added by add_multi_tenancy tool ---\n"
        "from app.api.routes.tenant import router as tenant_router  # noqa: E402\n"
        "api_router.include_router(tenant_router)\n"
    )
    routes_init.write_text(src.rstrip("\n") + "\n" + addition)


def write_migration(here: Path, versions_dir: Path, model_names: list[str], down_rev: str) -> Path:
    tables = [m.lower() + "s" for m in model_names]
    rev_id = "0008_add_multi_tenancy"
    backfill_lines = [
        "    op.execute(\n"
        f'        "UPDATE {table} SET tenant_id = '
        "(SELECT id FROM tenants WHERE slug='default') "
        'WHERE tenant_id IS NULL;"\n'
        "    )"
        for table in tables
    ]
    backfill_block = "\n\n".join(backfill_lines)
    alter_lines = [
        f'    op.alter_column("{table}", "tenant_id", nullable=False)\n'
        "    op.create_foreign_key(\n"
        f'        "fk_{table}_tenant", "{table}", "tenants",\n'
        '        ["tenant_id"], ["id"], ondelete="RESTRICT"\n'
        "    )\n"
        f'    op.create_index("ix_{table}_tenant_created", "{table}",'
        ' ["tenant_id", "created_at"])'
        for table in tables
    ]
    alter_block = "\n\n".join(alter_lines)
    add_col_lines = [
        "    op.add_column(\n"
        f'        "{table}",\n'
        '        sa.Column("tenant_id", sa.Uuid(), nullable=True),\n'
        "    )"
        for table in tables
    ]
    add_col_block = "\n\n".join(add_col_lines)
    drop_lines = [
        f'    op.drop_index("ix_{table}_tenant_created", table_name="{table}")\n'
        f'    op.drop_constraint("fk_{table}_tenant", "{table}", type_="foreignkey")\n'
        f'    op.drop_column("{table}", "tenant_id")'
        for table in reversed(tables)
    ]
    drop_block = "\n\n".join(drop_lines)

    content = render(
        here,
        "migration.py.tmpl",
        {
            "rev_id": rev_id,
            "down_rev": down_rev,
            "add_col_block": add_col_block,
            "backfill_block": backfill_block,
            "alter_block": alter_block,
            "drop_block": drop_block,
        },
    )
    migration_file = versions_dir / f"{rev_id}.py"
    migration_file.write_text(content)
    return migration_file
