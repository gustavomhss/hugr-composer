"""Pytest conftest — redirects caches out of the primitive directory.

The delivery gate scans every file under the primitive dir. A cache file whose
path contains a dotdir (e.g. `.pytest_cache/...` or `.hypothesis/...`) is
rejected by the contract's `FileArtefact.path_is_posix_and_contained`
validator. Redirect pytest cache AND the hypothesis example database to /tmp
before either library writes anything.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest
from hypothesis import settings
from hypothesis.database import DirectoryBasedExampleDatabase

# Hypothesis storage redirect (required for stateful primitives that ship a
# state_machine_ harness — prevents .hypothesis/ dotdir from ending up inside
# the primitive directory where FileArtefact path validation would reject it).
_HYP_DIR = tempfile.mkdtemp(prefix="hypothesis_")
os.environ.setdefault("HYPOTHESIS_STORAGE_DIRECTORY", _HYP_DIR)
settings.register_profile(
    "venous",
    database=DirectoryBasedExampleDatabase(_HYP_DIR),
    deadline=None,
)
settings.load_profile("venous")


def pytest_configure(config: pytest.Config) -> None:
    out = Path(tempfile.gettempdir()) / f"pytest_cache_{os.getpid()}"
    out.mkdir(parents=True, exist_ok=True)
    cache = config.cache
    cache._cachedir = out  # type: ignore[attr-defined] — redirect cache off-tree for FileArtefact contract.


# Ensure the primitive module is importable when pytest is invoked from elsewhere.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
