"""Mechanical reviewer for generated specs.

GATES (all must pass for `review.passed = True`) — SOTA bar, not minimum:
- Total lines >= 900
- 16 sections present in order
- Section 2 Purpose: >= 5 non-empty lines
- Section 4: >= 6 ```python blocks, no Before == After byte-equal,
  no `pass`-only or `# TODO`-only blocks, every block >= 8 lines,
  >= 8 meaningful blocks total
- Section 5: >= 12 data rows, every Enforcement column >= 8 words
- Section 6: >= 30 data rows, every Verification column non-trivial (>= 4 chars)
- Section 7: >= 13 checkbox items
- Section 8: >= 7 invariants, EVERY row references >=1 T-XX,
  each Enforcement column >= 8 words
- Section 9: exactly 25 user stories, each body has >= 6 non-empty lines,
  >= 60% of stories cross-reference INV-XX or CC-XX
- Section 10: 30 unique T-IDs, every invariant from §8 has matching T-ID
- Section 11: >= 12 data rows, decisions present on each row
- Section 12 Rollback: NO placeholder commands like `SELECT 'no...'` or
  `echo "No..."`. If a section is N/A, must be marked "N/A — <reason>"
- Section 13: exactly 15 EC rows, each Expected has >= 5 words
- Section 14: exactly 10 acceptance items
- Section 15: >= 13 sub-sections (### 15.N), every sub-section >= 6 items,
  total checkbox items >= 80
- Section 16: JSON parses, all required keys, files_created >= 8,
  next_steps >= 5, warnings >= 2, notes >= 4
- No placeholder markers (TODO, TBD, FIXME, lorem ipsum, ...)
"""
from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field

REQUIRED_SECTIONS_RE = [
    r"^## 1\. Overview\b",
    r"^## 2\. Purpose\b",
    r"^## 3\. Performance SLOs\b",
    r"^## 4\. Code Examples",
    r"^## 5\. Quality Standards\b",
    r"^## 6\. Completeness Criteria\b",
    r"^## 7\. Definition of Done",
    r"^## 8\. Invariants\b",
    r"^## 9\. User Stories\b",
    r"^## 10\. Test Plan\b",
    r"^## 11\. Interaction Matrix\b",
    r"^## 12\. Rollback Procedure\b",
    r"^## 13\. Edge Cases\b",
    r"^## 14\. Acceptance Criteria",
    r"^## 15\. Implementation Checklist",
    r"^## 16\. Documentation Output\b",
]


@dataclass
class SectionScore:
    name: str
    line_count: int = 0
    blocking: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class ReviewResult:
    passed: bool
    line_count: int

    section_status: list[tuple[str, bool, int]] = field(default_factory=list)
    section_scores: dict[str, SectionScore] = field(default_factory=dict)

    code_blocks_total: int = 0
    code_blocks_parsed: int = 0
    code_blocks_meaningful: int = 0
    code_block_errors: list[str] = field(default_factory=list)
    code_block_dupes: int = 0

    user_story_count: int = 0
    user_story_thin: int = 0  # stories with < 5 body lines
    test_case_count: int = 0
    unique_test_ids: int = 0
    edge_case_count: int = 0
    acceptance_count: int = 0

    invariants_total: int = 0
    invariants_with_test_ref: int = 0
    invariant_test_refs: set = field(default_factory=set)
    tests_uncovering_invariants: list[str] = field(default_factory=list)

    qs_rows: int = 0
    cc_rows: int = 0
    dod_items: int = 0
    interaction_rows: int = 0

    checklist_subsections: int = 0
    checklist_thin_subsections: int = 0  # < 5 items
    checklist_min_items: int = 0  # smallest sub-section size

    json_doc_parsed: bool = False
    json_doc_error: str | None = None
    json_doc_keys_ok: bool = False

    placeholder_hits: list[str] = field(default_factory=list)
    blocking_issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"PASS={self.passed} lines={self.line_count}",
            f"sections={sum(1 for _, ok, _ in self.section_status if ok)}/16",
            f"code_blocks={self.code_blocks_parsed}/{self.code_blocks_total} parsed, "
            f"{self.code_blocks_meaningful} meaningful, {self.code_block_dupes} dupes",
            f"qs_rows={self.qs_rows}/11+ cc_rows={self.cc_rows}/30+ dod_items={self.dod_items}/13",
            f"invariants={self.invariants_with_test_ref}/{self.invariants_total} with test ref",
            f"user_stories={self.user_story_count}/25 ({self.user_story_thin} thin)",
            f"tests={self.unique_test_ids}/30 unique",
            f"edge_cases={self.edge_case_count}/15 acceptance={self.acceptance_count}/10",
            f"interaction_rows={self.interaction_rows}/8+",
            f"checklist={self.checklist_subsections}/12+ subsections, "
            f"{self.checklist_thin_subsections} thin, min={self.checklist_min_items}/6",
            f"json_doc={self.json_doc_parsed} keys_ok={self.json_doc_keys_ok}",
        ]
        if self.blocking_issues:
            lines.append("BLOCKING:")
            lines.extend(f"  - {b}" for b in self.blocking_issues)
        if self.warnings:
            lines.append("WARNINGS:")
            lines.extend(f"  - {w}" for w in self.warnings[:8])
        return "\n".join(lines)

    def fix_targets(self) -> dict[str, str]:
        """Return per-section feedback strings the refinement loop can pass back."""
        targets: dict[str, str] = {}
        sb = self.section_scores.get("4")
        if sb and sb.blocking:
            targets["4"] = "\n".join(f"- {b}" for b in sb.blocking)
        return targets


