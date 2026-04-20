"""Pytest conftest — redirects cache out of the primitive directory.

Hypothesis storage is redirected to /tmp so the delivery contract's dotfile
ban (`.hypothesis/`) cannot fire on a test that happens to persist examples.
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
    cache._cachedir = out  # type: ignore[attr-defined]  # RATE_INV_03 — test harness only.


_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


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
