"""Prompt construction for spec generation.

The prompt embeds:
- The 16-section template with required content for each section
- FULL reference sections from TOOL-001 (user stories, test plan, edge cases) so the
  model has concrete examples of the required density and concreteness.
- A 'don't do' anti-pattern list
- The tool-specific brief
"""
from __future__ import annotations

from pathlib import Path
from textwrap import dedent

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLD_SPEC = REPO_ROOT / "docs/skills_library/skills/SKILL-001-fastapi-production/specs/TOOL-001-add_soft_delete.md"

SYSTEM_PROMPT = dedent(
    """
    You are a senior software architect writing rigorous engineering specifications
    for HuGR SKILL-001 FastAPI Production. Each spec is a self-contained markdown
    document of 750-1100 lines (target ~900), following a strict 16-section template.
    Your output is consumed by a code-generation tool that will implement the spec,
    so it must be detailed, mechanical, and free of ambiguity.

    HARD RULES (your spec is REJECTED if any of these fail):
    - Output ONLY the markdown spec. Nothing before, nothing after. No preamble.
    - All 16 sections present, in order, with the EXACT section headings shown below.
    - Code examples must be REAL Python that parses with `ast.parse`. No pseudocode.
    - Each Quality Standard must include an "Enforcement:" explanation.
    - Each Invariant row must reference a specific Test ID (e.g. T-04).
    - Tables must be valid GitHub-flavored markdown.
    - Section 5 (Quality Standards): >= 10 rows.
    - Section 6 (Completeness Criteria): >= 28 rows.
    - Section 8 (Invariants): >= 6 rows.
    - Section 9 (User Stories): EXACTLY 25 stories in 5 sub-sections of 5.
      Each story must have a bold title, then "Given/When/Then" lines (>= 4 total lines per story).
    - Section 10 (Test Plan): EXACTLY 30 unique tests T-01..T-30, in 5-6 sub-sections.
      Each in a table row with Setup/Action/Expected columns.
    - Section 11 (Interaction Matrix): table with >= 8 rows + a "Conflicts:" line.
    - Section 13 (Edge Cases): EXACTLY 15 rows EC-1..EC-15 in a single table.
    - Section 14 (Acceptance Criteria): EXACTLY 10 numbered items, each prefixed `✅`.
    - Section 15 (Implementation Checklist): >= 10 sub-sections (15.1, 15.2, ...),
      each with >= 5 checkbox items `- [ ]`.
    - Section 16 MUST end with a closed ```json block containing `status`,
      `files_created`, `files_modified`, `metrics`, `next_steps`, `warnings`, `notes`.
      The very last line of the document must be the ``` closing fence.

    DENSITY DEMAND:
    - Final spec must be >= 750 lines.
    - If you risk running out of space, EXPAND sections 9 and 10 (more story detail,
      more test rows). Compress NOTHING. Do not abbreviate any list with "etc." or "...".

    DO NOT DO:
    - No "TODO", "TBD", "FIXME", or `<placeholder>` markers.
    - No "etc." or "..." in lists. Enumerate every item.
    - No vague phrases like "for example" without an actual example.
    - No code fences inside JSON.
    - No heading levels deeper than ###.
    - No emojis except checkbox ✅ in section 14.
    - English only.
    """
).strip()


