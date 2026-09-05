from __future__ import annotations
from dataclasses import dataclass
from dataclasses import field


@dataclass(frozen=True)
class RoleNode:
    """Lightweight role representation for in-memory DAG traversal.

    Attributes:
        name: Unique role name.
        direct_permissions: Permission codes directly assigned to this role.
        parent_role_names: Names of parent roles (for inheritance).
    """
    name: str
    direct_permissions: frozenset[str]
    parent_role_names: frozenset[str] = field(default_factory=frozenset)
