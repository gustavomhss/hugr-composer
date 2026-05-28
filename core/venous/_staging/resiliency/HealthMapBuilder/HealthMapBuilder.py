from __future__ import annotations
from typing import Any
import asyncio
import os


class HealthMapBuilder:
    """Discovers dependencies from environment and builds a health graph.

    Uses config env vars to detect which dependencies are configured.
    Only enabled deps (env var present and non-empty) appear in the map.
    """

    def __init__(self) -> None:
        self._extra: dict[str, Any] = {}

    def discover(self) -> list[str]:
        """Return list of dependency names that are configured in env."""
        found = []
        for dep, env_key in _KNOWN_DEPS.items():
            if os.getenv(env_key, ''):
                found.append(dep)
        found.extend(self._extra.keys())
        return found

    def register(self, name: str, check_fn: Any) -> None:
        """Register a custom dependency check function.

        Args:
            name: Dependency name (used as graph node label).
            check_fn: Async callable returning dict with 'status' key.
        """
        self._extra[name] = check_fn

    async def build_graph(self) -> dict[str, Any]:
        """Run all checks and return a JSON-serializable dependency graph.

        Returns:
            Dict with 'nodes' (list of dep status) and 'edges'
            (list of {"from": "api", "to": dep_name}).
        """
        from app.health_map.checker import DependencyChecker
        checker = DependencyChecker()
        dep_names = self.discover()
        results = await asyncio.gather(*[checker.check(name) for name in dep_names], return_exceptions=True)
        nodes = []
        for name, res in zip(dep_names, results):
            if isinstance(res, Exception):
                nodes.append({'name': name, 'status': 'error', 'latency_ms': 0})
            else:
                nodes.append(res)
        edges = [{'from': 'api', 'to': n['name']} for n in nodes]
        overall = _aggregate(nodes)
        return {'status': overall, 'nodes': nodes, 'edges': edges}
