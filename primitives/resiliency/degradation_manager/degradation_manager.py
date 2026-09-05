"""Pure Python primitive: DegradationManager."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import uuid
from datetime import datetime

class DegradationManager:
    """Manages which features are enabled based on the current degradation tier.

    Thread-safe for read access; writes are single-threaded (from middleware).
    """

    def __init__(self) -> None:
        """Initialise with NORMAL tier (all features enabled)."""
        self._tier = DegradationTier.NORMAL
        self._disabled: frozenset[str] = frozenset()

    def set_tier(self, tier: DegradationTier) -> None:
        """Update the active degradation tier.

        Args:
            tier: New degradation tier from LoadShedder.
        """
        if tier != self._tier:
            logger.info('Degradation tier changed: %s → %s', self._tier.value, tier.value)
        self._tier = tier
        self._disabled = _TIER_DISABLED[tier]

    def is_feature_enabled(self, feature: str) -> bool:
        """Return True if *feature* is currently available.

        Args:
            feature: Feature name (e.g. 'analytics_events').

        Returns:
            True when the feature should run, False when degraded away.
        """
        return feature not in self._disabled

    def get_tier(self) -> DegradationTier:
        """Return the current degradation tier."""
        return self._tier

    def disabled_features(self) -> list[str]:
        """Return sorted list of currently disabled feature names."""
        return sorted(self._disabled)
