from __future__ import annotations


class AdminAuthBackend(_Base):
    """Cookie-based auth backend for the SQLAdmin panel.

    Authenticates users via email + password using the existing
    scaffold helpers and stores a minimal session token.
    """

    async def login(self, request: 'Request') -> bool:
        """Validate login form and create an admin session.

        Args:
            request: The Starlette request with form data containing
                ``username`` (email) and ``password`` fields.

        Returns:
            ``True`` if authentication succeeded, ``False`` otherwise.
        """
        from app.core.db import engine
        from app.core.security import verify_password
        from app.models.user import User
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession
        form = await request.form()
        email = form.get('username', '')
        password = form.get('password', '')
        if not email or not password:
            return False
        async with AsyncSession(engine) as session:
            stmt = select(User).where(User.email == str(email))
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()
        if user is None:
            return False
        if not verify_password(str(password), user.hashed_password):
            return False
        require_superuser = REQUIRE_SUPERUSER_PLACEHOLDER
        if require_superuser and (not getattr(user, 'is_superuser', False)):
            logger.warning('Admin login denied for non-superuser: %s', str(email))
            return False
        request.session['admin_user_id'] = str(user.id)
        request.session['admin_email'] = str(user.email)
        return True

    async def logout(self, request: 'Request') -> bool:
        """Clear the admin session.

        Args:
            request: The Starlette request whose session will be
                cleared.

        Returns:
            Always ``True``.
        """
        request.session.clear()
        return True

    async def authenticate(self, request: 'Request') -> bool:
        """Check whether the current session is authenticated.

        Args:
            request: The Starlette request to check.

        Returns:
            ``True`` if a valid admin session exists, ``False``
            otherwise.
        """
        user_id = request.session.get('admin_user_id')
        if not user_id:
            return False
        return True
