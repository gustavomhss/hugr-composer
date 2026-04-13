"""Shared Pydantic contracts for all adapt tools.

Every adapt tool accepts a ``ToolInput`` and returns a ``ToolResult``.
Centralising the contracts here keeps tool signatures uniform and lets
callers pattern-match on ``status`` without importing individual tools.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ToolInput(BaseModel):
    """Input contract for every adapt tool.

    Attributes:
        project_dir: Absolute path to the root of the FastAPI project
            (the directory that contains ``app/``, ``alembic/``, etc.).
        dry_run: When ``True``, the tool analyses the project and returns
            a preview ``ToolResult`` without writing any files to disk.
    """

    project_dir: str = Field(..., description="Absolute path to the FastAPI project root.")
    dry_run: bool = Field(
        default=False,
        description="Preview changes without writing files. Defaults to False.",
    )


class ToolResult(BaseModel):
    """Output contract for every adapt tool.

    Attributes:
        status: Outcome of the tool execution.

            * ``"success"`` — all changes were applied successfully.
            * ``"no_op"``   — the feature is already present; nothing was written.
            * ``"error"``   — execution failed; inspect ``error`` for details.

        files_created: Relative or absolute paths of files created during
            this run.  Empty on ``no_op`` or ``error``.
        files_modified: Relative or absolute paths of files modified during
            this run.  Empty on ``no_op`` or ``error``.
        warnings: Non-fatal observations the caller should review (e.g.
            deprecated patterns found in the project that the tool worked
            around).
        notes: Informational messages describing what was done or skipped.
        next_steps: Ordered list of manual actions the developer should
            take after the tool finishes (e.g. "run alembic upgrade head").
        error: Human-readable error message.  ``None`` unless
            ``status == "error"``.
        execution_time_ms: Wall-clock time the tool took to run, in
            milliseconds.
    """

    status: Literal["success", "no_op", "error"]
    files_created: list[str] = Field(default_factory=list)
    files_modified: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    error: str | None = None
    execution_time_ms: int = 0
