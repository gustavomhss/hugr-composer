"""Protocol for FeatureToggle — generated from FeatureToggle.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

@runtime_checkable
class FeatureToggle(Protocol):
    """FeatureToggle primitive — named boolean predicate evaluated against context."""

    def is_active(self, ctx: ToggleContext) -> bool: ...
