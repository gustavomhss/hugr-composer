from __future__ import annotations
from dataclasses import dataclass
from dataclasses import field
import time


@dataclass
class SecurityEvent:
    """Immutable record of a detected attack attempt.

    Attributes:
        attack_type: Category (sql_injection, command_injection, ssrf).
        request_path: URL path where the attack was detected.
        payload_snippet: First 120 chars of the offending value.
        timestamp: Unix epoch float when detected.
        client_ip: Remote IP address of the request.
        blocked: Whether the request was blocked (enforcing mode).
    """
    attack_type: str
    request_path: str
    payload_snippet: str
    timestamp: float = field(default_factory=time.time)
    client_ip: str = 'unknown'
    blocked: bool = False
