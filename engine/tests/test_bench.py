"""Unit tests for CONTRACT §B3.1-B3.3 — specs, rubric, runner."""
from __future__ import annotations

from pathlib import Path

import pytest

from engine.bench import BenchmarkRunner, score_spec
from engine.bench.runner import SPECS_ROOT, StubMaestro, _discover_specs


# ---------------------------------------------------------------- B3.1 specs

def test_twenty_specs_exist() -> None:
    specs = _discover_specs()
    assert len(specs) == 20, f"expected 20 specs, got {len(specs)}"


def test_tier_counts_match_contract() -> None:
    counts: dict[str, int] = {}
    for p in _discover_specs():
        counts[p.parent.name] = counts.get(p.parent.name, 0) + 1
    assert counts == {"baseline": 5, "mid": 10, "adversarial": 5}


def test_each_spec_has_required_sections() -> None:
    required = ("## Requirements", "## Acceptance criteria", "## Non-requirements")
    missing: list[str] = []
    for p in _discover_specs():
        txt = p.read_text(encoding="utf-8")
        for section in required:
            if section not in txt:
                missing.append(f"{p.relative_to(SPECS_ROOT)} missing {section}")
    assert not missing, missing


def test_specs_contain_no_tool_or_primitive_hints() -> None:
    """CONTRACT §B3.1 Invariant: specs are plain English, no tool/primitive
    names leak. Heuristic: forbid exact-match registry primitive names."""
    import yaml

    registry = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "primitives_by_concern.yaml").read_text()
    )
    forbidden = {p["name"] for p in registry["primitives"]}
    # Plus the obvious "add_*" tool prefix.
    leaks: list[str] = []
    for p in _discover_specs():
        txt = p.read_text(encoding="utf-8")
        for name in forbidden:
            if name in txt:
                leaks.append(f"{p.name}: leaks {name}")
        if "add_" in txt:
            leaks.append(f"{p.name}: contains 'add_' token")
    assert not leaks, leaks[:10]


# ---------------------------------------------------------------- B3.2 rubric

def test_score_spec_weights_are_equal() -> None:
    s = score_spec(
        "test/x", "baseline",
        scaffold_completeness=100, test_suite_pass=0,
        primitive_gate_pass=100, hand_editability=0,
    )
    # 100 + 0 + 100 + 0 = 200 * 0.25 = 50
    assert s.total == 50.0


def test_score_spec_clamps_to_range() -> None:
    s = score_spec(
        "test/y", "baseline",
        scaffold_completeness=150, test_suite_pass=-10,
        primitive_gate_pass=200, hand_editability=99,
    )
    assert s.dimensions[0].value == 100
    assert s.dimensions[1].value == 0
    assert s.dimensions[2].value == 100
    assert s.dimensions[3].value == 99


def test_score_spec_includes_evidence() -> None:
    s = score_spec(
        "test/z", "mid",
        scaffold_completeness=80, test_suite_pass=70,
        primitive_gate_pass=90, hand_editability=75,
        evidence={"scaffold_completeness": "all 5 endpoints present"},
    )
    assert s.dimensions[0].evidence == "all 5 endpoints present"


# ---------------------------------------------------------------- B3.3 runner

def test_runner_with_stub_maestro_produces_full_report(tmp_path: Path) -> None:
    stub = StubMaestro(scoreboard={"baseline/01_crud_todos": 80.0, "mid/02_realtime_chat": 50.0})
    runner = BenchmarkRunner(adapter=stub, workdir=tmp_path)
    report = runner.run_all(kit_version="test-rev")

    assert len(report.scores) == 20
    assert report.maestro_model == "stub"
    assert report.kit_version == "test-rev"
    # two scored specs, 18 at zero
    scored = {s.spec_id: s.total for s in report.scores}
    assert scored["baseline/01_crud_todos"] == 80.0
    assert scored["mid/02_realtime_chat"] == 50.0
    assert scored["adversarial/05_hidden_scaling_innocent_counter"] == 0.0


def test_runner_aggregates_by_tier(tmp_path: Path) -> None:
    stub = StubMaestro(scoreboard={
        "baseline/01_crud_todos": 100,
        "baseline/02_auth_only_saas": 100,
        "baseline/03_webhook_sink": 100,
        "baseline/04_rate_limited_api": 100,
        "baseline/05_multi_tenant_admin": 100,
    })
    runner = BenchmarkRunner(adapter=stub, workdir=tmp_path)
    report = runner.run_all(kit_version="t")
    by_tier = report.by_tier()
    assert by_tier["baseline"] == 100.0
    assert by_tier["mid"] == 0.0
    assert by_tier["adversarial"] == 0.0
    # 5*100 + 15*0 = 500; 500/20 = 25
    assert report.overall == 25.0


def test_report_writes_json_roundtrip(tmp_path: Path) -> None:
    stub = StubMaestro(scoreboard={"baseline/01_crud_todos": 42})
    runner = BenchmarkRunner(adapter=stub, workdir=tmp_path)
    report = runner.run_all(kit_version="rev")
    out = tmp_path / "score.json"
    report.write_json(out)
    import json
    loaded = json.loads(out.read_text())
    assert loaded["maestro_model"] == "stub"
    assert loaded["kit_version"] == "rev"
    assert any(s["spec_id"] == "baseline/01_crud_todos" and s["total"] == 42.0 for s in loaded["scores"])


@pytest.mark.parametrize("tier", ["baseline", "mid", "adversarial"])
def test_every_tier_has_specs_runner_sees(tier: str) -> None:
    specs = [p for p in _discover_specs() if p.parent.name == tier]
    assert specs, f"tier {tier} has no specs visible to runner"
