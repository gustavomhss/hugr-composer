from __future__ import annotations
from pathlib import Path
from typing import Any
import json


def load_spec(spec_path: str | None=None) -> dict[str, Any]:
    """Load the OpenAPI spec from disk or return an empty spec.

    Args:
        spec_path: Optional filesystem path to an openapi.json file.
            Falls back to settings.SCHEMA_ENFORCER_SPEC_PATH.

    Returns:
        Parsed OpenAPI spec dict, or empty dict when unavailable.
    """
    path_str = spec_path or getattr(settings, 'SCHEMA_ENFORCER_SPEC_PATH', '')
    if not path_str:
        return {}
    p = Path(path_str)
    if not p.is_file():
        logger.warning('schema_enforcer.spec_not_found', extra={'path': path_str})
        return {}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError as exc:
        logger.error('schema_enforcer.spec_parse_error', extra={'exc': str(exc)})
        return {}
