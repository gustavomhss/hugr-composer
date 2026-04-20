"""Pytest conftest — redirects cache out of the primitive directory.

The delivery gate scans every file under the primitive dir; a cache file whose
path contains a dotdir is rejected by the contract. Redirect cache to /tmp.
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
    cache._cachedir = out  # type: ignore[attr-defined] — the contract permits private-attribute access in conftest hygiene hooks.


_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
