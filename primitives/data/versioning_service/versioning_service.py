"""Content versioning service."""

from __future__ import annotations

_DEFAULT_MAX_DRAFTS = 10

class VersioningService:
    """Manages content versions and drafts."""

    def __init__(self, max_drafts: int = _DEFAULT_MAX_DRAFTS):
        self.max_drafts = max_drafts
        self._versions = {}

    def create_draft(self, content_id: str, content: str) -> int:
        if content_id not in self._versions:
            self._versions[content_id] = []
        version = len(self._versions[content_id]) + 1
        if len(self._versions[content_id]) >= self.max_drafts:
            self._versions[content_id].pop(0)
        self._versions[content_id].append({"version": version, "content": content})
        return version
