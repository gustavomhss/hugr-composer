from __future__ import annotations
from collections.abc import Iterable


def evaluate_scope(granted_scopes: Iterable[str], required_scope: str) -> ScopeCheckResult:
    """Evaluate whether any granted scope satisfies the required scope.

    Deny-by-default: the key must have an explicit grant that matches.
    Wildcards are expanded on both resource and action segments.

    Args:
        granted_scopes: Iterable of scope strings from the API key record.
        required_scope: The ``resource:action`` scope the route requires.

    Returns:
        ``ScopeCheckResult`` with ``allowed``, ``matched_scope``, and ``reason``.
    """
    required_scope = required_scope.strip()
    if ':' not in required_scope:
        return ScopeCheckResult(allowed=False, matched_scope=None, reason=f"required scope must be 'resource:action', got {required_scope!r}")
    for scope in granted_scopes:
        if _scope_matches(scope, required_scope):
            return ScopeCheckResult(allowed=True, matched_scope=scope, reason='matched')
    return ScopeCheckResult(allowed=False, matched_scope=None, reason=f'no granted scope matches {required_scope!r}')
