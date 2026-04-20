"""Self-contained HTML dashboard from `results/<run_id>/aggregate.json`.

Writes `<run_dir>/dashboard.html` — pure static, no build step, no
external CDN. Open in a browser or host on GitHub Pages / any static
host. Every number links back to the raw JSON under the same run_dir
so a reviewer can audit the source.
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[3]
RESULTS_ROOT = SKILL_ROOT / "benchmarks" / "blind" / "results"


_CSS = """
:root { --fg:#111; --muted:#666; --accent:#0b5fff; --bg:#fff; --ok:#0a7; --warn:#c70; --bad:#c33; --code:#f5f5f7; }
* { box-sizing: border-box; }
body { font: 14px/1.5 -apple-system, "Segoe UI", Inter, Roboto, sans-serif; color: var(--fg); background: var(--bg); margin: 0; }
.wrap { max-width: 1040px; margin: 0 auto; padding: 28px 20px 80px; }
h1 { font-size: 24px; margin: 0 0 8px; }
h2 { font-size: 18px; margin: 28px 0 8px; border-bottom: 1px solid #eee; padding-bottom: 4px; }
.meta { color: var(--muted); font-size: 12px; margin: 0 0 20px; }
.big { font-size: 28px; font-weight: 600; }
.card { border: 1px solid #e8e8e8; border-radius: 8px; padding: 16px 20px; background: #fafafa; margin-bottom: 14px; }
.ok { color: var(--ok); }
.bad { color: var(--bad); }
.warn { color: var(--warn); }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
table { width: 100%; border-collapse: collapse; margin: 10px 0 18px; font-size: 13px; }
th, td { padding: 6px 10px; border-bottom: 1px solid #eee; text-align: left; }
th { background: #fafafa; font-weight: 600; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
.bar { display: inline-block; height: 9px; background: var(--accent); border-radius: 2px; vertical-align: middle; }
.bar.naked { background: var(--bad); }
.bar.kit   { background: var(--ok); }
.bar-wrap { width: 200px; display: inline-block; background: #eee; border-radius: 2px; vertical-align: middle; }
.margin { padding: 2px 8px; border-radius: 10px; font-weight: 600; }
.margin.pos { background: #e5f6ee; color: var(--ok); }
.margin.neg { background: #fde7e7; color: var(--bad); }
code { background: var(--code); padding: 1px 5px; border-radius: 3px; font: 12px ui-monospace, Menlo, monospace; }
details { margin: 6px 0; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
"""


def _bar(pct: float, kind: str = "") -> str:
    pct = max(0.0, min(100.0, float(pct)))
    return (
        f'<span class="bar-wrap"><span class="bar {kind}" '
        f'style="width: {pct:.0f}%"></span></span>'
    )


def _render_overall(ov: dict) -> str:
    return (
        f'<div class="card"><div class="big">{ov.get("mean_score", 0):.2f}</div>'
        f'<div class="meta">mean score across {ov.get("runs", 0)} runs · '
        f'min {ov.get("min_score", 0):.2f} / max {ov.get("max_score", 0):.2f} · '
        f'stdev {ov.get("stdev_score", 0):.2f}</div></div>'
    )


def _render_hypothesis(h: dict) -> str:
    h1 = "ok" if h.get("H1_supported") else "bad"
    h2 = "ok" if h.get("H2_supported") else "bad"
    return f"""<div class="card">
<b>Pre-registered hypothesis (PROTOCOL §1)</b><br>
<span class="{h1}">H1 hard-tier mean gap</span>:
  {h.get('H1_hard_tier_gap_mean', 0):.2f} pts
  (threshold {h.get('H1_threshold', 25)} → <b class="{h1}">{'supported' if h.get('H1_supported') else 'NOT supported'}</b>)
<br>
<span class="{h2}">H2 impossible-tier ceiling gap</span>:
  {h.get('H2_impossible_tier_ceiling_gap', 0):.2f} pts
  (threshold {h.get('H2_threshold', 30)} → <b class="{h2}">{'supported' if h.get('H2_supported') else 'NOT supported'}</b>)
</div>"""


def _render_by_tier(by_tier: dict) -> str:
    rows: list[str] = []
    for tier in ("calibration", "hard", "impossible"):
        t = by_tier.get(tier)
        if not t:
            continue
        naked = t.get("naked", {})
        kit = t.get("kit", {})
        margin = round(kit.get("mean", 0) - naked.get("mean", 0), 2)
        mclass = "pos" if margin >= 0 else "neg"
        rows.append(
            f"<tr><td><b>{html.escape(tier)}</b></td>"
            f"<td class=num>{naked.get('mean', 0):.2f} {_bar(naked.get('mean', 0), 'naked')}</td>"
            f"<td class=num>{kit.get('mean', 0):.2f} {_bar(kit.get('mean', 0), 'kit')}</td>"
            f"<td class=num><span class='margin {mclass}'>{margin:+.2f}</span></td>"
            f"<td class=num>{naked.get('n', 0)}/{kit.get('n', 0)}</td></tr>"
        )
    if not rows:
        return "<p class=meta>no tier data</p>"
    return (
        "<table><thead><tr><th>Tier</th><th>naked mean</th>"
        "<th>kit mean</th><th>margin</th><th>n (naked/kit)</th></tr></thead>"
        "<tbody>" + "".join(rows) + "</tbody></table>"
    )


def _render_by_spec(by_spec: dict) -> str:
    rows: list[str] = []
    for spec_id, data in sorted(by_spec.items()):
        bc = data.get("by_condition", {})
        naked_mean = bc.get("naked", {}).get("mean", 0)
        kit_mean = bc.get("kit", {}).get("mean", 0)
        margin = data.get("margin_kit_minus_naked") or 0
        mclass = "pos" if margin >= 0 else "neg"
        rows.append(
            f"<tr><td><code>{html.escape(spec_id)}</code></td>"
            f"<td class=num>{naked_mean:.2f}</td>"
            f"<td class=num>{kit_mean:.2f}</td>"
            f"<td class=num><span class='margin {mclass}'>{margin:+.2f}</span></td>"
            f"<td class=num>{data.get('runs', 0)}</td></tr>"
        )
    return (
        "<table><thead><tr><th>Spec</th><th>naked</th><th>kit</th>"
        "<th>margin</th><th>runs</th></tr></thead>"
        "<tbody>" + "".join(rows) + "</tbody></table>"
    )


def _render_efficiency(by_cond: dict) -> str:
    rows: list[str] = []
    for cond in ("naked", "kit"):
        d = by_cond.get(cond, {})
        tokens_pp = d.get("tokens_per_pass")
        tp_str = f"{tokens_pp:,.0f}" if tokens_pp else "—"
        rows.append(
            f"<tr><td><b>{cond}</b></td>"
            f"<td class=num>{d.get('n', 0)}</td>"
            f"<td class=num>{d.get('mean', 0):.2f}</td>"
            f"<td class=num>{d.get('total_tokens', 0):,}</td>"
            f"<td class=num>{tp_str}</td></tr>"
        )
    return (
        "<table><thead><tr><th>Condition</th><th>n</th><th>mean</th>"
        "<th>total tokens</th><th>tokens/pass</th></tr></thead>"
        "<tbody>" + "".join(rows) + "</tbody></table>"
    )


def render_html(aggregate: dict, run_id: str) -> str:
    title = f"Blind Benchmark — {run_id}"
    return f"""<!doctype html><html lang=en><head>
<meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<style>{_CSS}</style>
</head><body><div class=wrap>
<h1>{html.escape(title)}</h1>
<p class=meta>
kit {html.escape(aggregate.get("kit_commit", "?"))} ·
harness v{html.escape(aggregate.get("harness_version", "?"))} ·
generated {html.escape(aggregate.get("generated_at", "?"))} ·
<a href="aggregate.json">aggregate.json</a> ·
<a href="pairs.jsonl">pairs.jsonl</a> ·
<a href="MANIFEST.json">manifest</a>
</p>

<h2>Overall</h2>
{_render_overall(aggregate.get("overall", {}))}
{_render_hypothesis(aggregate.get("hypothesis_test", {}))}

<h2>By tier</h2>
{_render_by_tier(aggregate.get("by_tier", {}))}

<h2>Efficiency (tokens / pass)</h2>
{_render_efficiency(aggregate.get("by_condition", {}))}

<h2>By spec</h2>
{_render_by_spec(aggregate.get("by_spec", {}))}

<p class=meta>Every number above is machine-derived from <code>aggregate.json</code>;
no number shown here is hand-authored. Reproduce with
<code>python -m engine.bench.blind.dashboard --run {html.escape(run_id)}</code>.</p>

</div></body></html>
"""


def build(run_id: str) -> Path:
    run_dir = RESULTS_ROOT / run_id
    agg = json.loads((run_dir / "aggregate.json").read_text())
    out = run_dir / "dashboard.html"
    out.write_text(render_html(agg, run_id), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=False, default=None,
                        help="run_id under benchmarks/blind/results/")
    parser.add_argument("--latest", action="store_true",
                        help="build dashboard for the most recent run_id")
    args = parser.parse_args(argv)

    if args.latest or not args.run:
        runs = sorted(d.name for d in RESULTS_ROOT.iterdir() if d.is_dir())
        if not runs:
            print("no runs under", RESULTS_ROOT, file=sys.stderr)
            return 2
        run_id = runs[-1]
    else:
        run_id = args.run
    out = build(run_id)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
