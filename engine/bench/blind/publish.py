"""Aggregator + fine-tuning-artifact emitter.

Consumes `MANIFEST.json` (written by runner) and produces:

  aggregate.json          — tier × condition scoreboard
  pairs.jsonl             — DPO preference pairs (kit-vs-naked on same spec+seed)
  anti_pairs.jsonl        — cases where naked outscored kit (investigate)
  sft.jsonl               — supervised records from high-scoring runs
  process_rewards.jsonl   — reserved — filled in a follow-up commit once
                            per-turn snapshots land (see PROTOCOL §5)
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path

DPO_MARGIN_THRESHOLD = 10.0  # points — pairs with smaller margins are noise
SFT_MIN_SCORE = 90.0


def aggregate_and_write(run_root: Path, manifest: dict) -> dict:
    per_run = manifest.get("per_run", [])
    by_spec: dict[str, list[dict]] = defaultdict(list)
    for m in per_run:
        by_spec[m["identity"]["spec_id"]].append(m)

    overall = _overall_stats(per_run)
    by_tier = _by_tier_stats(per_run)
    by_condition = _by_condition_stats(per_run)
    by_spec_agg = {sid: _spec_stats(sid, runs) for sid, runs in sorted(by_spec.items())}

    aggregate = {
        "run_id": manifest.get("run_id"),
        "harness_version": manifest.get("harness_version"),
        "kit_commit": manifest.get("kit_commit"),
        "generated_at": manifest.get("generated_at"),
        "overall": overall,
        "by_tier": by_tier,
        "by_condition": by_condition,
        "by_spec": by_spec_agg,
        "hypothesis_test": _pre_registered_hypothesis(by_tier, by_condition),
    }
    (run_root / "aggregate.json").write_text(json.dumps(aggregate, indent=2, sort_keys=False))

    pairs, anti_pairs = _dpo_pairs(run_root, per_run)
    (run_root / "pairs.jsonl").write_text(
        "\n".join(json.dumps(p) for p in pairs) + ("\n" if pairs else "")
    )
    (run_root / "anti_pairs.jsonl").write_text(
        "\n".join(json.dumps(p) for p in anti_pairs) + ("\n" if anti_pairs else "")
    )

    sft = _sft_records(run_root, per_run)
    (run_root / "sft.jsonl").write_text(
        "\n".join(json.dumps(r) for r in sft) + ("\n" if sft else "")
    )
    # Build the HTML dashboard alongside the JSON aggregates so a reviewer
    # can open one file and see the pre-registered hypothesis outcome.
    try:
        from engine.bench.blind.dashboard import render_html

        (run_root / "dashboard.html").write_text(
            render_html(aggregate, run_root.name),
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001
        pass
    return aggregate


def _overall_stats(per_run: list[dict]) -> dict:
    scores = [
        r["outcome"]["final_score"] for r in per_run if r["outcome"]["final_score"] is not None
    ]
    return {
        "runs": len(per_run),
        "mean_score": round(statistics.fmean(scores), 2) if scores else 0.0,
        "stdev_score": round(statistics.pstdev(scores), 2) if len(scores) > 1 else 0.0,
        "max_score": round(max(scores), 2) if scores else 0.0,
        "min_score": round(min(scores), 2) if scores else 0.0,
    }


def _by_tier_stats(per_run: list[dict]) -> dict:
    by: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in per_run:
        tier = r["identity"]["spec_id"].split("/", 1)[0]
        by[tier][r["identity"]["condition"]].append(r["outcome"]["final_score"])
    out: dict = {}
    for tier, by_cond in sorted(by.items()):
        out[tier] = {
            cond: {
                "n": len(ss),
                "mean": round(statistics.fmean(ss), 2) if ss else 0.0,
                "stdev": round(statistics.pstdev(ss), 2) if len(ss) > 1 else 0.0,
                "max": round(max(ss), 2) if ss else 0.0,
            }
            for cond, ss in by_cond.items()
        }
    return out


def _by_condition_stats(per_run: list[dict]) -> dict:
    by: dict[str, list[float]] = defaultdict(list)
    tokens: dict[str, int] = defaultdict(int)
    passes: dict[str, int] = defaultdict(int)
    for r in per_run:
        cond = r["identity"]["condition"]
        by[cond].append(r["outcome"]["final_score"])
        tokens[cond] += int(r["efficiency"]["input_tokens"]) + int(r["efficiency"]["output_tokens"])
        if r["outcome"]["final_score"] >= 50:
            passes[cond] += 1
    out: dict = {}
    for cond, ss in sorted(by.items()):
        out[cond] = {
            "n": len(ss),
            "mean": round(statistics.fmean(ss), 2) if ss else 0.0,
            "stdev": round(statistics.pstdev(ss), 2) if len(ss) > 1 else 0.0,
            "total_tokens": tokens[cond],
            "tokens_per_pass": round(tokens[cond] / passes[cond], 1) if passes[cond] else None,
        }
    return out


def _spec_stats(spec_id: str, runs: list[dict]) -> dict:
    by_cond: dict[str, list[float]] = defaultdict(list)
    for r in runs:
        by_cond[r["identity"]["condition"]].append(r["outcome"]["final_score"])
    return {
        "runs": len(runs),
        "by_condition": {
            c: {
                "mean": round(statistics.fmean(s), 2) if s else 0.0,
                "max": round(max(s), 2) if s else 0.0,
            }
            for c, s in sorted(by_cond.items())
        },
        "margin_kit_minus_naked": _margin(by_cond),
    }


def _margin(by_cond: dict[str, list[float]]) -> float | None:
    if "kit" in by_cond and "naked" in by_cond and by_cond["kit"] and by_cond["naked"]:
        return round(statistics.fmean(by_cond["kit"]) - statistics.fmean(by_cond["naked"]), 2)
    return None


def _pre_registered_hypothesis(by_tier: dict, by_condition: dict) -> dict:
    """Evaluate H1/H2 per PROTOCOL.md §1."""
    hard = by_tier.get("hard", {})
    imp = by_tier.get("impossible", {})
    h1_gap = hard.get("kit", {}).get("mean", 0) - hard.get("naked", {}).get("mean", 0)
    h2_gap = imp.get("kit", {}).get("max", 0) - imp.get("naked", {}).get("max", 0)
    return {
        "H1_hard_tier_gap_mean": round(h1_gap, 2),
        "H1_threshold": 25.0,
        "H1_supported": h1_gap >= 25.0,
        "H2_impossible_tier_ceiling_gap": round(h2_gap, 2),
        "H2_threshold": 30.0,
        "H2_supported": h2_gap >= 30.0,
    }


def _dpo_pairs(run_root: Path, per_run: list[dict]) -> tuple[list[dict], list[dict]]:
    # Group by (spec_id, seed, attempt-within-condition) — pair across conditions.
    by_key: dict[tuple, dict[str, dict]] = defaultdict(dict)
    for r in per_run:
        ident = r["identity"]
        key = (ident["spec_id"], ident["seed"], ident["attempt"])
        by_key[key][ident["condition"]] = r
    pairs: list[dict] = []
    anti: list[dict] = []
    for (spec_id, seed, _attempt), pair in by_key.items():
        if "kit" not in pair or "naked" not in pair:
            continue
        k, n = pair["kit"], pair["naked"]
        ks, ns = k["outcome"]["final_score"], n["outcome"]["final_score"]
        margin = ks - ns
        record = {
            "spec_id": spec_id,
            "seed": seed,
            "chosen": {"condition": "kit", "score": ks, "trajectory": _traj_ref(run_root, k)},
            "rejected": {"condition": "naked", "score": ns, "trajectory": _traj_ref(run_root, n)},
            "margin": round(margin, 2),
            "chosen_metrics": _compact_metrics(k),
            "rejected_metrics": _compact_metrics(n),
        }
        if margin >= DPO_MARGIN_THRESHOLD:
            pairs.append(record)
        elif margin <= -DPO_MARGIN_THRESHOLD:
            # Naked beat kit — investigate, do not use for DPO.
            flipped = dict(record)
            flipped["chosen"], flipped["rejected"] = record["rejected"], record["chosen"]
            flipped["margin"] = -margin
            anti.append(flipped)
    return pairs, anti


def _traj_ref(run_root: Path, m: dict) -> str:
    ident = m["identity"]
    safe = ident["spec_id"].replace("/", "__")
    return f"{safe}/{ident['condition']}/attempt_{ident['attempt']:02d}/trajectory.jsonl"


def _compact_metrics(m: dict) -> dict:
    return {
        "per_layer": m["outcome"]["per_layer"],
        "per_bucket": m["outcome"]["per_bucket"],
        "efficiency": {
            "wall_clock_s": m["efficiency"]["wall_clock_s"],
            "tokens": m["efficiency"]["input_tokens"] + m["efficiency"]["output_tokens"],
        },
        "kit_attribution": {
            "coverage_of_required": m["kit_attribution"]["coverage_of_required"],
            "imported": m["kit_attribution"]["imported"],
        },
    }


def _sft_records(run_root: Path, per_run: list[dict]) -> list[dict]:
    out: list[dict] = []
    for r in per_run:
        if r["outcome"]["final_score"] < SFT_MIN_SCORE:
            continue
        ident = r["identity"]
        safe = ident["spec_id"].replace("/", "__")
        traj = (
            run_root
            / safe
            / ident["condition"]
            / f"attempt_{ident['attempt']:02d}"
            / "trajectory.jsonl"
        )
        if not traj.exists():
            continue
        messages = []
        for line in traj.read_text().splitlines():
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            messages.append(
                {
                    "role": ev.get("role"),
                    "content": ev.get("content"),
                }
            )
        out.append(
            {
                "messages": messages,
                "metadata": {
                    "spec_id": ident["spec_id"],
                    "condition": ident["condition"],
                    "score": r["outcome"]["final_score"],
                    "kit_commit": ident["kit_commit"],
                },
            }
        )
    return out
