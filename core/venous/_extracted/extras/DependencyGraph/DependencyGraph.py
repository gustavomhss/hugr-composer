from __future__ import annotations
from collections import defaultdict
from collections import deque
from typing import Any


class DependencyGraph:
    """Build a dependency graph and produce a topological seed order.

    Args:
        models: List of SQLAlchemy mapper objects or model classes.
    """

    def __init__(self, models: list[Any]) -> None:
        """Initialise with a list of SQLAlchemy model classes/mappers.

        Args:
            models: SQLAlchemy mapper objects or ORM classes.
        """
        self._models = models

    def topological_order(self) -> list[Any]:
        """Return models sorted by FK dependency (parents before children).

        Uses Kahn's algorithm (BFS-based topological sort) to produce a
        stable ordering where every model appears after all its FK parents.

        Returns:
            List of model classes/mappers in safe insert order.
            Cycles are broken by removing the back-edge and logging a warning.
        """
        classes = self._resolve_classes()
        name_to_cls: dict[str, Any] = {cls.__name__: cls for cls in classes}
        graph: dict[str, list[str]] = defaultdict(list)
        in_degree: dict[str, int] = {name: 0 for name in name_to_cls}
        for cls in classes:
            deps = self._get_dependencies(cls, name_to_cls)
            for dep in deps:
                if dep in name_to_cls and dep != cls.__name__:
                    graph[dep].append(cls.__name__)
                    in_degree[cls.__name__] += 1
        queue: deque[str] = deque((name for name, deg in in_degree.items() if deg == 0))
        ordered: list[Any] = []
        while queue:
            name = queue.popleft()
            ordered.append(name_to_cls[name])
            for dependent in graph[name]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)
        remaining = [n for n, d in in_degree.items() if d > 0]
        if remaining:
            logger.warning('Cycle detected in model dependencies, seeding %s last: %s', remaining, remaining)
            for name in remaining:
                ordered.append(name_to_cls[name])
        return ordered

    def _resolve_classes(self) -> list[Any]:
        """Resolve mapper objects to their underlying ORM classes.

        Returns:
            List of ORM model classes.
        """
        classes: list[Any] = []
        for model in self._models:
            cls = model.class_ if hasattr(model, 'class_') else model
            if hasattr(cls, '__mapper__'):
                classes.append(cls)
        return classes

    def _get_dependencies(self, cls: Any, known: dict[str, Any]) -> list[str]:
        """Return names of models that *cls* depends on via FK columns.

        Args:
            cls: ORM model class.
            known: Mapping of class name to class for registered models.

        Returns:
            List of model class names that *cls* has FK references to.
        """
        deps: list[str] = []
        try:
            for rel in cls.__mapper__.relationships:
                related_cls = rel.mapper.class_
                if related_cls.__name__ in known:
                    deps.append(related_cls.__name__)
        except Exception:
            pass
        return deps
