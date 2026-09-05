"""Pure Python primitive: CanaryRegistry."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import uuid
from datetime import datetime

class CanaryRegistry:
    """Central registry of all deployed canary tokens.

    Attributes:
        _tokens: Internal mapping of token_id → CanaryToken.
    """
    _tokens: ClassVar[dict[str, CanaryToken]] = {}

    @classmethod
    def register(cls, token_id: str, canary_type: str, description: str) -> CanaryToken:
        """Register a canary token.

        Args:
            token_id: Unique ID (e.g. 'honeypot_internal_config').
            canary_type: Token type: 'honeypot', 'credential', 'decoy_record'.
            description: Human-readable description.

        Returns:
            The registered ``CanaryToken``.
        """
        token = CanaryToken(token_id=token_id, canary_type=canary_type, description=description)
        cls._tokens[token_id] = token
        logger.info('canary_registry: registered %s (%s)', token_id, canary_type)
        return token

    @classmethod
    def get(cls, token_id: str) -> CanaryToken | None:
        """Look up a token by ID.

        Args:
            token_id: The token to look up.

        Returns:
            ``CanaryToken`` or ``None`` when not registered.
        """
        return cls._tokens.get(token_id)

    @classmethod
    def all_tokens(cls) -> list[CanaryToken]:
        """Return all registered canary tokens.

        Returns:
            List of all ``CanaryToken`` instances in registration order.
        """
        return list(cls._tokens.values())
