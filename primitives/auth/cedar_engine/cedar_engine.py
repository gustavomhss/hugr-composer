"""Pure Python primitive: CedarEngine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import uuid
from datetime import datetime

class CedarEngine:
    """File-based Cedar policy engine.

    Attributes:
        _policy_dir: Directory from which .cedar files are loaded.
        _policies: Combined policy text from all loaded .cedar files.
        _loaded: True once policies have been loaded successfully.
    """

    def __init__(self, policy_dir: str | Path) -> None:
        """Initialise the engine with a policy directory.

        Args:
            policy_dir: Path to the directory containing .cedar files.
        """
        self._policy_dir = Path(policy_dir)
        self._policies: str = ''
        self._loaded: bool = False

    def load_policies(self, directory: str | Path | None=None) -> None:
        """Load all .cedar files from *directory* (or the configured dir).

        Args:
            directory: Override the directory set at construction time.
        """
        target = Path(directory) if directory else self._policy_dir
        if not target.is_dir():
            logger.warning('Cedar policy dir not found: %s', target)
            return
        parts: list[str] = []
        for policy_file in sorted(target.glob('*.cedar')):
            text = policy_file.read_text(encoding='utf-8')
            parts.append(text)
            logger.debug('Loaded Cedar policy: %s', policy_file.name)
        self._policies = '\n'.join(parts)
        self._loaded = bool(parts)
        logger.info('Cedar: loaded %d policy file(s) from %s', len(parts), target)

    def is_authorized(self, principal: str, action: str, resource: str, context: dict | None=None) -> bool:
        """Evaluate a Cedar authorization decision.

        Falls back to CEDAR_DEFAULT_EFFECT when cedarpy is not installed
        or when no policies are loaded.

        Args:
            principal: Principal entity string, e.g. ``'User::"alice"'``.
            action: Action entity string, e.g. ``'Action::"read"'``.
            resource: Resource entity string, e.g. ``'Resource::"report-42"'``.
            context: Optional key/value context attributes.

        Returns:
            ``True`` if the request is allowed, ``False`` if denied.
        """
        from app.core.config import settings
        if not getattr(settings, 'CEDAR_ENABLED', False):
            return True
        if not self._loaded:
            effect = getattr(settings, 'CEDAR_DEFAULT_EFFECT', 'deny')
            return effect == 'allow'
        try:
            import cedarpy
            req = cedarpy.AuthorizationRequest(principal=principal, action=action, resource=resource, context=context or {})
            decision = cedarpy.is_authorized(self._policies, req)
            return decision.allowed
        except Exception as exc:
            logger.error('Cedar evaluation error: %s', exc)
            return False
