"""Pure Python primitive: VersionRegistry."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import uuid
from datetime import datetime

class VersionRegistry:
    """Holds all known API versions.

    Attributes:
        _versions: Internal mapping from version label to VersionInfo.
    """

    def __init__(self) -> None:
        self._versions: dict[str, VersionInfo] = {}

    def register(self, info: VersionInfo) -> None:
        """Add a version descriptor to the registry.

        Args:
            info: VersionInfo to register.
        """
        self._versions[info.name] = info

    def get(self, name: str) -> VersionInfo | None:
        """Return VersionInfo for *name*, or None if unknown.

        Args:
            name: Version label (e.g. "v1").

        Returns:
            VersionInfo or None.
        """
        return self._versions.get(name)

    def supported(self) -> list[str]:
        """Return all registered version labels.

        Returns:
            List of version label strings.
        """
        return list(self._versions.keys())

    def deprecated(self) -> list[str]:
        """Return labels of deprecated versions.

        Returns:
            List of deprecated version label strings.
        """
        return [v for v, info in self._versions.items() if info.is_deprecated]