SECTION_TEMPLATE = dedent(
    """
    ## REQUIRED 16-SECTION STRUCTURE (use these exact headings)

    # TOOL-{tool_num}: {tool_name}

    > **Status**: SPEC v2 (rigorous)
    > **Last updated**: {date}

    ---

    ## 1. Overview
    Markdown table with rows: Tool name, Category, Complexity, Dependencies, Signature, Parameters.

    ## 2. Purpose
    2-3 sentence statement explaining what the tool does and why it matters in production.

    ## 3. Performance SLOs
    Markdown table with 6-9 metrics, each with Target and Why columns.

    ## 4. Code Examples (Before / After)
    Real Python code (ast.parse-able) showing:
    - 4.1 The relevant model BEFORE
    - 4.2 The relevant model AFTER (modified)
    - 4.3+ Any new modules created (CRUD, deps, helpers, etc.)
    - 4.N Migration file (Alembic)
    Use ```python code fences. Imports must be valid.

    ## 5. Quality Standards
    Markdown table with 8-12 rows. Columns: #, Standard, Enforcement.
    Each Enforcement explains HOW the standard is mechanically enforced (which file/check).

    ## 6. Completeness Criteria
    Markdown table with 24-33 rows. Columns: ID (CC-01..), Criterion, Verification.
    Verification is the concrete check (e.g. "grep", "T-09", "Inspect upgrade()").

    ## 7. Definition of Done (DoD)
    Markdown checkbox list with ~13 items, each starting `- [ ]`.

    ## 8. Invariants
    Markdown table with 6-8 rows. Columns: ID (INV-XX-NN), Invariant, Enforcement, Test (T-XX).
    Every invariant MUST reference at least one test from section 10.

    ## 9. User Stories
    Exactly 25 stories in 5 sub-sections of 5 each:
    ### 9.1 <theme> (US-01 .. US-05)
    ### 9.2 <theme> (US-06 .. US-10)
    ### 9.3 <theme> (US-11 .. US-15)
    ### 9.4 <theme> (US-16 .. US-20)
    ### 9.5 <theme> (US-21 .. US-25)
    Each story: bold title, "As a / I want / So that" optional, then "Given / When / Then".

    ## 10. Test Plan
    Exactly 30 test cases in 5-6 sub-sections. Use markdown tables with columns:
    #, Test, Setup, Action, Expected.

    ## 11. Interaction Matrix
    Markdown table listing how this tool interacts with other tools in SKILL-001.
    Columns: Other tool, Order matters?, Interaction, Notes.
    End with a "Conflicts:" line.

    ## 12. Rollback Procedure
    Subsections: Code rollback (before deploy), Database rollback (after deploy),
    Data preservation rollback, Failure mode (partial modification), Emergency.
    Each with shell or SQL commands as needed.

    ## 13. Edge Cases
    Exactly 15 numbered cases (EC-1 .. EC-15) in a markdown table.
    Columns: #, Scenario, Expected behavior.

    ## 14. Acceptance Criteria (Final Sign-off)
    Numbered list of exactly 10 items, each prefixed with `✅`.

    ## 15. Implementation Checklist (Ultra-granular)
    Sub-sections 15.1, 15.2, ... 15.N (8-15 sub-sections).
    Each with a checkbox list `- [ ]` of granular tasks.

    ## 16. Documentation Output
    A single ```json code block representing the success report:
    {{
      "status": "success",
      "files_created": [...],
      "files_modified": [...],
      "metrics": {{...}},
      "next_steps": [...],
      "warnings": [...],
      "notes": [...]
    }}
    """
).strip()


STYLE_EXAMPLE = dedent(
    """
    ## STYLE EXAMPLE (excerpt from TOOL-001 add_soft_delete; do NOT copy this content,
    just match the tone, density, and formatting)

    | Field | Value |
    |-------|-------|
    | Tool name | `fastapi_add_soft_delete` |
    | Category | EXTEND > CRUD & Data |
    | Complexity | Medium |
    | Dependencies | Existing project with at least 1 model + Alembic |

    | INV-SD-01 | Soft-deleted records are NEVER returned by default queries | `get()` adds `where(is_deleted == False)` unconditionally | T-03 |

    | EC-1 | Model has no `created_at` column | Tool errors: "Model must have created_at for soft-delete index". Suggest adding timestamps first. |
    """
).strip()


def _extract_section(content: str, header: str, next_header: str) -> str:
    start = content.find(header)
    if start < 0:
        return ""
    end = content.find(next_header, start + 1)
    return content[start:end] if end > 0 else content[start:]


def _gold_reference_excerpts() -> str:
    """Extract dense reference sections from TOOL-001 to teach the model the bar."""
    if not GOLD_SPEC.exists():
        return ""
    text = GOLD_SPEC.read_text()
    sections = [
        ("## 5. Quality Standards", "## 6."),
        ("## 8. Invariants", "## 9."),
        ("## 9. User Stories", "## 10."),
        ("## 13. Edge Cases", "## 14."),
        ("## 16. Documentation Output", "<EOF>"),
    ]
    parts = []
    for header, end in sections:
        chunk = _extract_section(text, header, end)
        if chunk:
            parts.append(chunk.strip())
    return "\n\n".join(parts)


def build_prompt(*, tool_num: str, tool_name: str, brief: str, date: str = "2026-04-08") -> str:
    """
    Build the full user prompt for DeepSeek.
    `brief` is the tool-specific section: name, signature, parameters, purpose,
    technical decisions, key invariants, anti-patterns to avoid.
    """
    gold_excerpts = _gold_reference_excerpts()

    parts = [
        SECTION_TEMPLATE.format(tool_num=tool_num, tool_name=tool_name, date=date),
        "",
        "## REFERENCE: dense sections from the canonical TOOL-001-add_soft_delete spec",
        "(Use these as a STYLE and DENSITY reference. DO NOT copy content. Each section",
        "below shows the level of concrete detail required.)",
        "",
        gold_excerpts,
        "",
        "---",
        "",
        "## TOOL-SPECIFIC BRIEF (the spec you must write)",
        "",
        brief.strip(),
        "",
        "---",
        "",
        "Now write the complete TOOL-{}-{}.md spec following all rules.".format(tool_num, tool_name),
        "Output ONLY the markdown spec body. Start with `# TOOL-{}: {}` on line 1.".format(tool_num, tool_name),
        "Match the density of the reference excerpts. Aim for 800-950 lines total.",
        "Each user story (US-XX) should have at least 4-7 lines of detail with concrete",
        "values, not generic 'Given X / When Y / Then Z' templates.",
    ]
    return "\n".join(parts)
