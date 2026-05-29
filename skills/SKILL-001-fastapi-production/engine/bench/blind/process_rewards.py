"""Per-turn reward computation for PRM / process-reward-model training.

For each workdir snapshot captured by the ClaudeCliAdapter, extract it
into a scratch directory and run the spec's Layer-A functional suite
only (cheapest signal that still requires a real boot). The delta in
score between consecutive snapshots becomes the turn-level reward.

Design choices
  - Layer A only. Property/concurrency/chaos are too slow to re-run per
    snapshot; they only run in the final judge pass. Layer A is enough
    to signal "this turn broke something that previously worked" or
    "this turn made a smoke test pass for the first time".
  - Opt-in via `--compute-process-rewards`. Default off because it
    multiplies the judge cost by O(n_turns).
  - Emits `process_rewards.jsonl` per attempt. Each record:
        {"turn": 5, "score_before": 25.0, "score_after": 50.0,
         "reward": 25.0, "layer_a_passed": 4, "layer_a_total": 5,
         "snapshot": "turn_005.tar.zst"}
  - Skipped turns (no snapshot taken because the turn didn't write files)
    carry no reward.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from engine.bench.blind.judge import _ChaosWriter, _parse_pytest_json
from engine.bench.blind.spec import Spec


def _extract_snapshot(archive: Path, out_dir: Path) -> Path | None:
    """Extract tar.zst or tar.gz to out_dir; return the workdir path inside."""
    out_dir.mkdir(parents=True, exist_ok=True)
    if archive.suffix == ".zst":
        try:
            import zstandard
        except ImportError:
            return None
        dctx = zstandard.ZstdDecompressor()
        with archive.open("rb") as fh, dctx.stream_reader(fh) as reader:
            with tarfile.open(fileobj=reader, mode="r|") as tar:
                tar.extractall(out_dir, filter="data")
    elif archive.suffixes[-2:] == [".tar", ".gz"]:
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(out_dir, filter="data")
    else:
        return None
    # The archive stored workdir with its own name at the top — find it.
    entries = [p for p in out_dir.iterdir() if p.is_dir()]
    return entries[0] if entries else None


def _score_snapshot_layer_a(
    spec: Spec,
    workdir: Path,
    chaos: _ChaosWriter | None = None,
) -> tuple[int, int]:
    """Boot the workdir and run only Layer-A tests. Returns (passed, total)."""

    from engine.bench.blind.judge import _free_port, _kill, _wait_for_health

    # Copy only Layer-A test files to a scratch judge dir.
    layer_a_dir = workdir.parent / "_pr_layer_a"
    if layer_a_dir.exists():
        shutil.rmtree(layer_a_dir)
    layer_a_dir.mkdir(parents=True)
    copied = 0
    for test_file in spec.judge_dir.glob("test_A_*.py"):
        shutil.copy(test_file, layer_a_dir / test_file.name)
        copied += 1
    conftest = spec.judge_dir / "conftest.py"
    if conftest.exists():
        shutil.copy(conftest, layer_a_dir / "conftest.py")
    if copied == 0:
        return (0, 0)

    port = _free_port()
    boot_cmd = spec.boot_command.replace("{PORT}", str(port)).replace("{PYTHON}", sys.executable)
    if boot_cmd.startswith("python "):
        boot_cmd = sys.executable + boot_cmd[len("python") :]

    env = {**__import__("os").environ, "PORT": str(port)}
    boot_log = workdir.parent / "_pr_boot_log.txt"
    try:
        with boot_log.open("w") as log:
            proc = subprocess.Popen(
                boot_cmd,
                shell=True,
                cwd=workdir,
                stdout=log,
                stderr=log,
                preexec_fn=getattr(__import__("os"), "setsid", None),
                env=env,
            )
    except OSError:
        return (0, 0)

    # Smaller boot window — if the snapshot doesn't even boot, reward 0.
    ok, _ = _wait_for_health(f"http://127.0.0.1:{port}{spec.health_probe}", timeout_s=15)
    if not ok:
        _kill(proc)
        if chaos:
            chaos.event("pr_boot_fail", port=port)
        return (0, 0)

    report = workdir.parent / "_pr_report.json"
    try:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                str(layer_a_dir),
                "-q",
                "--tb=no",
                "--no-header",
                "--json-report",
                f"--json-report-file={report}",
                "--json-report-omit=collectors,log,keywords",
            ],
            capture_output=True,
            text=True,
            check=False,
            cwd=workdir,
            timeout=30,
            env={
                **env,
                "BLIND_BASE_URL": f"http://127.0.0.1:{port}",
                "BLIND_EMITTED_DIR": str(workdir),
            },
        )
    except subprocess.TimeoutExpired:
        _kill(proc)
        return (0, 0)
    finally:
        _kill(proc)

    records = _parse_pytest_json(report, "")
    passed = sum(1 for r in records if r.outcome == "pass" and r.layer == "A")
    total = sum(1 for r in records if r.outcome in ("pass", "fail", "error") and r.layer == "A")
    return (passed, total)


def compute(spec: Spec, attempt_dir: Path) -> list[dict]:
    """Walk file_snapshots/turn_*.tar.{zst,gz} in order and compute deltas.

    Returns a list of process-reward records AND writes them to
    `<attempt_dir>/process_rewards.jsonl`.
    """
    snapshots_dir = attempt_dir / "file_snapshots"
    if not snapshots_dir.exists():
        return []
    archives = sorted(
        [
            p
            for p in snapshots_dir.iterdir()
            if p.name.startswith("turn_") and p.suffix in (".zst", ".gz")
        ],
        key=lambda p: p.name,
    )
    if not archives:
        return []

    chaos_log = attempt_dir / "judge" / "chaos_log.jsonl"
    chaos = _ChaosWriter(chaos_log) if not chaos_log.exists() else None

    prev_score = 0.0
    records: list[dict] = []
    for archive in archives:
        turn = int(archive.stem.split("_")[1])
        with tempfile.TemporaryDirectory(prefix="pr_extract_") as tmp:
            wd = _extract_snapshot(archive, Path(tmp))
            if wd is None:
                continue
            passed, total = _score_snapshot_layer_a(spec, wd, chaos)
        score_after = 100.0 * passed / total if total else 0.0
        reward = score_after - prev_score
        records.append(
            {
                "turn": turn,
                "score_before": round(prev_score, 2),
                "score_after": round(score_after, 2),
                "reward": round(reward, 2),
                "layer_a_passed": passed,
                "layer_a_total": total,
                "snapshot": archive.name,
            }
        )
        prev_score = score_after

    out = attempt_dir / "process_rewards.jsonl"
    out.write_text("\n".join(json.dumps(r) for r in records) + ("\n" if records else ""))
    return records
