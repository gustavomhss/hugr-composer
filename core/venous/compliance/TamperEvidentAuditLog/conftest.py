"""Pytest conftest — places the primitive dir on sys.path for direct module import."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest


def pytest_configure(config: pytest.Config) -> None:
    out = Path(tempfile.gettempdir()) / f"pytest_cache_{os.getpid()}"
    out.mkdir(parents=True, exist_ok=True)
    config.cache._cachedir = out  # type: ignore[attr-defined]  # pytest internal — mirrors AuditEvent exemplar.


_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