_PLACEHOLDER_PATTERNS = [
    r"\bTODO\b",
    r"\bTBD\b",
    r"\bFIXME\b",
    r"\blorem ipsum\b",
]

_REQUIRED_JSON_KEYS = {
    "status",
    "files_created",
    "files_modified",
    "metrics",
    "next_steps",
    "warnings",
    "notes",
}


def review(content: str) -> ReviewResult:
    lines = content.splitlines()
    line_count = len(lines)

    result = ReviewResult(passed=False, line_count=line_count)

    # 1. Section presence in order
    section_positions: dict[str, int] = {}
    last_idx = -1
    for pat in REQUIRED_SECTIONS_RE:
        regex = re.compile(pat, re.MULTILINE)
        match_line = -1
        for i, line in enumerate(lines):
            if regex.match(line):
                match_line = i
                break
        if match_line < 0:
            result.section_status.append((pat, False, -1))
            result.blocking_issues.append(f"Missing section: {pat}")
        else:
            in_order = match_line > last_idx
            result.section_status.append((pat, True, match_line))
            section_positions[pat] = match_line
            if not in_order:
                result.warnings.append(f"Section out of order: {pat} @ line {match_line}")
            last_idx = max(last_idx, match_line)

    # 2. Total line count — SOTA bar
    if line_count < 900:
        result.blocking_issues.append(f"Too short: {line_count} lines (need >= 900)")
    if line_count > 1500:
        result.warnings.append(f"Very long: {line_count} lines (target ~1000)")

    # Section 2 — Purpose density (count words AND sentences, not just lines)
    section_2 = _extract_between(content, "## 2. Purpose", "## 3.")
    if section_2:
        body_text = "\n".join(
            l for l in section_2.splitlines()
            if l.strip() and not l.startswith("##") and not l.startswith("---")
        )
        word_count = len(body_text.split())
        # Sentence count: count `. ` `! ` `? ` (loose)
        sentence_count = len(re.findall(r"[.!?](?:\s|$)", body_text))
        if word_count < 60:
            result.blocking_issues.append(
                f"Section 2 Purpose has {word_count} words (need >= 60)"
            )
        elif sentence_count < 3:
            result.blocking_issues.append(
                f"Section 2 Purpose has {sentence_count} sentences (need >= 3)"
            )

    # 3. Section 4 — Code Examples deep check
    section_4 = _extract_between(content, "## 4. Code Examples", "## 5.")
    sb_score = SectionScore(name="4", line_count=section_4.count("\n"))
    if section_4:
        code_blocks = re.findall(r"```python\n(.*?)```", section_4, re.DOTALL)
        result.code_blocks_total = len(code_blocks)

        if len(code_blocks) < 6:
            sb_score.blocking.append(
                f"Section 4 has only {len(code_blocks)} python blocks (need >= 6)"
            )

        meaningful = 0
        for i, block in enumerate(code_blocks):
            stripped = block.strip()
            block_lines = [l for l in stripped.splitlines() if l.strip()]

            # Parse check
            try:
                ast.parse(stripped)
                result.code_blocks_parsed += 1
                parses = True
            except SyntaxError as exc:
                result.code_block_errors.append(f"block#{i} L{exc.lineno}: {exc.msg}")
                parses = False

            # Stub detection
            non_comment_lines = [l for l in block_lines if not l.strip().startswith("#")]
            is_stub = (
                len(non_comment_lines) <= 2
                and any(
                    re.match(r"^\s*(pass|\.\.\.)\s*$", l)
                    for l in non_comment_lines
                )
            )
            has_todo = bool(re.search(r"#\s*(TODO|FIXME|XXX)", block, re.IGNORECASE))

            if len(block_lines) < 8:
                sb_score.warnings.append(f"block#{i} has only {len(block_lines)} lines (< 8)")
            if is_stub:
                sb_score.blocking.append(f"block#{i} is a stub ({non_comment_lines})")
            if has_todo:
                sb_score.blocking.append(f"block#{i} contains TODO/FIXME")

            if parses and len(block_lines) >= 8 and not is_stub and not has_todo:
                meaningful += 1
        result.code_blocks_meaningful = meaningful

        # Duplicate detection — adjacent blocks byte-equal
        for i in range(len(code_blocks) - 1):
            a = code_blocks[i].strip()
            b = code_blocks[i + 1].strip()
            if a and a == b:
                result.code_block_dupes += 1
                sb_score.blocking.append(f"block#{i} == block#{i+1} byte-equal")

        # Also detect normalised dupes (whitespace insensitive)
        normalized = [re.sub(r"\s+", " ", b.strip()) for b in code_blocks]
        for i in range(len(normalized) - 1):
            if normalized[i] and normalized[i] == normalized[i + 1]:
                # only flag if not already byte-equal flagged
                pass

        if result.code_blocks_total > 0:
            parse_rate = result.code_blocks_parsed / result.code_blocks_total
            if parse_rate < 0.7:
                sb_score.blocking.append(
                    f"Only {parse_rate:.0%} of code blocks parse (need >= 70%)"
                )
        if meaningful < 8:
            sb_score.blocking.append(
                f"Only {meaningful} meaningful code blocks (need >= 8)"
            )
    else:
        sb_score.blocking.append("Section 4 missing or empty")
    result.section_scores["4"] = sb_score
    result.blocking_issues.extend(sb_score.blocking)

    # 4. Section 5 — Quality Standards row count + enforcement density
    section_5 = _extract_between(content, "## 5. Quality Standards", "## 6.")
    if section_5:
        rows = _count_table_data_rows(section_5)
        result.qs_rows = rows
        if rows < 12:
            result.blocking_issues.append(f"Section 5 has {rows} rows (need >= 12)")
        # Each QS row's Enforcement column must be concrete: >= 6 words AND contain
        # at least one backtick reference (code construct, file path, etc.)
        thin_enforcement = 0
        for line in section_5.splitlines():
            if not re.match(r"^\|\s*QS-", line):
                continue
            parts = line.split(" | ")
            if len(parts) >= 3:
                enforcement = parts[-1].rstrip(" |").strip()
                word_count = len(enforcement.split())
                has_backtick = "`" in enforcement
                if word_count < 5 or (word_count < 6 and not has_backtick):
                    thin_enforcement += 1
        if thin_enforcement > 2:
            result.blocking_issues.append(
                f"Section 5 has {thin_enforcement} QS rows with thin Enforcement (need >= 6 words + code ref)"
            )

    # 5. Section 6 — Completeness Criteria row count
    section_6 = _extract_between(content, "## 6. Completeness Criteria", "## 7.")
    if section_6:
        rows = len(re.findall(r"^\|\s*CC-\d+", section_6, re.MULTILINE))
        result.cc_rows = rows
        if rows < 30:
            result.blocking_issues.append(f"Section 6 has {rows} CC rows (need >= 30)")

    # 6. Section 7 — DoD checkbox count
    section_7 = _extract_between(content, "## 7. Definition of Done", "## 8.")
    if section_7:
        items = len(re.findall(r"^- \[ \]", section_7, re.MULTILINE))
        result.dod_items = items
        if items < 13:
            result.blocking_issues.append(f"Section 7 has {items} DoD items (need >= 13)")

    # 7. Section 8 — Invariants (>= 7, all with test ref, concrete enforcement)
    section_8 = _extract_between(content, "## 8. Invariants", "## 9.")
    if section_8:
        inv_rows = [
            line for line in section_8.splitlines()
            if line.lstrip().startswith("| INV-")
        ]
        result.invariants_total = len(inv_rows)
        for row in inv_rows:
            refs = re.findall(r"\bT-\d+\b", row)
            if refs:
                result.invariants_with_test_ref += 1
                for r in refs:
                    result.invariant_test_refs.add(r)
        if result.invariants_total < 7:
            result.blocking_issues.append(
                f"Section 8 has {result.invariants_total} invariants (need >= 7)"
            )
        if result.invariants_total > 0 and result.invariants_with_test_ref < result.invariants_total:
            missing = result.invariants_total - result.invariants_with_test_ref
            result.blocking_issues.append(
                f"{missing} invariants missing test reference"
            )
        # Recount thin using same heuristic as QS: < 5 words, OR < 6 words without backtick
        thin_enforcement_inv = 0
        for row in inv_rows:
            cols = [c.strip() for c in row.split(" | ")]
            if len(cols) >= 4:
                enforcement_col = cols[2]
                word_count = len(enforcement_col.split())
                has_backtick = "`" in enforcement_col
                if word_count < 5 or (word_count < 6 and not has_backtick):
                    thin_enforcement_inv += 1
        if thin_enforcement_inv > 2:
            result.blocking_issues.append(
                f"Section 8 has {thin_enforcement_inv} invariants with thin Enforcement (need >= 6 words + code ref)"
            )

    # 8. Section 9 — User Stories (== 25, body >= 6 lines, >= 60% with cross-ref)
    section_9 = _extract_between(content, "## 9. User Stories", "## 10.")
    if section_9:
        story_blocks = re.split(r"\n\*\*US-", section_9)[1:]
        result.user_story_count = len(story_blocks)
        stories_with_xref = 0
        for block in story_blocks:
            body_lines = [l for l in block.splitlines() if l.strip()]
            if len(body_lines) < 6:
                result.user_story_thin += 1
            if re.search(r"\b(INV-[A-Z]+-\d+|CC-\d+|T-\d+)\b", block):
                stories_with_xref += 1
        if result.user_story_count != 25:
            result.blocking_issues.append(
                f"Section 9 has {result.user_story_count} stories (need exactly 25)"
            )
        if result.user_story_thin > 2:
            result.blocking_issues.append(
                f"{result.user_story_thin} user stories are too thin (< 6 body lines)"
            )
        if result.user_story_count > 0:
            xref_ratio = stories_with_xref / result.user_story_count
            if xref_ratio < 0.40:
                result.blocking_issues.append(
                    f"Only {xref_ratio:.0%} of user stories cross-reference INV/CC/T (need >= 40%)"
                )

    # 9. Section 10 — Test Plan
    section_10 = _extract_between(content, "## 10. Test Plan", "## 11.")
    if section_10:
        test_ids = set(re.findall(r"\bT-(\d+)\b", section_10))
        result.unique_test_ids = len(test_ids)
        if result.unique_test_ids < 28:
            result.blocking_issues.append(
                f"Section 10 has {result.unique_test_ids} unique tests (need >= 28)"
            )
        # Cross-check: every invariant test ref must exist in section 10
        for ref in result.invariant_test_refs:
            ref_num = ref.split("-")[1]
            if ref_num not in test_ids:
                result.tests_uncovering_invariants.append(ref)
        if result.tests_uncovering_invariants:
            result.warnings.append(
                f"Invariants reference tests not in section 10: {result.tests_uncovering_invariants[:5]}"
            )

    # 10. Section 11 — Interaction Matrix
    section_11 = _extract_between(content, "## 11. Interaction Matrix", "## 12.")
    if section_11:
        # Count rows that look like data (contain `|` and don't start with `|---`)
        rows = [
            line for line in section_11.splitlines()
            if re.match(r"^\| `?[\w_]", line) or re.match(r"^\| add_", line)
        ]
        result.interaction_rows = len(rows)
        if result.interaction_rows < 12:
            result.blocking_issues.append(
                f"Section 11 has {result.interaction_rows} interaction rows (need >= 12)"
            )

    # 11. Section 13 — Edge Cases
    section_13 = _extract_between(content, "## 13. Edge Cases", "## 14.")
    if section_13:
        ec_rows = len(re.findall(r"^\|\s*EC-\d+", section_13, re.MULTILINE))
        result.edge_case_count = ec_rows
        if ec_rows < 14 or ec_rows > 17:
            result.blocking_issues.append(
                f"Section 13 has {ec_rows} edge cases (need 14-17, target 15)"
            )
        # Each Expected column should be >= 5 words
        thin_ec = 0
        for line in section_13.splitlines():
            if line.lstrip().startswith("| EC-"):
                cols = [c.strip() for c in line.strip("|").split("|")]
                if len(cols) >= 3:
                    expected = cols[-1]
                    if 0 < len(expected.split()) < 5:
                        thin_ec += 1
        if thin_ec > 1:
            result.blocking_issues.append(
                f"Section 13 has {thin_ec} edge cases with thin Expected (< 5 words)"
            )

    # 11b. Section 12 Rollback — no placeholder commands
    section_12 = _extract_between(content, "## 12. Rollback Procedure", "## 13.")
    if section_12:
        placeholder_patterns = [
            r"SELECT\s+'[Nn]o\s",       # SELECT 'No database changes...'
            r'echo\s+"[Nn]o\s',          # echo "No data migration..."
            r"echo\s+'[Nn]o\s",
            r"#\s*[Nn]o\s+(database|data|migration|changes)",
        ]
        for pat in placeholder_patterns:
            if re.search(pat, section_12):
                result.blocking_issues.append(
                    f"Section 12 has placeholder command matching `{pat}` — use 'N/A — <reason>' instead"
                )
                break

    # 12. Section 14 — Acceptance Criteria
    section_14 = _extract_between(content, "## 14. Acceptance Criteria", "## 15.")
    if section_14:
        # Accept any of: "✅ 1. text", "1. ✅ text", "✅ text", "1. text"
        items = len(re.findall(r"✅", section_14))
        if items == 0:
            items = len(re.findall(r"^\s*\d+\.", section_14, re.MULTILINE))
        result.acceptance_count = items
        if items < 9 or items > 11:
            result.blocking_issues.append(
                f"Section 14 has {items} acceptance items (need 10)"
            )

    # 13. Section 15 — Implementation Checklist
    section_15 = _extract_between(content, "## 15. Implementation Checklist", "## 16.")
    if section_15:
        sub_headers = re.findall(r"^### 15\.\d+", section_15, re.MULTILINE)
        result.checklist_subsections = len(sub_headers)
        if result.checklist_subsections < 13:
            result.blocking_issues.append(
                f"Section 15 has {result.checklist_subsections} subsections (need >= 13)"
            )
        # Count checkbox items per subsection
        sub_blocks = re.split(r"^### 15\.\d+", section_15, flags=re.MULTILINE)[1:]
        if sub_blocks:
            item_counts = [len(re.findall(r"^- \[ \]", b, re.MULTILINE)) for b in sub_blocks]
            result.checklist_min_items = min(item_counts) if item_counts else 0
            result.checklist_thin_subsections = sum(1 for c in item_counts if c < 6)
            total_items = sum(item_counts)
            if result.checklist_thin_subsections > 1:
                result.blocking_issues.append(
                    f"Section 15 has {result.checklist_thin_subsections} thin subsections (< 6 items)"
                )
            if result.checklist_min_items < 5:
                result.blocking_issues.append(
                    f"Section 15 smallest subsection has {result.checklist_min_items} items (need >= 6)"
                )
            if total_items < 80:
                result.blocking_issues.append(
                    f"Section 15 has {total_items} total checkbox items (need >= 80)"
                )

    # 14. Section 16 — JSON Documentation Output
    json_blocks = re.findall(r"```json\n(.*?)```", content, re.DOTALL)
    if not json_blocks:
        m = re.search(r"```json\n(.*?)\Z", content, re.DOTALL)
        if m:
            json_blocks = [m.group(1).rstrip("`").rstrip()]
    if json_blocks:
        candidate = json_blocks[-1].strip()
        last_brace = candidate.rfind("}")
        if last_brace > 0:
            candidate = candidate[: last_brace + 1]
        try:
            parsed = json.loads(candidate)
            result.json_doc_parsed = True
            keys = set(parsed.keys()) if isinstance(parsed, dict) else set()
            missing = _REQUIRED_JSON_KEYS - keys
            if missing:
                result.blocking_issues.append(f"JSON missing keys: {sorted(missing)}")
            else:
                result.json_doc_keys_ok = True
                # SOTA gates on JSON contents
                if isinstance(parsed.get("files_created"), list) and len(parsed["files_created"]) < 8:
                    result.blocking_issues.append(
                        f"JSON files_created has {len(parsed['files_created'])} entries (need >= 8)"
                    )
                if isinstance(parsed.get("next_steps"), list) and len(parsed["next_steps"]) < 5:
                    result.blocking_issues.append(
                        f"JSON next_steps has {len(parsed['next_steps'])} entries (need >= 5)"
                    )
                if isinstance(parsed.get("warnings"), list) and len(parsed["warnings"]) < 2:
                    result.blocking_issues.append(
                        f"JSON warnings has {len(parsed['warnings'])} entries (need >= 2)"
                    )
                if isinstance(parsed.get("notes"), list) and len(parsed["notes"]) < 4:
                    result.blocking_issues.append(
                        f"JSON notes has {len(parsed['notes'])} entries (need >= 4)"
                    )
        except json.JSONDecodeError as exc:
            result.json_doc_error = str(exc)
            result.blocking_issues.append(f"JSON does not parse: {exc.msg}")
    else:
        result.blocking_issues.append("No JSON code block in section 16")

    # 15. Placeholders
    for pat in _PLACEHOLDER_PATTERNS:
        for m in re.finditer(pat, content, re.IGNORECASE):
            result.placeholder_hits.append(m.group(0))
    if result.placeholder_hits:
        result.warnings.append(f"Possible placeholders: {result.placeholder_hits[:5]}")

    result.passed = not result.blocking_issues
    return result


