"""High-level ADAPT tools that add features to existing projects."""

from .add_background_job import add_background_job
from .add_endpoint import add_endpoint
from .add_integration import add_integration
from .add_middleware import add_middleware
from .add_websocket import add_websocket
from .fix_findings import fix_findings
from .migrate_db import generate_migration

__all__ = [
    "add_background_job",
    "add_endpoint",
    "add_integration",
    "add_middleware",
    "add_websocket",
    "fix_findings",
    "generate_migration",
]
