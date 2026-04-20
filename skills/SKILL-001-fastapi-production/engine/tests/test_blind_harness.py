"""Unit tests for the blind-benchmark harness.

These tests cover the harness modules directly — no LLM calls, no boot.
They run in a couple of seconds and MUST stay green for B3.7 to pass.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.bench.blind.attribution import scan_primitives, attribute
from engine.bench.blind.judge import _classify, _aggregate, _parse_pytest_json, TestRecord
from engine.bench.blind.publish import (
    DPO_MARGIN_THRESHOLD, _margin, _pre_registered_hypothesis,
    _by_tier_stats, _by_condition_stats,
)
from engine.bench.blind.snapshots import snapshot_workdir
from engine.bench.blind.spec import (
    DIFFICULTY_AXES, TIER_PREDICTIONS, discover_specs, load_spec,
    SpecValidationError,
)
from engine.bench.blind.static_scan import run_static_scan


# ---------------------------------------------------------------------------
# spec.py
# ---------------------------------------------------------------------------

def test_spec_loader_accepts_valid_seed_spec() -> None:
    """The one spec we author (hard/01) must validate."""
    root = Path(__file__).resolve().parents[2] / "benchmarks" / "blind" / "specs"
    specs = discover_specs(root)
    assert len(specs) >= 1, f"no specs discovered under {root}"
    s = next(s for s in specs if s.spec_id == "hard/01_financial_ledger")
    assert s.tier == "hard"
    assert s.brief_sha256 and len(s.brief_sha256) == 64
    assert "concurrency" in s.difficulty_axes
    assert TIER_PREDICTIONS["hard"]["naked_min"] <= s.predicted_naked_score <= TIER_PREDICTIONS["hard"]["naked_max"]


def test_spec_loader_rejects_missing_brief(tmp_path: Path) -> None:
    d = tmp_path / "bogus"
    d.mkdir()
    (d / "metadata.json").write_text("{}")
    (d / "judge").mkdir()
    with pytest.raises(SpecValidationError, match="brief.md"):
        load_spec(d)


def test_spec_loader_rejects_unknown_difficulty_axis(tmp_path: Path) -> None:
    d = tmp_path / "bad_axis"
    d.mkdir()
    (d / "brief.md").write_text("# x\n## Requirements\n## Acceptance criteria\n## Non-requirements\n")
    (d / "judge").mkdir()
    (d / "judge" / "test_A.py").write_text("def test_x(): pass")
    (d / "metadata.json").write_text(json.dumps({
        "tier": "hard", "difficulty_axes": ["made_up"],
        "required_primitives": [], "predicted_naked_score": 20,
        "predicted_kit_score": 70, "boot_command": "x", "health_probe": "/",
        "timeout_s": 60, "authored_at": "2026", "author": "t",
    }))
    with pytest.raises(SpecValidationError, match="unknown difficulty_axes"):
        load_spec(d)


def test_spec_loader_rejects_predictions_outside_tier_band(tmp_path: Path) -> None:
    d = tmp_path / "mis_tier"
    d.mkdir()
    (d / "brief.md").write_text("x")
    (d / "judge").mkdir()
    (d / "judge" / "test_A.py").write_text("def test_x(): pass")
    (d / "metadata.json").write_text(json.dumps({
        "tier": "hard", "difficulty_axes": [],
        "required_primitives": [],
        "predicted_naked_score": 90,   # way above hard band max=40
        "predicted_kit_score": 95,
        "boot_command": "x", "health_probe": "/",
        "timeout_s": 60, "authored_at": "2026", "author": "t",
    }))
    with pytest.raises(SpecValidationError, match="out of tier band"):
        load_spec(d)


def test_difficulty_axes_whitelist_covers_expected() -> None:
    for required in ("concurrency", "exactly_once", "causal_order",
                      "multi_invariant", "failure_injection"):
        assert required in DIFFICULTY_AXES


# ---------------------------------------------------------------------------
# judge.py
# ---------------------------------------------------------------------------

def test_judge_classify_extracts_layer_and_bucket() -> None:
    assert _classify("test_A_functional__health_endpoint") == ("A", "functional")
    assert _classify("test_C_concurrency__200_parallel") == ("C", "concurrency")
    assert _classify("test_E_static__no_float") == ("E", "static")


def test_judge_classify_falls_back_on_nonconforming_name() -> None:
    assert _classify("test_something_else") == ("A", "unknown")


def test_judge_aggregate_computes_per_layer_and_bucket() -> None:
    records = [
        TestRecord("t::test_A_functional__a", "pass", "A", "functional", 10),
        TestRecord("t::test_A_functional__b", "fail", "A", "functional", 10),
        TestRecord("t::test_C_concurrency__a", "pass", "C", "concurrency", 100),
        TestRecord("t::test_E_static__a", "pass", "E", "static", 1),
    ]
    result = _aggregate(records, boot_status="success", boot_log_path=None)
    assert result.tests_passed == 3 and result.tests_total == 4
    assert result.final_score == 75.0
    assert result.per_layer["A"] == 50.0
    assert result.per_layer["C"] == 100.0
    assert result.per_bucket["concurrency"] == 100.0


def test_judge_parse_pytest_json_reads_report(tmp_path: Path) -> None:
    report = tmp_path / "r.json"
    report.write_text(json.dumps({
        "tests": [
            {"nodeid": "tests/test_file.py::test_A_functional__x",
             "outcome": "passed", "duration": 0.05},
            {"nodeid": "tests/test_file.py::test_B_property__y",
             "outcome": "failed", "duration": 0.12,
             "call": {"longrepr": "AssertionError: conservation broken"}},
        ],
    }))
    records = _parse_pytest_json(report, "")
    assert len(records) == 2
    assert records[0].outcome == "pass"
    assert records[1].outcome == "fail"
    assert records[1].layer == "B"
    assert "conservation" in records[1].stderr_snippet


# ---------------------------------------------------------------------------
# publish.py
# ---------------------------------------------------------------------------

def _run_record(spec_id: str, condition: str, score: float, seed: int = 7919,
                attempt: int = 1, tokens: int = 1000) -> dict:
    return {
        "identity": {
            "run_id": "x", "spec_id": spec_id, "condition": condition,
            "attempt": attempt, "seed": seed, "model": "m",
            "temperature": 0.7, "kit_commit": "abc", "mcp_config_hash": "h",
            "harness_version": "1.0.0", "brief_sha256": "deadbeef",
        },
        "outcome": {
            "emit_status": "success", "boot_status": "success",
            "final_score": score, "tests_passed": int(score / 10),
            "tests_total": 10, "per_layer": {"A": score}, "per_bucket": {},
            "emit_error": "", "judge_notes": "",
        },
        "efficiency": {
            "wall_clock_s": 100, "input_tokens": tokens,
            "output_tokens": tokens // 2, "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
        },
        "kit_attribution": {"imported": [], "required": [],
                             "coverage_of_required": 0.0,
                             "unexpected_imports": [], "missing_required": []},
        "static_findings": [], "extra": {},
    }


def test_publish_by_tier_stats_splits_kit_naked() -> None:
    runs = [
        _run_record("hard/01_x", "naked", 30.0),
        _run_record("hard/01_x", "kit", 80.0),
        _run_record("hard/02_y", "naked", 20.0),
        _run_record("hard/02_y", "kit", 85.0),
    ]
    stats = _by_tier_stats(runs)
    assert stats["hard"]["naked"]["mean"] == 25.0
    assert stats["hard"]["kit"]["mean"] == 82.5


def test_publish_pre_registered_hypothesis_supported_when_gap_big() -> None:
    by_tier = {"hard": {"naked": {"mean": 30}, "kit": {"mean": 80}}}
    by_condition = {}
    h = _pre_registered_hypothesis(by_tier, by_condition)
    assert h["H1_hard_tier_gap_mean"] == 50.0
    assert h["H1_supported"] is True


def test_publish_pre_registered_hypothesis_not_supported_on_small_gap() -> None:
    by_tier = {"hard": {"naked": {"mean": 50}, "kit": {"mean": 60}}}
    h = _pre_registered_hypothesis(by_tier, {})
    assert h["H1_hard_tier_gap_mean"] == 10.0
    assert h["H1_supported"] is False


def test_publish_by_condition_tokens_per_pass() -> None:
    runs = [
        _run_record("hard/01", "kit", 80.0, tokens=1000),
        _run_record("hard/02", "kit", 30.0, tokens=1500),  # under 50 = not a pass
    ]
    stats = _by_condition_stats(runs)
    assert stats["kit"]["n"] == 2
    # 2 runs, tokens = (1000+500) + (1500+750) = 3750, passes = 1 (score>=50)
    assert stats["kit"]["tokens_per_pass"] == 3750.0


def test_publish_dpo_margin_threshold_constant() -> None:
    # Guard against accidental threshold loosening.
    assert DPO_MARGIN_THRESHOLD == 10.0


# ---------------------------------------------------------------------------
# attribution.py
# ---------------------------------------------------------------------------

def test_attribution_detects_from_imports(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(
        "from core.venous.cache.SessionCache import SessionCache\n"
        "from core.venous.security.SignatureVerifier import SignatureVerifier\n"
    )
    found = scan_primitives(tmp_path)
    assert "SessionCache" in found
    assert "SignatureVerifier" in found


def test_attribution_coverage_math(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text(
        "from core.venous.data.UnitOfWork import UnitOfWork\n"
    )
    result = attribute(tmp_path, required=["UnitOfWork", "OptimisticConcurrency"])
    assert result["coverage_of_required"] == 0.5
    assert "OptimisticConcurrency" in result["missing_required"]


def test_attribution_does_not_match_bare_core_venous(tmp_path: Path) -> None:
    # Accidental `from core.venous import ...` should NOT pull in namespace-level names
    (tmp_path / "a.py").write_text("import os\n")
    assert scan_primitives(tmp_path) == set()


# ---------------------------------------------------------------------------
# static_scan.py
# ---------------------------------------------------------------------------

def test_static_scan_triggers_on_float_call(tmp_path: Path) -> None:
    (tmp_path / "rules.yaml").write_text(
        "rules:\n"
        "  - id: no_float\n"
        "    description: test\n"
        "    severity: fail\n"
        "    scope: 'glob:**/*.py'\n"
        "    pattern_any_of:\n"
        "      - {kind: ast_call_name, name: float}\n"
    )
    (tmp_path / "src.py").write_text("x = float(123)\n")
    findings = run_static_scan(tmp_path, tmp_path / "rules.yaml")
    assert len(findings) == 1
    assert findings[0].verdict == "triggered"


def test_static_scan_clean_when_no_match(tmp_path: Path) -> None:
    (tmp_path / "rules.yaml").write_text(
        "rules:\n"
        "  - id: no_float\n"
        "    description: test\n"
        "    severity: fail\n"
        "    scope: 'glob:**/*.py'\n"
        "    pattern_any_of:\n"
        "      - {kind: ast_call_name, name: float}\n"
    )
    (tmp_path / "src.py").write_text("x = int(123)\n")
    findings = run_static_scan(tmp_path, tmp_path / "rules.yaml")
    assert findings[0].verdict == "clean"


# ---------------------------------------------------------------------------
# snapshots.py
# ---------------------------------------------------------------------------

def test_snapshot_creates_archive(tmp_path: Path) -> None:
    workdir = tmp_path / "emitted"
    workdir.mkdir()
    (workdir / "app.py").write_text("print('hi')\n")
    out_dir = tmp_path / "snaps"
    archive = snapshot_workdir(workdir, out_dir, label="final")
    assert archive.exists()
    assert archive.stat().st_size > 0


def test_snapshot_skips_pycache(tmp_path: Path) -> None:
    workdir = tmp_path / "emitted"
    (workdir / "__pycache__").mkdir(parents=True)
    (workdir / "__pycache__" / "junk.pyc").write_bytes(b"\x00" * 100)
    (workdir / "ok.py").write_text("pass\n")
    out_dir = tmp_path / "snaps"
    archive = snapshot_workdir(workdir, out_dir, label="t")
    import tarfile
    opener = {"tar.zst": "r|", "tar.gz": "r:gz"}
    ext = "tar.zst" if str(archive).endswith(".tar.zst") else "tar.gz"
    if ext == "tar.gz":
        with tarfile.open(archive, "r:gz") as tar:
            names = tar.getnames()
            assert any("ok.py" in n for n in names)
            assert not any("__pycache__" in n for n in names)
