"""Performance baseline tests.

These tests lock latency / memory ceilings for hot paths so regressions
surface as test failures instead of silent slowdowns. Numbers are
generous (≥ 2x observed median) to avoid flakiness while still catching
order-of-magnitude regressions.

Measured paths (bounds are the `BOUND_*` constants below —
mirror with the constants, not the docstring; constants win on
drift):

    1. Catalog load + parse                → BOUND_CATALOG_LOAD      (1.0s)
    2. Classifier run over pool            → BOUND_CLASSIFIER_RUN    (60.0s)
    3. Ledger Markdown render              → BOUND_LEDGER_RENDER     (5.0s)
    4. Contract check full run             → BOUND_CONTRACT_CHECK    (90.0s)
    5. Catalog manifest verify idempotent  → BOUND_MANIFEST_VERIFY   (30.0s)

If a real regression surfaces, the remedy is to either
    (a) find the slow path and fix it, OR
    (b) document why the new baseline is acceptable and update the
        ceiling with a commit message citing the rationale.

Bypassing via pytest.mark.skip is forbidden without a CHANGELOG note.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

SKILL_ROOT = Path(__file__).resolve().parents[1]


# Upper bounds (seconds). Calibrated to observed-median × ~1.8 so typical
# CI noise doesn't flap; still tight enough to catch a real regression.
#
# Observed on Apple M2 Pro, Python 3.14, warm filesystem (Nov 2026):
#   catalog load       ≈ 0.02s
#   classifier run     ≈ 17s
#   ledger render      ≈ 0.5s
#   contract check     ≈ 38s   (B1.6 orphan-generator scan dominates)
#   manifest verify    ≈ 6s
#
# Known optimisation opportunity: CONTRACT §B1.6 can be sped up to
# < 5s with a single-pass AST scan over `generators/` — tracked for
# v1.1 post-release.
BOUND_CATALOG_LOAD = 1.0
BOUND_CLASSIFIER_RUN = 60.0
BOUND_LEDGER_RENDER = 5.0
BOUND_CONTRACT_CHECK = 90.0
BOUND_MANIFEST_VERIFY = 30.0


def _python_bin() -> str:
    """Prefer the skill's venv python; fall back to the current interpreter."""
    venv_py = SKILL_ROOT / ".venv" / "bin" / "python"
    return str(venv_py) if venv_py.exists() else sys.executable


def _time_subprocess(cmd: list[str]) -> float:
    """Return wall-clock seconds. Fails the test if the subprocess errored.

    Inherits the current env (HOME, LANG, etc.) and overrides PYTHONPATH
    so imports resolve against the skill tree. Minimal-env attempts
    caused 20-50x slowdowns on some systems — inheriting is safer here.
    """
    import os

    env = {**os.environ, "PYTHONPATH": str(SKILL_ROOT)}
    start = time.monotonic()
    r = subprocess.run(
        cmd, cwd=str(SKILL_ROOT), capture_output=True, text=True, env=env
    )
    elapsed = time.monotonic() - start
    if r.returncode != 0:
        pytest.fail(
            f"subprocess failed ({r.returncode}):\n"
            f"cmd={cmd}\nstdout={r.stdout[-2000:]}\nstderr={r.stderr[-2000:]}"
        )
    return elapsed


def test_catalog_load_under_bound():
    """Reading + JSON-parsing catalog.json is sub-second."""
    catalog_path = SKILL_ROOT / "engine" / "index" / "catalog.json"
    assert catalog_path.exists(), "catalog missing — run `engine.index.manifest build`"
    start = time.monotonic()
    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    elapsed = time.monotonic() - start
    assert "tools" in data, "malformed catalog"
    assert elapsed < BOUND_CATALOG_LOAD, (
        f"catalog load took {elapsed:.3f}s (bound {BOUND_CATALOG_LOAD}s). "
        "Investigate parser / file growth."
    )


def test_classifier_run_under_bound():
    """Full ledger regeneration over the staged pool stays under the ceiling."""
    elapsed = _time_subprocess(
        [_python_bin(), "-m", "engine.promotion.classify"]
    )
    assert elapsed < BOUND_CLASSIFIER_RUN, (
        f"classify took {elapsed:.3f}s (bound {BOUND_CLASSIFIER_RUN}s). "
        "Investigate signal scan or measurement hot path."
    )


def test_ledger_render_under_bound():
    """Markdown render from ledger.json."""
    elapsed = _time_subprocess(
        [_python_bin(), "-m", "engine.promotion.ledger"]
    )
    assert elapsed < BOUND_LEDGER_RENDER, (
        f"ledger render took {elapsed:.3f}s (bound {BOUND_LEDGER_RENDER}s)."
    )


def test_contract_check_under_bound():
    """Full contract-check harness run (all rules in RULES tuple)."""
    elapsed = _time_subprocess(
        [_python_bin(), "-m", "engine.audit.contract_check"]
    )
    assert elapsed < BOUND_CONTRACT_CHECK, (
        f"contract_check took {elapsed:.3f}s (bound {BOUND_CONTRACT_CHECK}s). "
        "A new rule may have introduced a slow path."
    )


def test_manifest_verify_under_bound():
    """Two full catalog builds (verify mode) complete within bound."""
    elapsed = _time_subprocess(
        [_python_bin(), "-m", "engine.index.manifest", "verify"]
    )
    assert elapsed < BOUND_MANIFEST_VERIFY, (
        f"manifest verify took {elapsed:.3f}s (bound {BOUND_MANIFEST_VERIFY}s). "
        "Catalog-scan hot path may have regressed."
    )
