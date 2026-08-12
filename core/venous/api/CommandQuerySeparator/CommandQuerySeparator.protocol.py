"""Protocol for CommandQuerySeparator — generated from CommandQuerySeparator.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Callable, Mapping

@runtime_checkable
class CommandQuerySeparator(Protocol):
    """Protocol for the CQS primitive; signature mirrors the catalog api_signature."""

    def dispatch_command(self, command: object) -> object: ...
    def answer_query(self, query: object) -> object: ...
    def register_command_handler(self, command_type: type, handler: CommandHandler) -> None: ...
    def register_query_handler(self, query_type: type, handler: QueryHandler) -> None: ...
