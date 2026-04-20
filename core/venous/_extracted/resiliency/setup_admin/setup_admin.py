from __future__ import annotations


def setup_admin(app: 'FastAPI') -> None:
    """Mount the SQLAdmin panel on *app*.

    Imports ``sqladmin`` lazily so the application can boot (and pass
    health checks) without the package installed.  When the import
    fails a warning is logged and the function returns without
    mounting anything.

    Args:
        app: The FastAPI application instance.
    """
    try:
        from sqladmin import Admin
    except ImportError:
        logger.warning('sqladmin not installed — admin panel disabled. Install with: pip install sqladmin')
        return
    from app.admin.auth import AdminAuthBackend
    from app.admin.views import MODEL_ADMINS
    from app.core.db import engine
    try:
        from starlette.middleware.sessions import SessionMiddleware
        app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY)
    except ImportError:
        logger.warning('itsdangerous not installed — admin auth disabled')
    path = getattr(settings, 'ADMIN_PATH', 'ADMIN_PATH_PLACEHOLDER')
    title = getattr(settings, 'ADMIN_TITLE', 'ADMIN_TITLE_PLACEHOLDER')
    auth_backend = AdminAuthBackend(secret_key=settings.SECRET_KEY)
    admin = Admin(app, engine, base_url=path, title=title, authentication_backend=auth_backend)
    for view_cls in MODEL_ADMINS:
        admin.add_view(view_cls)
    logger.info('SQLAdmin panel mounted at %s', path)
