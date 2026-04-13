"""Side-by-side comparison of a generated spec against a gold reference (TOOL-008)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLD_TOOL_008 = REPO_ROOT / "docs/skills_library/skills/SKILL-001-fastapi-production/specs/TOOL-008-add_multi_tenancy.md"

SECTIONS = [
    ("1. Overview", "## 1. Overview", "## 2."),
    ("2. Purpose", "## 2. Purpose", "## 3."),
    ("3. SLOs", "## 3. Performance SLOs", "## 4."),
    ("4. Code Examples", "## 4. Code Examples", "## 5."),
    ("5. Quality Standards", "## 5. Quality Standards", "## 6."),
    ("6. Completeness Criteria", "## 6. Completeness Criteria", "## 7."),
    ("7. DoD", "## 7. Definition of Done", "## 8."),
    ("8. Invariants", "## 8. Invariants", "## 9."),
    ("9. User Stories", "## 9. User Stories", "## 10."),
    ("10. Test Plan", "## 10. Test Plan", "## 11."),
    ("11. Interaction Matrix", "## 11. Interaction Matrix", "## 12."),
    ("12. Rollback", "## 12. Rollback Procedure", "## 13."),
    ("13. Edge Cases", "## 13. Edge Cases", "## 14."),
    ("14. Acceptance", "## 14. Acceptance Criteria", "## 15."),
    ("15. Checklist", "## 15. Implementation Checklist", "## 16."),
    ("16. Doc Output", "## 16. Documentation Output", "<EOF>"),
]


@dataclass
class SectionStats:
    name: str
    line_count: int
    char_count: int
    code_blocks: int
    table_rows: int
    bullet_items: int
    checkbox_items: int


def _extract(content: str, start: str, end: str) -> str:
    s = content.find(start)
    if s < 0:
        return ""
    if end == "<EOF>":
        return content[s:]
    e = content.find(end, s + 1)
    return content[s:e] if e > 0 else content[s:]


def _stats(name: str, section_content: str) -> SectionStats:
    code_blocks = len(re.findall(r"```", section_content)) // 2
    table_rows = sum(
        1 for line in section_content.splitlines()
        if line.startswith("|") and not re.match(r"^\|[\s\-:|]+$", line)
    )
    bullet_items = len(re.findall(r"^- (?!\[)", section_content, re.MULTILINE))
    checkbox_items = len(re.findall(r"^- \[ \]", section_content, re.MULTILINE))
    return SectionStats(
        name=name,
        line_count=section_content.count("\n"),
        char_count=len(section_content),
        code_blocks=code_blocks,
        table_rows=max(0, table_rows - 1),  # subtract header row
        bullet_items=bullet_items,
        checkbox_items=checkbox_items,
    )


def compare_specs(generated_path: Path, gold_path: Path = GOLD_TOOL_008) -> str:
    """Returns a side-by-side text report."""
    if not generated_path.exists():
        return f"ERROR: generated spec not found: {generated_path}"
    if not gold_path.exists():
        return f"ERROR: gold spec not found: {gold_path}"

    gen = generated_path.read_text()
    gold = gold_path.read_text()

    out = []
    out.append("=" * 92)
    out.append(f"SIDE-BY-SIDE: {generated_path.name}  vs  GOLD ({gold_path.name})")
    out.append("=" * 92)
    out.append(
        f"{'TOTAL LINES':<27} {'gen':>12} {'gold':>12} {'ratio':>10}  {'verdict':<20}"
    )
    out.append("-" * 92)

    gen_total = len(gen.splitlines())
    gold_total = len(gold.splitlines())
    ratio = gen_total / max(gold_total, 1)
    verdict = _verdict(ratio, target_min=0.85)
    out.append(
        f"{'(full document)':<27} {gen_total:>12} {gold_total:>12} {ratio:>10.2f}  {verdict:<20}"
    )
    out.append("")
    out.append(f"{'SECTION':<27} {'gen lines':>12} {'gold lines':>12} {'ratio':>10}  {'verdict':<20}")
    out.append("-" * 92)

    for name, start, end in SECTIONS:
        gen_sec = _extract(gen, start, end)
        gold_sec = _extract(gold, start, end)
        gs = _stats(name, gen_sec)
        gold_s = _stats(name, gold_sec)
        if gold_s.line_count == 0:
            ratio_text = "N/A"
            verdict = "N/A"
        else:
            r = gs.line_count / gold_s.line_count
            ratio_text = f"{r:.2f}"
            verdict = _verdict(r, target_min=0.75)
        out.append(
            f"{name:<27} {gs.line_count:>12} {gold_s.line_count:>12} {ratio_text:>10}  {verdict:<20}"
        )

    # Detailed diff: code blocks, table rows, checkbox items per section
    out.append("")
    out.append("DETAILED COUNTS (gen vs gold):")
    out.append(
        f"{'SECTION':<27} {'code':>12} {'tbl-rows':>12} {'bullets':>12} {'checkbox':>12}"
    )
    out.append("-" * 80)
    for name, start, end in SECTIONS:
        gen_sec = _extract(gen, start, end)
        gold_sec = _extract(gold, start, end)
        gs = _stats(name, gen_sec)
        gold_s = _stats(name, gold_sec)
        out.append(
            f"{name:<27} "
            f"{f'{gs.code_blocks}/{gold_s.code_blocks}':>12} "
            f"{f'{gs.table_rows}/{gold_s.table_rows}':>12} "
            f"{f'{gs.bullet_items}/{gold_s.bullet_items}':>12} "
            f"{f'{gs.checkbox_items}/{gold_s.checkbox_items}':>12} "
        )

    return "\n".join(out)


def _verdict(ratio: float, target_min: float) -> str:
    if ratio >= 1.0:
        return "✓ matches/exceeds"
    if ratio >= target_min:
        return "≈ acceptable"
    if ratio >= 0.6:
        return "⚠ THIN"
    return "✗ TOO THIN"


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m spec_orchestrator.compare <generated_spec_path>")
        sys.exit(1)
    print(compare_specs(Path(sys.argv[1])))
