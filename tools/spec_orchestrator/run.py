"""CLI: orchestrate one spec generation with the OBSTINATE 6-call pipeline.

Pipeline:
  1. Generate via 6-call (V3 default)
  2. Run reviewer with SOTA gates
  3. While failing AND budget left:
     a. Group blocking issues by which call (A..F) is responsible
     b. For each failing call, refine with feedback
     c. Escalate model V3 -> R1 on 3rd attempt
     d. Re-review
  4. Side-by-side compare against TOOL-008 gold
  5. SAVE only if all gates pass
  6. If stuck after max retries: save WITH `## NEEDS HUMAN: ...` flag
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from spec_orchestrator.client import call_deepseek
from spec_orchestrator.compare import compare_specs
from spec_orchestrator.multi_call import (
    MultiCallResult,
    generate_six_call,
    refine_section_a,
    refine_section_b,
    refine_section_c,
    refine_section_d,
    refine_section_e,
    refine_section_f,
)
from spec_orchestrator.reviewer import blocking_to_call, review

# ============================================================================
# Section boundary helpers
# ============================================================================
SECTION_BOUNDS = {
    "A": ("# TOOL-", "## 4. Code Examples"),
    "B": ("## 4. Code Examples", "## 5. Quality Standards"),
    "C": ("## 5. Quality Standards", "## 9. User Stories"),
    "D": ("## 9. User Stories", "## 10. Test Plan"),
    "E": ("## 10. Test Plan", "## 11. Interaction Matrix"),
    "F": ("## 11. Interaction Matrix", None),  # to end
}


def _replace_call_section(full_spec: str, call: str, new_content: str) -> str:
    start_marker, end_marker = SECTION_BOUNDS[call]
    start = full_spec.find(start_marker)
    if start < 0:
        return full_spec
    if end_marker is None:
        # Replace from start to end of file
        return full_spec[:start] + new_content.strip() + "\n"
    end = full_spec.find(end_marker, start + 1)
    if end < 0:
        return full_spec[:start] + new_content.strip() + "\n"
    return full_spec[:start] + new_content.strip() + "\n\n---\n\n" + full_spec[end:]


def _build_priors(mc: MultiCallResult, call: str) -> str:
    """Build the prior context for refining `call`."""
    parts = []
    for letter in ("A", "B", "C", "D", "E"):
        if letter == call:
            break
        if letter in mc.sections:
            parts.append(mc.sections[letter])
    return "\n\n---\n\n".join(parts)


# ============================================================================
# Main loop
# ============================================================================
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tool-num", required=True)
    parser.add_argument("--tool-name", required=True)
    parser.add_argument("--brief", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--model", default="deepseek/deepseek-chat")
    parser.add_argument("--temperature", type=float, default=0.3)
    parser.add_argument("--no-save", action="store_true")
    parser.add_argument("--save-on-fail", action="store_true",
                        help="Save with NEEDS HUMAN flags even if gates fail")
    parser.add_argument("--raw-out", type=Path)
    parser.add_argument("--max-retries-per-call", type=int, default=3)
    parser.add_argument("--max-cost", type=float, default=0.50,
                        help="Hard cost cap in USD")
    parser.add_argument("--no-refine", action="store_true")
    args = parser.parse_args()

    if not args.brief.exists():
        print(f"ERROR: brief file not found: {args.brief}", file=sys.stderr)
        return 2

    brief_text = args.brief.read_text()
    print(f"[run] tool=TOOL-{args.tool_num} name={args.tool_name} model={args.model}", flush=True)
    print(f"[run] mode=OBSTINATE 6-call + per-section refinement", flush=True)
    print(f"[run] cap: cost ${args.max_cost} / max retries per call: {args.max_retries_per_call}", flush=True)

    # ========================================================================
    # Step 1: initial generation
    # ========================================================================
    try:
        mc = generate_six_call(
            tool_num=args.tool_num,
            tool_name=args.tool_name,
            brief=brief_text,
            model=args.model,
            temperature=args.temperature,
        )
    except Exception as exc:
        print(f"[run] GENERATION FAILED: {exc}", file=sys.stderr)
        return 3

    print()
    print(f"[run] === 6-call totals ===")
    print(f"[run] elapsed={mc.total_elapsed_seconds:.0f}s "
          f"prompt_tok={mc.total_prompt_tokens} completion_tok={mc.total_completion_tokens} "
          f"cost=${mc.total_cost_usd:.4f}", flush=True)
    print(f"[run] full spec lines={len(mc.full_spec.splitlines())}", flush=True)
    print()

    full_spec = mc.full_spec
    total_cost = mc.total_cost_usd
    refine_cost = 0.0

    def _write_raw(spec_text: str) -> None:
        if not args.raw_out:
            return
        args.raw_out.parent.mkdir(parents=True, exist_ok=True)
        meta = {
            "tool_num": args.tool_num,
            "tool_name": args.tool_name,
            "model": args.model,
            "elapsed_seconds": mc.total_elapsed_seconds,
            "prompt_tokens": mc.total_prompt_tokens,
            "completion_tokens": mc.total_completion_tokens,
            "cost_usd": total_cost,
            "calls": len(mc.calls),
        }
        args.raw_out.write_text(
            "<!--\n" + json.dumps(meta, indent=2) + "\n-->\n\n" + spec_text
        )

    _write_raw(full_spec)

    # ========================================================================
    # Step 2: initial review
    # ========================================================================
    print("[run] === initial review ===")
    rr = review(full_spec)
    print(rr.summary())
    print()

    # ========================================================================
    # Step 3: Obstinate refinement loop
    # ========================================================================
    retries = {letter: 0 for letter in "ABCDEF"}
    stuck_calls: set[str] = set()

    while not rr.passed and not args.no_refine:
        if total_cost >= args.max_cost:
            print(f"[run] COST CAP REACHED ${total_cost:.4f} >= ${args.max_cost}", flush=True)
            break

        # Group blocking issues by call letter
        by_call: dict[str, list[str]] = {}
        unmapped: list[str] = []
        for blocking in rr.blocking_issues:
            call = blocking_to_call(blocking)
            if call is None:
                unmapped.append(blocking)
                continue
            by_call.setdefault(call, []).append(blocking)

        if not by_call:
            print(f"[run] NO REFINEABLE BLOCKING ISSUES (all unmapped: {unmapped})", flush=True)
            break

        # Filter out calls that have exhausted retries
        actionable = {
            c: msgs for c, msgs in by_call.items()
            if retries[c] < args.max_retries_per_call
        }
        for c in by_call:
            if retries[c] >= args.max_retries_per_call:
                stuck_calls.add(c)

        if not actionable:
            print(f"[run] ALL FAILING CALLS HAVE EXHAUSTED RETRIES: {sorted(stuck_calls)}",
                  flush=True)
            break

        # Refine each actionable call (in fixed order so context stays consistent)
        for call_letter in "ABCDEF":
            if call_letter not in actionable:
                continue
            issues = actionable[call_letter]
            attempt = retries[call_letter] + 1
            # Escalate model on 3rd attempt
            model = "deepseek/deepseek-r1" if attempt >= 3 else args.model

            print(f"[run] REFINE call {call_letter} (attempt {attempt}/{args.max_retries_per_call}) "
                  f"model={model}", flush=True)
            for msg in issues:
                print(f"  - {msg}", flush=True)

            feedback = "\n".join(f"- {m}" for m in issues)
            current_section = mc.sections.get(call_letter, "")

            try:
                if call_letter == "A":
                    new_section, refine_res = refine_section_a(
                        tool_num=args.tool_num,
                        tool_name=args.tool_name,
                        brief=brief_text,
                        current_section=current_section,
                        review_feedback=feedback,
                        model=model,
                        temperature=args.temperature,
                    )
                elif call_letter == "B":
                    new_section, refine_res = refine_section_b(
                        tool_num=args.tool_num,
                        tool_name=args.tool_name,
                        brief=brief_text,
                        header=mc.sections.get("A", ""),
                        current_section=current_section,
                        review_feedback=feedback,
                        model=model,
                        temperature=args.temperature,
                    )
                elif call_letter == "C":
                    header_and_code = (
                        mc.sections.get("A", "") + "\n\n---\n\n" + mc.sections.get("B", "")
                    )
                    new_section, refine_res = refine_section_c(
                        tool_num=args.tool_num,
                        tool_name=args.tool_name,
                        brief=brief_text,
                        header_and_code=header_and_code,
                        current_section=current_section,
                        review_feedback=feedback,
                        model=model,
                        temperature=args.temperature,
                    )
                elif call_letter == "D":
                    prior = _build_priors(mc, "D")
                    new_section, refine_res = refine_section_d(
                        tool_num=args.tool_num,
                        tool_name=args.tool_name,
                        brief=brief_text,
                        prior=prior,
                        current_section=current_section,
                        review_feedback=feedback,
                        model=model,
                        temperature=args.temperature,
                    )
                elif call_letter == "E":
                    prior = _build_priors(mc, "E")
                    new_section, refine_res = refine_section_e(
                        tool_num=args.tool_num,
                        tool_name=args.tool_name,
                        brief=brief_text,
                        prior=prior,
                        current_section=current_section,
                        review_feedback=feedback,
                        model=model,
                        temperature=args.temperature,
                    )
                elif call_letter == "F":
                    prior = _build_priors(mc, "F")
                    new_section, refine_res = refine_section_f(
                        tool_num=args.tool_num,
                        tool_name=args.tool_name,
                        brief=brief_text,
                        prior=prior,
                        current_section=current_section,
                        review_feedback=feedback,
                        model=model,
                        temperature=args.temperature,
                    )
                else:
                    continue
            except Exception as exc:
                print(f"[run] REFINE call {call_letter} FAILED: {exc}", file=sys.stderr)
                stuck_calls.add(call_letter)
                retries[call_letter] = args.max_retries_per_call
                continue

            refine_cost += refine_res.cost_usd
            total_cost = mc.total_cost_usd + refine_cost
            print(f"[run] refine {call_letter} done: {refine_res.elapsed_seconds:.0f}s "
                  f"cost=${refine_res.cost_usd:.4f} lines={len(new_section.splitlines())} "
                  f"running_total=${total_cost:.4f}", flush=True)

            mc.sections[call_letter] = new_section
            full_spec = _replace_call_section(full_spec, call_letter, new_section)
            if full_spec.count("```") % 2 == 1:
                full_spec = full_spec.rstrip() + "\n```\n"
            retries[call_letter] += 1

        _write_raw(full_spec)
        print("[run] === re-review after refinement pass ===", flush=True)
        rr = review(full_spec)
        print(rr.summary())
        print()

    # ========================================================================
    # Step 4: Final review + decide outcome
    # ========================================================================
    print("[run] === FINAL REVIEW ===", flush=True)
    rr = review(full_spec)
    print(rr.summary())
    print()

    # ========================================================================
    # Step 5: Side-by-side compare
    # ========================================================================
    tmp_path = Path(f"/tmp/_compare_{args.tool_num}.md")
    tmp_path.write_text(full_spec)
    print("[run] === side-by-side compare against TOOL-008 ===", flush=True)
    print(compare_specs(tmp_path))
    print()

    print(f"[run] TOTAL cost: ${total_cost:.4f}", flush=True)
    print(f"[run] retries used: {retries}", flush=True)
    print(f"[run] stuck calls: {sorted(stuck_calls) if stuck_calls else 'NONE'}", flush=True)
    print()

    # ========================================================================
    # Step 6: Save (or flag NEEDS HUMAN)
    # ========================================================================
    if args.no_save:
        print("[run] --no-save: not writing final file")
        return 0 if rr.passed else 1

    if rr.passed:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(full_spec)
        print(f"[run] ✅ PASSED — wrote {args.out} ({len(full_spec.splitlines())} lines)")
        return 0

    # NOT passed — add NEEDS HUMAN flag at the top
    flag_block = (
        "<!--\n"
        "NEEDS HUMAN REVIEW — these blocking issues remain:\n"
        + "\n".join(f"  - {b}" for b in rr.blocking_issues)
        + f"\n\nStuck calls (max retries reached): {sorted(stuck_calls) if stuck_calls else 'NONE'}\n"
        + f"Total refinement cost: ${total_cost:.4f}\n"
        "-->\n\n"
    )
    flagged_spec = flag_block + full_spec

    if args.save_on_fail:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(flagged_spec)
        print(f"[run] ⚠️  STUCK — wrote {args.out} WITH NEEDS HUMAN flag", file=sys.stderr)
        return 1

    print("[run] BLOCKED: review failed and --save-on-fail not set", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
