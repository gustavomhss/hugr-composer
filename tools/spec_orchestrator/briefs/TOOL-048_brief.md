## Tool: `generate_admin_panel`

### Overview parameters
- Tool name: `fastapi_generate_admin_panel`
- Category: EVOLVE
- Complexity: High
- Dependencies: existing FastAPI project, SQLAlchemy models, optional sqladmin or starlette-admin
- Signature: `generate_admin_panel(project_dir: str, models: list[str] | None = None, mount_path: str = "/admin", auth_dependency: str = "require_admin", theme: str = "default", read_only_models: list[str] | None = None) -> dict`
- Parameters:
  - `project_dir`: project root
  - `models`: list of model names to expose; default all
  - `mount_path`: URL prefix for the admin panel
  - `auth_dependency`: the FastAPI dependency used to guard admin access
  - `theme`: `default`, `dark`, or custom template
  - `read_only_models`: models exposed only in read mode (no create/edit/delete)

### Purpose
Scaffold a complete admin panel mounted at `/admin` that auto-generates list/detail/create/edit/delete views for every SQLAlchemy model. Uses sqladmin (or starlette-admin as fallback) with customization hooks for: permissions per action, audit logging, soft-delete awareness, multi-tenancy filtering, relationship dropdowns, and CSV export. Generates the scaffolding + customization points + tests + documentation. Essential for internal ops teams who need to inspect/edit data without touching the database. Auth is enforced at the mount level via a FastAPI dependency (must resolve to a user with admin role).

### Performance SLOs
- Tool execution time < 5s (generation)
- Files modified ≤ 3 (main.py, pyproject.toml, Makefile)
- Files created ≥ 10 (admin module, model views, auth wrapper, audit hook, templates, tests, docs, CI workflow, README, Makefile targets)
- Admin list view < 200 ms for 10k rows
- Admin edit save < 100 ms
- Minimal overhead on non-admin requests

### Key technical decisions
1. **Framework:** sqladmin (primary) — async-first, Pydantic-compatible
2. **Model discovery:** walks `src/models/` for all `DeclarativeBase` subclasses
3. **Per-model view:** one `ModelView` class per model in `admin/views/`
4. **Auth:** entire `/admin` guarded by a single dependency (`Depends(require_admin)`)
5. **Audit:** every write action logged to audit_log table via middleware
6. **Soft-delete awareness:** list view hides soft-deleted by default, filter to show
7. **Multi-tenant aware:** queries filtered by current user's tenant
8. **Relationship rendering:** FKs as dropdowns with search
9. **CSV export:** per-model action, bounded to 10k rows
10. **Read-only mode:** models in `read_only_models` have create/edit/delete hidden

### Key invariants
1. Admin panel is ALWAYS auth-gated; anonymous NEVER reaches it.
2. Every write action is ALWAYS audit-logged.
3. Soft-deleted rows are ALWAYS hidden unless explicitly filtered.
4. Multi-tenancy is ALWAYS enforced (tenant_id in queries).
5. Read-only models are NEVER editable through admin.
6. CSV export is ALWAYS row-bounded (prevent DoS).
7. Model views are ALWAYS regenerated on schema change.

### User story themes
- 9.1 Basic admin (US-01..05): list, detail, create, edit, delete
- 9.2 Auth (US-06..10): require admin, reject anonymous, reject non-admin, session
- 9.3 Advanced features (US-11..15): soft-delete, multi-tenant, FK dropdown, search, bulk
- 9.4 Audit (US-16..20): write logged, read logged (optional), attribution, filter
- 9.5 Edge cases (US-21..25): read-only, CSV export, theme, tool idempotency

### Test plan categories
- 10.1 CRUD (T-01..06): list, detail, create, edit, delete, pagination
- 10.2 Auth (T-07..12): unauthenticated, wrong role, valid admin
- 10.3 Advanced (T-13..18): soft-delete, multi-tenant, FK, bulk
- 10.4 Audit (T-19..24): write logged, attribution, filter
- 10.5 Edge cases (T-25..30): read-only, CSV, tool idempotency

### Edge cases (15)
1. Anonymous request → 401 redirect
2. Authenticated non-admin → 403
3. List view with 10k rows → pagination, < 200 ms
4. Edit a soft-deleted row → blocked unless explicitly allowed
5. Edit across tenants → blocked by tenant filter
6. CSV export with 100k rows → truncated to 10k, warning shown
7. FK dropdown with 1M rows → async search, paginated
8. Model with no primary key → not exposed
9. Model with composite PK → detail view supported
10. Read-only model → no edit/create/delete buttons
11. Tool re-run idempotent (same models → same views)
12. New model added after generation → scaffold needs re-run
13. Relationship cycle → recursion bounded
14. Audit hook fails → action rolled back, error shown
15. Theme override → CSS loaded

### Anti-patterns
- DO NOT skip auth (admin panels are high-value targets)
- DO NOT expose without CSRF protection
- DO NOT allow unlimited CSV exports (DoS)
- DO NOT forget audit logging (compliance issue)
- DO NOT display soft-deleted rows by default
