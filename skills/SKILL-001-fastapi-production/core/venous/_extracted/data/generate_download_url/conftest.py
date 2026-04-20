"""Conftest for extracted primitive — hypothesis DB redirect + pytest cache."""
from __future__ import annotations

import os
import tempfile

from hypothesis import settings
from hypothesis.database import DirectoryBasedExampleDatabase

_HYP_DIR = tempfile.mkdtemp(prefix="hypothesis_")
os.environ.setdefault("HYPOTHESIS_STORAGE_DIRECTORY", _HYP_DIR)
settings.register_profile(
    "venous",
    database=DirectoryBasedExampleDatabase(_HYP_DIR),
    deadline=None,
)
settings.load_profile("venous")
