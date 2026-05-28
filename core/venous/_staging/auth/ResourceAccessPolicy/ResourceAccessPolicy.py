from __future__ import annotations
from dataclasses import dataclass
from typing import Any


@dataclass
class ResourceAccessPolicy:
    """Delegation policy allowing cross-user access grants.

    Attributes:
        grantor_id: User ID granting access.
        grantee_id: User ID receiving access.
        resource_model: Name of the model class being delegated.
        resource_id: Specific resource ID, or None for all owned resources.
        read_only: When True, grantee can read but not modify.
    """
    grantor_id: Any
    grantee_id: Any
    resource_model: str
    resource_id: Any = None
    read_only: bool = True

    def allows(self, user_id: Any, resource_id: Any, write: bool=False) -> bool:
        """Check whether this policy permits *user_id* to access *resource_id*.

        Args:
            user_id: Requesting user's ID.
            resource_id: Resource being accessed.
            write: True if this is a write/delete operation.

        Returns:
            True when access is permitted by this policy.
        """
        if user_id != self.grantee_id:
            return False
        if self.resource_id is not None and self.resource_id != resource_id:
            return False
        if write and self.read_only:
            return False
        return True
