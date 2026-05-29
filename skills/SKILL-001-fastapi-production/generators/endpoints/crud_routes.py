"""Generator for CRUD API routes."""

from __future__ import annotations

MCP_TOOL = {
    "name": "fastapi_api_generate_crud_routes",
    "description": "Generate complete CRUD routes for a model with auth and owner-based access control.",
    "tags": ["endpoints", "generator"],
    "entry": "generate_crud_routes",
}

import textwrap
from pathlib import Path

from generators._pluralize import pluralize as _pluralize


def generate_crud_routes(
    output_dir: str,
    model_name: str,
    fields: dict[str, str],
    auth: str = "required",
    owner_field: str | None = None,
    prefix: str | None = None,
    shared_model: bool = False,
) -> dict:
    """Generate ``api/routes/{model_name_lower}.py`` with a complete CRUD router.

    The generated file follows the tiangolo/full-stack-fastapi golden
    standard:

    * ``GET  /{plural}/``     -- list with pagination (skip/limit)
    * ``GET  /{plural}/{id}`` -- get by ID
    * ``POST /{plural}/``     -- create
    * ``PUT  /{plural}/{id}`` -- partial update (exclude_unset)
    * ``DELETE /{plural}/{id}`` -- delete

    Security policy (BOLA — OWASP API1:2023):

    * When *owner_field* is set AND *shared_model* is False (the default
      and secure-by-default mode), GET-by-id / PATCH / DELETE enforce
      per-object ownership: regular users may only access records whose
      ``owner_id`` matches ``current_user.id``; superusers have
      unrestricted access.  Mismatch raises HTTP 403.
    * When *owner_field* is set AND *shared_model* is True (explicit
      opt-out), the per-object guard is omitted: any authenticated user
      may read / update / delete any row.  The route docstrings call out
      this open-access policy so reviewers can audit it.  This mode is
      intended for catalogue / lookup tables that happen to track who
      created a row (``owner_id``) but are not user-private.

    Args:
        output_dir: Project root directory.  The file is written to
            ``{output_dir}/api/routes/{lower}.py``.
        model_name: PascalCase model name (e.g. ``Product``).
        fields: ``{field_name: type_hint}`` mapping — only used to
            build the ``Create`` payload assembly (owner_id injection).
        auth: Authentication level.  One of ``"required"`` (all routes
            need ``CurrentUser``), ``"superuser"`` (all need
            ``CurrentSuperuser``), ``"public_read"`` (GET is public,
            writes need auth), or ``"none"`` (no auth).
        owner_field: If set (e.g. ``"user"``), the model has an
            ``owner_id`` column.  By default this triggers the per-object
            ownership guard on read/update/delete-by-id.  Pass
            ``shared_model=True`` to opt-out of the guard while keeping
            the ``owner_id`` column populated server-side.
        prefix: Custom URL prefix.  Defaults to ``/{plural_lower}``.
        shared_model: Opt-out of the per-object ownership guard for
            owner-bearing models.  When True (and ``owner_field`` is
            set), the emitted routes do NOT check ``obj.owner_id ==
            current_user.id`` — any authenticated user may access any
            row.  The list endpoint also returns all rows (not just the
            caller's).  Default False = secure-by-default.

    Returns:
        Dict with ``files_created`` and ``notes``.
    """
    out = Path(output_dir) / "api" / "routes"
    out.mkdir(parents=True, exist_ok=True)

    lower = model_name.lower()
    cls = model_name if model_name[0].isupper() else model_name.capitalize()
    plural = _pluralize(lower)
    plural_class = _pluralize(cls)
    url_prefix = prefix if prefix else f"/{plural}"

    # ------------------------------------------------------------------
    # Resolve auth strategy
    # ------------------------------------------------------------------
    has_auth = auth != "none"
    has_owner = owner_field is not None and has_auth
    write_auth = auth != "none"
    superuser_only = auth == "superuser"
    # Secure-by-default: the per-object guard fires whenever the model
    # has an owner_id column AND the caller has not opted out via
    # shared_model=True.  Owner_id is still injected on create even in
    # shared-model mode (it is a useful audit trail) — only the per-row
    # access check is suppressed.
    enforce_owner_guard = has_owner and not shared_model

    # ------------------------------------------------------------------
    # Build imports
    # ------------------------------------------------------------------
    import_lines: list[str] = [
        f'"""CRUD routes for {cls}."""',
        "",
        "from __future__ import annotations",
        "",
        "import uuid",
        "",
        "from fastapi import APIRouter, HTTPException, Query, status",
        "",
        f"from app.crud.{lower} import (",
        "    create as crud_create,",
        "    delete as crud_delete,",
        "    get as crud_get,",
        "    get_multi as crud_get_multi,",
        "    update as crud_update,",
        ")",
        f"from app.schemas.{lower} import (",
        f"    {cls}Create,",
        f"    {cls}Public,",
        f"    {cls}Update,",
        f"    {plural_class}Public,",
        ")",
        "from app.core.session import SessionDep",
    ]

    if has_auth:
        deps_imports: list[str] = []
        if not superuser_only:
            deps_imports.append("CurrentUser")
        if superuser_only:
            deps_imports.append("CurrentSuperuser")
        import_lines.append(f"from app.api.deps import {', '.join(deps_imports)}")

    if (
        write_auth
        and not superuser_only
        and not has_owner
        and auth == "public_read"
        and "CurrentUser" not in "".join(import_lines)
    ):
        # Need CurrentUser for writes even when reads are public
        import_lines.append("from app.api.deps import CurrentUser")

    # Message schema for delete responses
    import_lines.append("from app.schemas.message import Message")

    # ------------------------------------------------------------------
    # Determine user param name for each endpoint type
    # ------------------------------------------------------------------
    if superuser_only:
        read_user_param = "current_user: CurrentSuperuser"
        write_user_param = "current_user: CurrentSuperuser"
    elif has_auth:
        read_user_param = "current_user: CurrentUser"
        write_user_param = "current_user: CurrentUser"
    else:
        read_user_param = ""
        write_user_param = ""

    # For public_read, GET endpoints have no user param
    if auth == "public_read":
        read_user_param = ""

    # ------------------------------------------------------------------
    # Router declaration
    # ------------------------------------------------------------------
    router_line = f'router = APIRouter(prefix="{url_prefix}", tags=["{plural}"])'

    # ------------------------------------------------------------------
    # GET /{plural}/ — List with pagination
    # ------------------------------------------------------------------
    list_params = ["session: SessionDep"]
    if read_user_param:
        list_params.append(read_user_param)
    list_params.append("skip: int = Query(default=0, ge=0)")
    list_params.append("limit: int = Query(default=100, ge=1, le=1000)")
    list_sig = ",\n    ".join(list_params)

    # Build get_multi kwargs
    if enforce_owner_guard and not superuser_only:
        list_body_lines = [
            "    # Superusers see all records; regular users see only their own.",
            "    owner_filter = (",
            "        None if current_user.is_superuser else current_user.id",
            "    )",
            "    result = await crud_get_multi(",
            "        session, skip=skip, limit=limit, owner_id=owner_filter,",
            "    )",
        ]
    elif has_owner and shared_model:
        # Shared model: every authenticated user sees every row (open-access
        # catalogue / lookup table).  owner_id is still tracked on create
        # but is not used for filtering.
        list_body_lines = [
            "    # Shared model (open access): all authenticated users see all rows.",
            "    result = await crud_get_multi(session, skip=skip, limit=limit)",
        ]
    else:
        list_body_lines = [
            "    result = await crud_get_multi(session, skip=skip, limit=limit)",
        ]

    list_body_lines.append(f"    return {plural_class}Public(**result)")

    list_route = _build_route(
        method="get",
        path="/",
        func_name=f"list_{plural}",
        doc=(
            f"Return a paginated list of {plural}.\n\n"
            "    Args:\n"
            "        skip: Number of records to skip (offset).\n"
            "        limit: Maximum number of records to return (1-1000)."
        ),
        params=list_sig,
        return_type=f"{plural_class}Public",
        body_lines=list_body_lines,
    )

    # ------------------------------------------------------------------
    # GET /{plural}/{id} — Get by ID
    # ------------------------------------------------------------------
    get_params = ["session: SessionDep", "id: uuid.UUID"]
    if read_user_param:
        get_params.append(read_user_param)
    get_sig = ",\n    ".join(get_params)

    get_body_lines = [
        "    obj = await crud_get(session, id)",
        "    if obj is None:",
        "        raise HTTPException(",
        "            status_code=status.HTTP_404_NOT_FOUND,",
        f'            detail="{cls} not found",',
        "        )",
    ]
    if enforce_owner_guard and not superuser_only:
        get_body_lines.extend(
            [
                "    if not current_user.is_superuser and obj.owner_id != current_user.id:",
                "        raise HTTPException(",
                "            status_code=status.HTTP_403_FORBIDDEN,",
                '            detail="Not enough permissions",',
                "        )",
            ]
        )
    get_body_lines.append("    return obj")

    # BOLA secure-by-default: docstring must truthfully describe the actual
    # access policy.  Three cases:
    #   1. Owner-bearing + NOT shared → per-object ownership enforced (default).
    #   2. Owner-bearing + shared_model=True → open access (explicit opt-out).
    #   3. Authenticated but ownerless → any active user may read any row.
    if enforce_owner_guard:
        get_doc = (
            f"Fetch a single {cls} by its UUID.\n\n"
            "    Access policy: regular users may only fetch records they own;\n"
            "    superusers have unrestricted access.\n\n"
            "    Raises:\n"
            f"        HTTPException 404: {cls} not found.\n"
            "        HTTPException 403: Not authorized — caller does not own this record."
        )
    elif has_owner and shared_model:
        get_doc = (
            f"Fetch a single {cls} by its UUID.\n\n"
            f"    Access policy: shared model — any authenticated user may read\n"
            f"    any {cls} row.  The model tracks ``owner_id`` (populated\n"
            "    server-side on create) but no per-object access check is\n"
            "    performed.  This is an EXPLICIT opt-out from the secure-by-\n"
            "    default ownership guard via ``shared_models=...``.\n\n"
            "    Raises:\n"
            f"        HTTPException 404: {cls} not found."
        )
    elif has_auth:
        get_doc = (
            f"Fetch a single {cls} by its UUID.\n\n"
            "    Access policy: authentication required; any active user may read\n"
            "    any record (no per-object ownership check is enforced).\n\n"
            "    Raises:\n"
            f"        HTTPException 404: {cls} not found."
        )
    else:
        get_doc = (
            f"Fetch a single {cls} by its UUID.\n\n"
            "    Access policy: public — no authentication required.\n\n"
            "    Raises:\n"
            f"        HTTPException 404: {cls} not found."
        )

    get_route = _build_route(
        method="get",
        path="/{id}",
        func_name=f"read_{lower}",
        doc=get_doc,
        params=get_sig,
        return_type=f"{cls}Public",
        body_lines=get_body_lines,
    )

    # ------------------------------------------------------------------
    # POST /{plural}/ — Create
    # ------------------------------------------------------------------
    create_params = ["session: SessionDep", f"body: {cls}Create"]
    if write_user_param:
        create_params.append(write_user_param)
    create_sig = ",\n    ".join(create_params)

    create_body_lines = [
        "    obj_in = body.model_dump()",
    ]
    if has_owner:
        create_body_lines.append('    obj_in["owner_id"] = current_user.id')
    create_body_lines.extend(
        [
            "    obj = await crud_create(session, obj_in=obj_in)",
            "    return obj",
        ]
    )

    create_route = _build_route(
        method="post",
        path="/",
        func_name=f"create_{lower}",
        doc=f"Create a new {cls} record.",
        params=create_sig,
        return_type=f"{cls}Public",
        body_lines=create_body_lines,
        status_code=201,
    )

    # ------------------------------------------------------------------
    # PATCH /{plural}/{id} — Partial update (exclude_unset semantics)
    # ------------------------------------------------------------------
    update_params = ["session: SessionDep", "id: uuid.UUID", f"body: {cls}Update"]
    if write_user_param:
        update_params.append(write_user_param)
    update_sig = ",\n    ".join(update_params)

    update_body_lines = [
        "    obj = await crud_get(session, id)",
        "    if obj is None:",
        "        raise HTTPException(",
        "            status_code=status.HTTP_404_NOT_FOUND,",
        f'            detail="{cls} not found",',
        "        )",
    ]
    if enforce_owner_guard and not superuser_only:
        update_body_lines.extend(
            [
                "    if not current_user.is_superuser and obj.owner_id != current_user.id:",
                "        raise HTTPException(",
                "            status_code=status.HTTP_403_FORBIDDEN,",
                '            detail="Not enough permissions",',
                "        )",
            ]
        )
    update_body_lines.extend(
        [
            "    update_data = body.model_dump(exclude_unset=True)",
            "    obj = await crud_update(session, db_obj=obj, obj_in=update_data)",
            "    return obj",
        ]
    )

    if enforce_owner_guard:
        update_doc = (
            f"Partially update an existing {cls}.\n\n"
            "    Only fields present in the request body are modified\n"
            "    (``exclude_unset`` semantics).\n\n"
            "    Access policy: regular users may only update records they own;\n"
            "    superusers have unrestricted access.\n\n"
            "    Raises:\n"
            f"        HTTPException 404: {cls} not found.\n"
            "        HTTPException 403: Not authorized — caller does not own this record."
        )
    elif has_owner and shared_model:
        update_doc = (
            f"Partially update an existing {cls}.\n\n"
            "    Only fields present in the request body are modified\n"
            "    (``exclude_unset`` semantics).\n\n"
            f"    Access policy: shared model — any authenticated user may update\n"
            f"    any {cls} row.  EXPLICIT opt-out from the secure-by-default\n"
            "    ownership guard via ``shared_models=...``.\n\n"
            "    Raises:\n"
            f"        HTTPException 404: {cls} not found."
        )
    else:
        update_doc = (
            f"Partially update an existing {cls}.\n\n"
            "    Only fields present in the request body are modified\n"
            "    (``exclude_unset`` semantics)."
        )

    update_route = _build_route(
        method="patch",
        path="/{id}",
        func_name=f"update_{lower}",
        doc=update_doc,
        params=update_sig,
        return_type=f"{cls}Public",
        body_lines=update_body_lines,
    )

    # ------------------------------------------------------------------
    # DELETE /{plural}/{id} — Delete
    # ------------------------------------------------------------------
    delete_params = ["session: SessionDep", "id: uuid.UUID"]
    if write_user_param:
        delete_params.append(write_user_param)
    delete_sig = ",\n    ".join(delete_params)

    delete_body_lines = [
        "    obj = await crud_get(session, id)",
        "    if obj is None:",
        "        raise HTTPException(",
        "            status_code=status.HTTP_404_NOT_FOUND,",
        f'            detail="{cls} not found",',
        "        )",
    ]
    if enforce_owner_guard and not superuser_only:
        delete_body_lines.extend(
            [
                "    if not current_user.is_superuser and obj.owner_id != current_user.id:",
                "        raise HTTPException(",
                "            status_code=status.HTTP_403_FORBIDDEN,",
                '            detail="Not enough permissions",',
                "        )",
            ]
        )
    delete_body_lines.extend(
        [
            "    await crud_delete(session, id)",
            f'    return Message(message="{cls} deleted")',
        ]
    )

    # BOLA secure-by-default: docstring must truthfully describe the access policy.
    if enforce_owner_guard:
        delete_doc = (
            f"Delete a {cls} by its UUID.\n\n"
            "    Access policy: regular users may only delete records they own;\n"
            "    superusers have unrestricted access.\n\n"
            "    Raises:\n"
            f"        HTTPException 404: {cls} not found.\n"
            "        HTTPException 403: Not authorized — caller does not own this record."
        )
    elif has_owner and shared_model:
        delete_doc = (
            f"Delete a {cls} by its UUID.\n\n"
            f"    Access policy: shared model — any authenticated user may delete\n"
            f"    any {cls} row.  EXPLICIT opt-out from the secure-by-default\n"
            "    ownership guard via ``shared_models=...``.\n\n"
            "    Raises:\n"
            f"        HTTPException 404: {cls} not found."
        )
    elif has_auth:
        delete_doc = (
            f"Delete a {cls} by its UUID.\n\n"
            "    Access policy: authentication required; any active user may delete\n"
            "    any record (no per-object ownership check is enforced).\n\n"
            "    Raises:\n"
            f"        HTTPException 404: {cls} not found."
        )
    else:
        delete_doc = (
            f"Delete a {cls} by its UUID.\n\n"
            "    Access policy: public — no authentication required.\n\n"
            "    Raises:\n"
            f"        HTTPException 404: {cls} not found."
        )

    delete_route = _build_route(
        method="delete",
        path="/{id}",
        func_name=f"delete_{lower}",
        doc=delete_doc,
        params=delete_sig,
        return_type="Message",
        body_lines=delete_body_lines,
    )

    # ------------------------------------------------------------------
    # Assemble full file
    # ------------------------------------------------------------------
    content = "\n".join(import_lines)
    content += "\n\n"
    content += router_line
    content += "\n"
    content += list_route
    content += get_route
    content += create_route
    content += update_route
    content += delete_route

    file_path = out / f"{lower}.py"
    file_path.write_text(content)

    # ------------------------------------------------------------------
    # Notes
    # ------------------------------------------------------------------
    notes = [
        f"Generated api/routes/{lower}.py with 5 CRUD endpoints for {cls}.",
        f"Router prefix: {url_prefix}  |  Auth mode: {auth}.",
    ]
    if enforce_owner_guard:
        notes.append("Owner-scoped access control enabled (owner_id injected from current user).")
    elif has_owner and shared_model:
        notes.append(
            f"Shared model (BOLA opt-out): owner_id is tracked on create but per-object "
            f"ownership guard is suppressed — any authenticated user may read/update/delete "
            f"any {cls} row.  Listed in shared_models=..., audited in tests/test_bola_shared_models.py."
        )
    notes.append(
        f"Imports: crud/{lower}.py, schemas/{lower}.py "
        f"(contains {cls}Create/Update/Public + {plural_class}Public)."
    )

    return {"files_created": [str(file_path)], "notes": notes}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_route(
    *,
    method: str,
    path: str,
    func_name: str,
    doc: str,
    params: str,
    return_type: str,
    body_lines: list[str],
    status_code: int | None = None,
) -> str:
    """Build a single route function as a string block."""
    # Decorator
    status_arg = ", status_code=status.HTTP_201_CREATED" if status_code == 201 else ""
    decorator = f'@router.{method}("{path}", response_model={return_type}{status_arg})'

    body = "\n".join(body_lines)

    return textwrap.dedent(f"""

{decorator}
async def {func_name}(
    {params},
) -> {return_type}:
    \"\"\"{doc}
    \"\"\"
{body}
""")
