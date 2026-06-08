"""Shared pytest configuration for the skill-001 test suite.

Some test files boot the *emitted* FastAPI app in-process via
``from app.main import app`` (e.g. ``test_full_integration.py`` and
``test_http_smoke.py``). The scaffold's ``Settings`` validator
(see ``generators/infra/config.py``) fail-fasts at import time on an
empty / short / known-weak ``SECRET_KEY`` — in every environment,
LOCAL included.

The fixture factory writes a valid ``.env`` into each generated project,
but pydantic-settings resolves ``env_file=".env"`` relative to the
*current working directory* (the worktree root under pytest), not the
temp project dir, so that ``.env`` is never picked up for an in-process
boot. Other test files work around this by calling
``os.environ.setdefault("SECRET_KEY", ...)`` at module import; this
conftest centralises that so a test-only key is present before ANY test
module is imported during collection.

Notes:
- ``setdefault`` is deliberate: it only sets the var when ABSENT, so it
  never clobbers a real shell value or a per-file override, and it stays
  compatible with the negative tests that pass their own explicit env to
  subprocesses.
- The value is a throwaway 64-hex-char string generated once per test
  process — NEVER a real secret. 64 hex chars = 32 bytes, satisfying the
  validator's 32-char minimum with margin.
"""

from __future__ import annotations

import os
import secrets

# Set a valid, test-only SECRET_KEY before any emitted app is imported.
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))
# Keep the emitted app in LOCAL mode for test boots (matches the .env the
# fixture factory writes; harmless if already set by a shell or a test).
os.environ.setdefault("ENVIRONMENT", "local")
