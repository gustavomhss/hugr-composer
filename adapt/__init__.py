"""adapt — Phase 2 tool layer for SKILL-001-fastapi-production.

Public surface:

    from adapt.contracts import ToolInput, ToolResult
    from adapt.extend.crud_data.add_soft_delete import add_soft_delete
"""

from adapt.contracts import ToolInput, ToolResult

__all__ = ["ToolInput", "ToolResult"]
