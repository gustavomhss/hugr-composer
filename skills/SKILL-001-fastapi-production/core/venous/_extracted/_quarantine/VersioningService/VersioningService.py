from __future__ import annotations
from datetime import datetime
from datetime import timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any
import uuid


class VersioningService:
    """Service layer for content version lifecycle management.

    Attributes:
        max_drafts: Maximum concurrent drafts allowed per content_id.
    """

    def __init__(self, max_drafts: int=_DEFAULT_MAX_DRAFTS) -> None:
        """Initialise the service.

        Args:
            max_drafts: Maximum concurrent drafts per content item.
        """
        self.max_drafts = max_drafts

    async def create_draft(self, session: AsyncSession, content_id: str, content_type: str, data: dict[str, Any], author_id: uuid.UUID | None=None) -> ContentVersion:
        """Create a new draft version for a content item.

        Enforces max_drafts limit. Auto-increments version_number.

        Args:
            session: Async SQLAlchemy session.
            content_id: Opaque string ID of the content item.
            content_type: Lowercase name of the content type (e.g. 'article').
            data: JSON-serialisable dict representing the content snapshot.
            author_id: UUID of the user creating the draft.

        Returns:
            The newly created ContentVersion with status='draft'.

        Raises:
            ValueError: If max_drafts limit is reached for this content_id.
        """
        drafts = await self._count_drafts(session, content_id)
        if drafts >= self.max_drafts:
            raise ValueError(f'Max drafts ({self.max_drafts}) reached for content_id={content_id}')
        next_version = await self._next_version_number(session, content_id)
        version = ContentVersion(content_id=content_id, content_type=content_type, version_number=next_version, status='draft', data_json=data, author_id=author_id)
        session.add(version)
        await session.commit()
        await session.refresh(version)
        return version

    async def publish(self, session: AsyncSession, content_id: str, version_number: int) -> ContentVersion:
        """Publish a specific draft version.

        Transitions the target version to published and archives any
        currently published version for the same content_id.

        Args:
            session: Async SQLAlchemy session.
            content_id: Opaque string ID of the content item.
            version_number: Version number of the draft to publish.

        Returns:
            The updated ContentVersion with status='published'.

        Raises:
            ValueError: If the target version does not exist or is not a draft.
        """
        version = await self._get_version(session, content_id, version_number)
        if version is None:
            raise ValueError(f'Version {version_number} not found for content_id={content_id}')
        if version.status not in ('draft', 'pending'):
            raise ValueError(f'Only draft versions can be published; current status={version.status}')
        await self._archive_current_published(session, content_id)
        version.status = 'published'
        version.published_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(version)
        return version

    async def archive(self, session: AsyncSession, content_id: str, version_number: int) -> ContentVersion:
        """Archive a specific version (idempotent).

        Args:
            session: Async SQLAlchemy session.
            content_id: Opaque string ID of the content item.
            version_number: Version number to archive.

        Returns:
            The updated ContentVersion with status='archived'.

        Raises:
            ValueError: If the target version does not exist.
        """
        version = await self._get_version(session, content_id, version_number)
        if version is None:
            raise ValueError(f'Version {version_number} not found for content_id={content_id}')
        if version.status != 'archived':
            version.status = 'archived'
            await session.commit()
            await session.refresh(version)
        return version

    async def get_history(self, session: AsyncSession, content_id: str, limit: int=50) -> list[ContentVersion]:
        """Return all versions for a content item, newest first.

        Args:
            session: Async SQLAlchemy session.
            content_id: Opaque string ID of the content item.
            limit: Maximum number of versions to return.

        Returns:
            List of ContentVersion instances ordered by version_number desc.
        """
        stmt = select(ContentVersion).where(ContentVersion.content_id == content_id).order_by(ContentVersion.version_number.desc()).limit(limit)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def diff(self, session: AsyncSession, content_id: str, v1: int, v2: int) -> dict[str, Any]:
        """Compute a field-level diff between two version numbers.

        Returns a dict with 'added', 'removed', and 'changed' keys.
        Values show (old, new) tuples for 'changed' fields.

        Args:
            session: Async SQLAlchemy session.
            content_id: Opaque string ID of the content item.
            v1: Earlier version number.
            v2: Later version number.

        Returns:
            Dict with 'added', 'removed', 'changed' field-level diffs.

        Raises:
            ValueError: If either version is not found.
        """
        ver1 = await self._get_version(session, content_id, v1)
        ver2 = await self._get_version(session, content_id, v2)
        if ver1 is None:
            raise ValueError(f'Version {v1} not found for content_id={content_id}')
        if ver2 is None:
            raise ValueError(f'Version {v2} not found for content_id={content_id}')
        return _compute_diff(ver1.data_json or {}, ver2.data_json or {})

    async def _count_drafts(self, session: AsyncSession, content_id: str) -> int:
        """Count active draft versions for a content item.

        Args:
            session: Async SQLAlchemy session.
            content_id: Opaque string ID of the content item.

        Returns:
            Number of versions with status='draft'.
        """
        stmt = select(ContentVersion).where(ContentVersion.content_id == content_id, ContentVersion.status == 'draft')
        result = await session.execute(stmt)
        return len(result.scalars().all())

    async def _next_version_number(self, session: AsyncSession, content_id: str) -> int:
        """Compute the next version number for a content item.

        Args:
            session: Async SQLAlchemy session.
            content_id: Opaque string ID of the content item.

        Returns:
            Current max version_number + 1, or 1 if no versions exist.
        """
        stmt = select(ContentVersion.version_number).where(ContentVersion.content_id == content_id).order_by(ContentVersion.version_number.desc()).limit(1)
        result = await session.execute(stmt)
        current = result.scalar_one_or_none()
        return (current or 0) + 1

    async def _get_version(self, session: AsyncSession, content_id: str, version_number: int) -> ContentVersion | None:
        """Fetch a specific version by content_id and version_number.

        Args:
            session: Async SQLAlchemy session.
            content_id: Opaque string ID of the content item.
            version_number: The version to fetch.

        Returns:
            ContentVersion instance or None if not found.
        """
        stmt = select(ContentVersion).where(ContentVersion.content_id == content_id, ContentVersion.version_number == version_number)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def _archive_current_published(self, session: AsyncSession, content_id: str) -> None:
        """Archive any currently published version for a content item.

        Args:
            session: Async SQLAlchemy session.
            content_id: Opaque string ID of the content item.
        """
        stmt = select(ContentVersion).where(ContentVersion.content_id == content_id, ContentVersion.status == 'published')
        result = await session.execute(stmt)
        for version in result.scalars().all():
            version.status = 'archived'