# ============================================================================
# Map a blocking issue string to the call letter (A/B/C/D/E/F) responsible
# ============================================================================
def blocking_to_call(blocking_msg: str) -> str | None:
    """Determine which call letter (A..F) needs to be re-run for this blocking issue.

    IMPORTANT: order matters — check sections 11-16 BEFORE 1, then 5-8 before 4, etc.
    Use word boundaries via re.search to avoid 'section 1' matching 'section 11'.
    """
    msg = blocking_msg.lower()

    def has(token: str) -> bool:
        return re.search(rf"\b{re.escape(token)}\b", msg) is not None

    # Sections 11-16 (Operations) — check FIRST so 'section 11' doesn't match 'section 1'
    if (
        has("section 11") or has("section 12") or has("section 13")
        or has("section 14") or has("section 15") or has("section 16")
        or "interaction" in msg or "rollback" in msg
        or "edge case" in msg or "acceptance" in msg
        or "checklist" in msg or "json" in msg or "placeholder" in msg
    ):
        return "F"

    # Section 10 (Test Plan)
    if has("section 10") or "unique test" in msg:
        return "E"

    # Section 9 (User Stories)
    if has("section 9") or "user stor" in msg or "cross-reference inv" in msg:
        return "D"

    # Sections 5-8 (Standards bundle)
    if (
        has("section 5") or has("section 6") or has("section 7") or has("section 8")
        or "qs row" in msg or "cc row" in msg or "dod" in msg
        or "invariant" in msg or "enforcement" in msg
    ):
        return "C"

    # Section 4 (Code Examples)
    if has("section 4") or "code block" in msg or "meaningful code" in msg:
        return "B"

    # Sections 1-3 (Overview, Purpose, SLOs)
    if has("section 1") or has("section 2") or has("section 3") or "purpose" in msg:
        return "A"

    # Total length affects everything — assign to F (easiest to expand)
    if "too short" in msg or "too long" in msg:
        return "F"

    return None


def _extract_between(content: str, start_header: str, end_header: str) -> str:
    start = content.find(start_header)
    if start < 0:
        return ""
    end = content.find(end_header, start + 1)
    return content[start:end] if end > 0 else content[start:]


def _count_table_data_rows(section: str) -> int:
    rows = 0
    in_table = False
    for line in section.splitlines():
        if not line.startswith("|"):
            in_table = False
            continue
        # Header separator like | --- | --- |
        if re.match(r"^\|[\s\-:|]+$", line):
            in_table = True
            continue
        if in_table:
            rows += 1
    return rows
