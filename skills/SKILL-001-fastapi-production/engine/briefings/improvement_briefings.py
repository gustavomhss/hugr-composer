"""
Build an improvement briefing for a primitive whose existing manifest failed one
of the live-LLM tiers (T6 adversarial or T9 meta) with substantive feedback.
The briefing injects the judge's specific low-score axes + rationale, or the
successful adversarial attacks, so the next agent can target exactly the gap.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from single_primitive_briefings import SinglePrimitiveBriefing, pending_briefings  # noqa: E402


def render_improvement_prompt(
    briefing: SinglePrimitiveBriefing,
    manifest_path: Path,
) -> str:
    m = json.loads(manifest_path.read_text())
    # Find the failing tier + evidence
    gaps: list[str] = []
    for tr in m.get("tier_reports", []):
        if tr["status"] not in ("failed", "errored"):
            continue
        tier = tr["tier"]
        if tier == "T9_meta":
            ev_path = manifest_path.parent / (tr.get("evidence_path") or "_evidence/t9_meta.json")
            if ev_path.exists():
                ev = json.loads(ev_path.read_text())
                for a in ev.get("judge", {}).get("axes", []):
                    if a["score"] < 8:
                        gaps.append(f"[T9 judge] axis `{a['axis']}` = {a['score']}/10 → {a['rationale']}")
                for r in ev.get("personas", {}).get("reviews", []):
                    if not r.get("understood"):
                        gaps.append(f"[T9 persona] `{r['persona']}` did not understand → friction: {r.get('friction_points')}")
            err = tr.get("error_details") or ""
            gaps.append(f"[T9 contract] {err[:400]}")
        elif tier == "T6_adversarial":
            ev_path = manifest_path.parent / (tr.get("evidence_path") or "_evidence/t6_adversarial.json")
            if ev_path.exists():
                ev = json.loads(ev_path.read_text())
                for a in ev.get("attacks", []):
                    if a.get("defender_outcome") not in ("rejected", "held"):
                        gaps.append(f"[T6 attack succeeded] `{a['attack_id']}` via {a['model']}: {a['hypothesis'][:200]}")
        else:
            gaps.append(f"[{tier} failed] {(tr.get('error_details') or '')[:300]}")

    gap_block = "\n".join(f"  - {g}" for g in gaps) if gaps else "  - (no specific gap surfaced; see manifest)"
    base = briefing.render_prompt()
    prefix = f"""# IMPROVEMENT BRIEFING — {briefing.primitive_name}

A previous build of this primitive FAILED one or more tiers. The artefacts are
already in `{manifest_path.parent}`. Your job is to DIAGNOSE + FIX, not rebuild
from scratch. Preserve what passes, target only the gaps.

## Exact gaps to close
{gap_block}

## Approach
1. Read the existing files in the target dir.
2. Address EACH gap above directly. If the judge flagged `completeness`, add
   the missing behaviour. If `production_readiness`, harden the impl (thread
   safety, resource cleanup, explicit error types). If an adversarial attack
   succeeded, make the corresponding `test_inv_*_prevents` test reproduce the
   attack and add the defense in the impl.
3. Re-run the self-check CLI (see below) until exit 0 + every gap closed.
4. If a gap CANNOT be closed (e.g. judge asks for something out of scope),
   document why in `<Name>.md` under a "Known limitations" section and flag
   in your return summary.

---

"""
    return prefix + base
