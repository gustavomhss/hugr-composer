from __future__ import annotations
from datetime import datetime
import uuid


class FeatureFlagPublic(FeatureFlagBase):
    """Output schema for feature-flag API responses.

    Attributes:
        id: UUID primary key.
        created_at: UTC creation timestamp.
        updated_at: UTC last-updated timestamp.
        updated_by: UUID of the last actor.
    """
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    updated_by: uuid.UUID | None = None
