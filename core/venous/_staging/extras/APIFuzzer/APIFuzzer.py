from __future__ import annotations
from typing import Any
import os


class APIFuzzer:
    """Reads OpenAPI schema and generates adversarial inputs per field type.

    Args:
        base_url: Target server base URL (e.g. 'http://localhost:8000').
        schema: Pre-loaded OpenAPI schema dict.  When None the schema is
            fetched from ``{base_url}/openapi.json`` by FuzzRunner.
    """

    def __init__(self, base_url: str, schema: dict[str, Any] | None=None) -> None:
        self.base_url = base_url.rstrip('/')
        self._schema: dict[str, Any] = schema or {}

    def set_schema(self, schema: dict[str, Any]) -> None:
        """Replace the loaded schema.

        Args:
            schema: OpenAPI 3.x schema dict from /openapi.json.
        """
        self._schema = schema

    def endpoint_list(self) -> list[dict[str, Any]]:
        """Return a list of endpoint descriptors from the loaded schema.

        Each descriptor has 'method', 'path', and 'body_schema' keys.

        Returns:
            List of dicts describing each POST/PUT/PATCH endpoint.
        """
        endpoints = []
        paths = self._schema.get('paths', {})
        exclude_raw = os.getenv('FUZZ_EXCLUDE_PATHS', '/docs,/openapi.json,/redoc')
        excluded = [p.strip() for p in exclude_raw.split(',') if p.strip()]
        for path, methods in paths.items():
            if any((path.startswith(ex) for ex in excluded)):
                continue
            for method in ('post', 'put', 'patch'):
                if method not in methods:
                    continue
                op = methods[method]
                body_schema = _extract_body_schema(op, self._schema)
                endpoints.append({'method': method.upper(), 'path': path, 'body_schema': body_schema})
        return endpoints

    def generate_payloads(self, body_schema: dict[str, Any] | None) -> list[dict[str, Any]]:
        """Generate a list of adversarial payload dicts for a body schema.

        Args:
            body_schema: JSON Schema dict for the request body.  When
                None a set of structurally adversarial payloads is returned.

        Returns:
            List of dicts ready to be JSON-serialised as request bodies.
        """
        from app.fuzzer.generators import build_payloads_for_schema
        return build_payloads_for_schema(body_schema or {})
