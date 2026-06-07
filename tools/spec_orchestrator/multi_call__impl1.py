"""Internal: reference excerpts, shared rules, and prompt builders A/B/C.

Split out of multi_call.py to keep modules <=500 LOC. Not a public API; import
from `spec_orchestrator.multi_call` instead.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLD_TOOL_001 = (
    REPO_ROOT
    / "docs/skills_library/skills/SKILL-001-fastapi-production/specs/TOOL-001-add_soft_delete.md"
)
GOLD_TOOL_008 = (
    REPO_ROOT
    / "docs/skills_library/skills/SKILL-001-fastapi-production/specs/TOOL-008-add_multi_tenancy.md"
)


# ============================================================================
# Reference excerpts (loaded once)
# ============================================================================
def _extract_section(content: str, header: str, next_header: str) -> str:
    start = content.find(header)
    if start < 0:
        return ""
    end = content.find(next_header, start + 1)
    return content[start:end] if end > 0 else content[start:]


def _gold_excerpt(file: Path, header: str, next_header: str) -> str:
    if not file.exists():
        return ""
    return _extract_section(file.read_text(), header, next_header).strip()


def _ref_section_4() -> str:
    return _gold_excerpt(GOLD_TOOL_008, "## 4. Code Examples", "## 5.")


def _ref_section_5() -> str:
    return _gold_excerpt(GOLD_TOOL_008, "## 5. Quality Standards", "## 6.")


def _ref_section_6() -> str:
    return _gold_excerpt(GOLD_TOOL_008, "## 6. Completeness Criteria", "## 7.")


def _ref_section_8() -> str:
    return _gold_excerpt(GOLD_TOOL_008, "## 8. Invariants", "## 9.")


def _ref_section_9() -> str:
    return _gold_excerpt(GOLD_TOOL_008, "## 9. User Stories", "## 10.")


def _ref_section_10() -> str:
    return _gold_excerpt(GOLD_TOOL_008, "## 10. Test Plan", "## 11.")


def _ref_section_13() -> str:
    return _gold_excerpt(GOLD_TOOL_008, "## 13. Edge Cases", "## 14.")


def _ref_section_15() -> str:
    return _gold_excerpt(GOLD_TOOL_008, "## 15. Implementation Checklist", "## 16.")


def _ref_section_16() -> str:
    return _gold_excerpt(GOLD_TOOL_008, "## 16. Documentation Output", "<EOF>")


# ============================================================================
# Shared system prompt
# ============================================================================
SHARED_RULES = dedent(
    """
    HARD RULES (output is REJECTED if any fail):
    - Output ONLY the markdown for the requested sections. No preamble. No closing remarks.
    - Use the EXACT section headings shown below.
    - Code examples must be REAL Python that parses with `ast.parse`. No pseudocode.
    - Every Python block must contain meaningful code. NEVER `pass`-only stubs.
      NEVER `# TODO` comments. NEVER duplicate identical Before/After blocks.
    - Tables must be valid GitHub-flavored markdown.
    - No "TODO", "TBD", "FIXME", "..." in lists. Enumerate every item.
    - No vague phrases ("appropriately", "as needed", "for example" without an example).
    - Every story, test, edge case must contain CONCRETE values: file paths, route paths,
      status codes, function names, field names, env vars. NEVER generic templates.
    - English only. No emojis except checkbox ✅ in section 14.
    - Match the density and concreteness of the gold reference excerpts shown.
    """
).strip()


# ============================================================================
# CALL A — Sections 1-3 (Overview, Purpose, SLOs)
# ============================================================================
SYSTEM_A = (
    dedent(
        """
    You are a senior software architect writing the HEADER block (sections 1-3) of a
    rigorous engineering specification for HuGR SKILL-001 FastAPI Production.
    """
    ).strip()
    + "\n\n"
    + SHARED_RULES
)


def build_prompt_a(*, tool_num: str, tool_name: str, brief: str, date: str) -> str:
    return dedent(
        f"""
        Write SECTIONS 1-3 of TOOL-{tool_num}-{tool_name}.md.

        Required output starting on line 1:

        # TOOL-{tool_num}: {tool_name}

        > **Status**: SPEC v2 (rigorous)
        > **Last updated**: {date}

        ---

        ## 1. Overview

        Markdown table with EXACTLY these rows in this order: Tool name, Category,
        Complexity, Dependencies, Signature, Parameters.
        - "Tool name" value: ` `fastapi_{tool_name}` `
        - "Category" value: derived from the tool brief (e.g. "EXTEND > API Design")
        - "Complexity": Medium or High
        - "Dependencies": list real dependencies from the brief, comma-separated
        - "Signature": full Python typed signature
        - "Parameters": each parameter on its own line via `<br>`, with concrete
          description (purpose AND default value AND example value)

        ## 2. Purpose

        One dense paragraph of 4-6 sentences (at least 80 words). Must explain:
        - Sentence 1-2: WHAT the tool does (concrete capability, name key artifacts)
        - Sentence 3: WHY it matters in production (the problem without this tool)
        - Sentence 4: HOW it integrates (mechanism: listener, middleware, dependency, etc.)
        - Sentence 5-6: KEY DESIGN DECISIONS (e.g. "shared_db strategy by default",
          "Fernet encryption for tokens at rest", "Stripe-style HMAC signatures")

        The reviewer REJECTS if Purpose has < 60 words or < 3 sentences.

        ## 3. Performance SLOs

        Markdown table with EXACTLY 7-9 rows. Columns: Metric, Target, Why.
        Each Target must be a concrete number with a unit (e.g. "< 5 ms", "≥ 100 req/s",
        "< 4s for typical project"). Each Why must be a one-sentence justification.
        Must include rows for: tool execution time, files modified, files created,
        latency overhead, memory overhead, migration runtime (or "0s — no DB changes"),
        and at least 2 tool-specific metrics.

        ---

        TOOL BRIEF:

        {brief.strip()}

        ---

        Output ONLY markdown. Start with `# TOOL-{tool_num}: {tool_name}` on line 1.
        Stop immediately after the section 3 closing line. Do NOT add a `---` separator.
        Do NOT include section 4 or any later section.
        """
    ).strip()


# ============================================================================
# CALL B — Section 4 ALONE (Code Examples)  ★ THE MOST CRITICAL CALL
# ============================================================================
SYSTEM_B = (
    dedent(
        """
    You are a senior FastAPI engineer writing the CODE EXAMPLES section (section 4)
    of a rigorous engineering specification. Your output is consumed by a code-generation
    tool that will implement the spec, so every code block MUST be real, copy-pastable
    Python that demonstrates a CONCRETE change.
    """
    ).strip()
    + "\n\n"
    + SHARED_RULES
    + "\n\n"
    + dedent(
        """
    SECTION 4 SPECIFIC RULES (extra-strict — AUTOMATIC REJECTION if violated):
    - Produce AT LEAST 9 ```python fenced blocks. The reviewer gate requires ≥ 8
      "meaningful" blocks (10+ lines, parses, not a stub). Aim for 9-12 to have margin.
    - Each Before/After PAIR must show a MEANINGFUL DIFFERENCE. The After block must
      add new imports, new fields, new methods, or new functions that the Before block
      lacks. NEVER produce a Before and After that are byte-equal or near-identical.
    - If a layer (e.g. CRUD) genuinely doesn't change, OMIT the Before/After comparison
      and instead show a NEW module or NEW function in that layer (no Before).
    - Each Python block must be 10-40 lines of REAL code. NEVER `pass`-only,
      NEVER `# TODO`, NEVER `...` body. Blocks with < 10 lines are REJECTED.
    - Cover ALL of these (each as its own sub-section with its own code block):
      * Model change OR new model (4.1/4.2 Before/After)
      * New helper/core module (4.3)
      * CRUD or service change (4.4)
      * Route change or new route (4.5)
      * Schema or Pydantic model (4.6)
      * Middleware or dependency (4.7 if applicable)
      * Migration file with real `op.add_column`, `op.create_table`, etc. (4.8)
      * At least 1 additional module (config, utils, etc.) (4.9)
    - Every import must be plausible: `from app.models.X import Y`, `from sqlalchemy import ...`.
    - Use realistic SQLAlchemy 2.0 typed syntax (Mapped, mapped_column).
    - Use realistic FastAPI patterns (CurrentUser, SessionDep, response_model).
    - Migration file: real Alembic upgrade() and downgrade() with concrete op.* calls.
    - Total section length: 250-450 lines.
    """
    ).strip()
)


def build_prompt_b(*, tool_num: str, tool_name: str, brief: str, header: str) -> str:
    ref = _ref_section_4()
    return dedent(
        f"""
        Sections 1-3 already written for context (do NOT repeat them):

        ```markdown
        {header}
        ```

        ---

        REFERENCE: full Code Examples section from TOOL-008 (gold standard).
        Match this density and concreteness. DO NOT copy content — adapt to the new tool.

        {ref}

        ---

        TOOL BRIEF:

        {brief.strip()}

        ---

        Now write SECTION 4 ONLY for TOOL-{tool_num}-{tool_name}.md.

        Required structure:

        ## 4. Code Examples (Before / After)

        ### 4.1 <descriptive title for first artifact>: BEFORE
        ```python
        # ... real code ...
        ```

        ### 4.2 <descriptive title for first artifact>: AFTER
        ```python
        # ... real code that visibly differs from 4.1 ...
        ```

        (continue with 4.3, 4.4, 4.5, 4.6, ... covering all the artifacts the tool creates)

        REQUIREMENTS:
        - At least 6 ```python blocks
        - At least 1 Before/After PAIR with meaningful diff
        - At least 1 NEW module shown without a Before (because there is no Before)
        - At least 1 Alembic migration block with real op.* calls
        - Total section length 200-350 lines
        - All code must parse with ast.parse

        Stop immediately after the last code block of section 4.
        Do NOT include section 5 or any later section. Do NOT add a `---` separator.
        Output ONLY the markdown of section 4. Start with `## 4. Code Examples (Before / After)` on line 1.
        """
    ).strip()


# ============================================================================
# CALL C — Sections 5-8 (QS, CC, DoD, Invariants)
# ============================================================================
SYSTEM_C = (
    dedent(
        """
    You are continuing a rigorous engineering specification. You will produce sections
    5 (Quality Standards), 6 (Completeness Criteria), 7 (Definition of Done),
    and 8 (Invariants). These sections cross-reference each other and reference tests
    T-01..T-30 that will be written in a later call.
    """
    ).strip()
    + "\n\n"
    + SHARED_RULES
)


def build_prompt_c(*, tool_num: str, tool_name: str, brief: str, header_and_code: str) -> str:
    ref_5 = _ref_section_5()
    ref_6 = _ref_section_6()
    ref_8 = _ref_section_8()
    return dedent(
        f"""
        Sections 1-4 already written:

        ```markdown
        {header_and_code}
        ```

        ---

        REFERENCE: section 5 from TOOL-008 (12 quality standards):

        {ref_5}

        ---

        REFERENCE: section 6 from TOOL-008 (30 completeness criteria):

        {ref_6}

        ---

        REFERENCE: section 8 from TOOL-008 (8 invariants with test refs):

        {ref_8}

        ---

        TOOL BRIEF:

        {brief.strip()}

        ---

        Now write SECTIONS 5, 6, 7, AND 8 for TOOL-{tool_num}-{tool_name}.md.

        ## 5. Quality Standards

        Markdown table with EXACTLY 12-14 rows. Columns: #, Standard, Enforcement.
        Each Enforcement column MUST be at least 8 words long — name the specific
        file path, function name, decorator, constraint class, or validation step.
        REJECTED if any Enforcement column is < 8 words.

        Example of GOOD enforcement (>= 8 words):
        "`DepthLimiter` extension in `app/graphql/extensions.py` validates depth via AST traversal and raises `GraphQLError` with 400 status"

        Example of BAD enforcement (< 8 words — REJECTED):
        "Middleware adds headers"

        ## 6. Completeness Criteria

        Markdown table with EXACTLY 30-33 rows. Columns: ID (CC-01..), Criterion, Verification.
        Verification is the concrete check (e.g. "grep `INV-XX` in source", "T-09",
        "Inspect upgrade()", "curl /openapi.json"). NEVER vague.

        ## 7. Definition of Done (DoD)

        Markdown checkbox list with EXACTLY 13 items. Each starts `- [ ]` and references
        a concrete artifact or check (e.g. "All 30 Completeness Criteria verified").

        ## 8. Invariants

        Markdown table with EXACTLY 8 rows. Columns: ID (use a 2-3 letter prefix derived
        from the tool, e.g. INV-VER-01 for api_versioning), Invariant, Enforcement, Test.

        EVERY row's Enforcement column MUST be at least 8 words describing the
        specific mechanism (file, function, event, constraint). REJECTED if < 8 words.

        Example of GOOD Enforcement:
        "`do_orm_execute` listener adds `WHERE tenant_id = current_tenant` unconditionally via `with_loader_criteria`"

        Example of BAD Enforcement (REJECTED):
        "Path-based router isolation"

        EVERY row's Test column must reference at least one test ID T-XX (T-01 to T-30).
        Distribute references across the 30 tests so the test plan in the next call
        can produce matching tests.

        Stop immediately after the closing row of section 8. Do NOT include section 9.
        Do NOT add a `---` separator. Output ONLY the markdown.
        Start with `## 5. Quality Standards` on line 1.
        """
    ).strip()
