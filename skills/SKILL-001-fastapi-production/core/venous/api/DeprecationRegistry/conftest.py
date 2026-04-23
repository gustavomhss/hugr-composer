"""Pytest conftest — sys.path + hypothesis DB redirect out of primitive dir.

Injects BOTH the Registry's own directory AND its DeprecationEntry
dependency's directory onto sys.path so the registry's ``from
DeprecationEntry import ...`` fallback path resolves when tests run
from this directory.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest


def pytest_configure(config: pytest.Config) -> None:
    out = Path(tempfile.gettempdir()) / f"pytest_cache_{os.getpid()}"
    out.mkdir(parents=True, exist_ok=True)
    cache = config.cache
    cache._cachedir = out  # type: ignore[attr-defined]


_HERE = Path(os.path.abspath(__file__)).parent
for p in (_HERE, _HERE.parent / "DeprecationEntry"):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)

_HYP_DIR = Path(tempfile.gettempdir()) / f"hypothesis_db_{os.getpid()}"
os.environ.setdefault("HYPOTHESIS_STORAGE_DIRECTORY", str(_HYP_DIR))
try:
    from hypothesis import settings as _hyp_settings
    from hypothesis.database import DirectoryBasedExampleDatabase as _HypDB

    _HYP_DIR.mkdir(parents=True, exist_ok=True)
    _hyp_settings.register_profile(
        "no_repo_cache",
        database=_HypDB(str(_HYP_DIR)),
        deadline=None,
    )
    _hyp_settings.load_profile("no_repo_cache")
except ImportError:
    pass
