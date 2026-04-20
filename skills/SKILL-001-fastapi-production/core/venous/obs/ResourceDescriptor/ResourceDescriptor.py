"""ResourceDescriptor primitive — entity identity attached to telemetry.

Invariant IDs:

- RD-INV-01: service.name MUST be non-empty; missing SHALL cause fast-fail init.
- RD-INV-02: service.instance.id MUST be unique per process and stable for its lifetime.
- RD-INV-03: deployment.environment.name MUST be one of {development, staging,
  production, preview}; free-form FORBIDDEN.
- RD-INV-04: the descriptor is immutable; merged_with ALWAYS returns a new descriptor.
- RD-INV-05: to_attributes MUST use canonical semconv keys (service.name, not serviceName).
- RD-INV-06: the descriptor NEVER contains secrets, credentials, or PII.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Final

ALLOWED_ENVIRONMENTS: Final[frozenset[str]] = frozenset({
    "development", "staging", "production", "preview",
})
SECRET_LIKE_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"(?i)password"),
    re.compile(r"(?i)secret"),
    re.compile(r"(?i)api[_-]?key"),
    re.compile(r"(?i)authorization"),
    re.compile(r"(?i)bearer"),
)


class ResourceInvariantError(ValueError):
    """Runtime invariant violation."""


def _validate_no_secrets(attrs: Mapping[str, str]) -> None:
    for k, v in attrs.items():
        full = f"{k}={v}"
        for pat in SECRET_LIKE_PATTERNS:
            if pat.search(full):
                raise ResourceInvariantError(
                    f"RD-INV-06: attribute {k!r} appears to contain a secret."
                )


@dataclass(frozen=True)
class ResourceDescriptor:
    """Immutable descriptor of a telemetry-emitting entity."""

    service_name: str
    service_namespace: str | None
    service_version: str
    service_instance_id: str
    deployment_environment: str
    attributes: Mapping[str, str]

    def __post_init__(self) -> None:
        if not isinstance(self.service_name, str) or not self.service_name:
            raise ResourceInvariantError(
                "RD-INV-01: service.name MUST be non-empty."
            )
        if not isinstance(self.service_instance_id, str) or not self.service_instance_id:
            raise ResourceInvariantError(
                "RD-INV-02: service.instance.id MUST be non-empty."
            )
        if self.deployment_environment not in ALLOWED_ENVIRONMENTS:
            raise ResourceInvariantError(
                f"RD-INV-03: deployment.environment.name MUST be one of "
                f"{sorted(ALLOWED_ENVIRONMENTS)}, got {self.deployment_environment!r}."
            )
        # Freeze a defensive copy of attributes.
        object.__setattr__(self, "attributes", dict(self.attributes))
        _validate_no_secrets(self.attributes)

    def merged_with(self, overrides: Mapping[str, str]) -> ResourceDescriptor:
        """RD-INV-04: return a new descriptor; never mutate self."""
        _validate_no_secrets(overrides)
        merged_attrs = {**self.attributes, **overrides}
        return replace(self, attributes=merged_attrs)

    def to_attributes(self) -> Mapping[str, str]:
        """RD-INV-05: canonical SemConv keys only."""
        out: dict[str, str] = {
            "service.name": self.service_name,
            "service.version": self.service_version,
            "service.instance.id": self.service_instance_id,
            "deployment.environment.name": self.deployment_environment,
        }
        if self.service_namespace:
            out["service.namespace"] = self.service_namespace
        out.update(self.attributes)
        return out


__all__ = [
    "ALLOWED_ENVIRONMENTS",
    "ResourceDescriptor",
    "ResourceInvariantError",
]
