"""MCP sidecar: fastapi_check_headers — thin wrapper over core.tools.runtime.check_security_headers."""
from __future__ import annotations


MCP_TOOL = {
    "name": "fastapi_check_headers",
    "description": "Check security headers and CORS of a running instance.",
    "tags": ["runtime", "verify"],
    "entry": "entry",
    "annotations": {"readOnlyHint": True},
}


def entry(base_url: str) -> dict:
    """Check security headers and CORS of a running instance."""
    import asyncio
    from core.tools.runtime import check_security_headers
    result = asyncio.run(check_security_headers(base_url))
    return result.model_dump(mode="json")
