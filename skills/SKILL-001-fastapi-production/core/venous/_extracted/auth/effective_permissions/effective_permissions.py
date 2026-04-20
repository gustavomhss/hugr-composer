from __future__ import annotations


def effective_permissions(role_name: str, registry: dict[str, RoleNode], _visited: frozenset[str] | None=None) -> frozenset[str]:
    """Return merged permission set for a role by walking the DAG recursively.

    Args:
        role_name: Name of the role to resolve.
        registry: Mapping of role name → RoleNode.
        _visited: Internal cycle-detection set (callers should omit).

    Returns:
        Frozen set of permission codes (e.g. ``frozenset({'items:read'})``)

    Raises:
        ValueError: If ``role_name`` is not in ``registry``.
        CyclicRoleError: If a cycle is detected in the inheritance chain.
    """
    if role_name not in registry:
        raise ValueError(f'unknown role: {role_name!r}')
    visited = _visited or frozenset()
    if role_name in visited:
        raise CyclicRoleError(f'cycle detected at role {role_name!r}')
    visited = visited | {role_name}
    role = registry[role_name]
    result: set[str] = set(role.direct_permissions)
    for parent in role.parent_role_names:
        result |= effective_permissions(parent, registry, visited)
    return frozenset(result)
