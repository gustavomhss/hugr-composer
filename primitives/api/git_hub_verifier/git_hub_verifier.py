"""Inbound verifier: GitHubVerifier."""

from __future__ import annotations

from typing import Protocol

class InboundVerifier(Protocol):
    name: str
    def verify(self, body: bytes, headers: dict[str, str]) -> "VerifiedEvent": ...


class GitHubVerifier(InboundVerifier):
    """Verify GitHub webhook payloads."""

    name = "github"

    def verify(self, body: bytes, headers: dict[str, str]) -> dict:
        """Verify a GitHub-signed webhook request."""
        raise NotImplementedError
