"""6-call spec generation pipeline.

Each section that needs density gets its own dedicated call:

  Call A — Sections 1-3 (Overview, Purpose, SLOs)            ~80 lines  V3
  Call B — Section 4 alone (Code Examples)                   ~200 lines V3 (escalates to R1 on retry)
  Call C — Sections 5-8 (QS, CC, DoD, Invariants)            ~220 lines V3
  Call D — Section 9 alone (25 User Stories)                 ~280 lines V3
  Call E — Section 10 alone (30 Test Plan)                   ~120 lines V3
  Call F — Sections 11-16 (Interaction..Documentation Out)   ~300 lines V3

Total: 1100+ lines of dense, concrete content.

Cross-reference consistency:
  Call C is told it must reference T-01..T-30 (which Call E will produce).
  Call E receives Call C's invariants so it can ensure every invariant has a test.
  Call F receives the tool's name, purpose, invariants for cross-references.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from textwrap import dedent
from typing import Callable

from spec_orchestrator.client import CompletionResult, call_deepseek

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLD_TOOL_001 = REPO_ROOT / "docs/skills_library/skills/SKILL-001-fastapi-production/specs/TOOL-001-add_soft_delete.md"
GOLD_TOOL_008 = REPO_ROOT / "docs/skills_library/skills/SKILL-001-fastapi-production/specs/TOOL-008-add_multi_tenancy.md"


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
SYSTEM_A = dedent(
    """
    You are a senior software architect writing the HEADER block (sections 1-3) of a
    rigorous engineering specification for HuGR SKILL-001 FastAPI Production.
    """
).strip() + "\n\n" + SHARED_RULES


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
SYSTEM_B = dedent(
    """
    You are a senior FastAPI engineer writing the CODE EXAMPLES section (section 4)
    of a rigorous engineering specification. Your output is consumed by a code-generation
    tool that will implement the spec, so every code block MUST be real, copy-pastable
    Python that demonstrates a CONCRETE change.
    """
).strip() + "\n\n" + SHARED_RULES + "\n\n" + dedent(
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
SYSTEM_C = dedent(
    """
    You are continuing a rigorous engineering specification. You will produce sections
    5 (Quality Standards), 6 (Completeness Criteria), 7 (Definition of Done),
    and 8 (Invariants). These sections cross-reference each other and reference tests
    T-01..T-30 that will be written in a later call.
    """
).strip() + "\n\n" + SHARED_RULES


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


# ============================================================================
# CALL D — Section 9 ALONE (25 User Stories)
# ============================================================================
SYSTEM_D = dedent(
    """
    You are continuing a rigorous engineering specification. You will produce ONLY
    section 9 (User Stories): exactly 25 stories in 5 sub-sections of 5 each.
    Stories must cross-reference the tool's invariants from section 8.
    """
).strip() + "\n\n" + SHARED_RULES


def build_prompt_d(*, tool_num: str, tool_name: str, brief: str, prior: str) -> str:
    ref = _ref_section_9()
    return dedent(
        f"""
        Sections 1-8 already written:

        ```markdown
        {prior}
        ```

        ---

        REFERENCE: section 9 from TOOL-008 (25 user stories with concrete details).
        Match this density. DO NOT copy content — adapt to the new tool.

        {ref}

        ---

        TOOL BRIEF:

        {brief.strip()}

        ---

        Now write SECTION 9 ONLY for TOOL-{tool_num}-{tool_name}.md.

        ## 9. User Stories

        EXACTLY 25 stories in 5 sub-sections of 5 each:

        ### 9.1 <theme A> (US-01 .. US-05)
        ### 9.2 <theme B> (US-06 .. US-10)
        ### 9.3 <theme C> (US-11 .. US-15)
        ### 9.4 <theme D> (US-16 .. US-20)
        ### 9.5 <theme E> (US-21 .. US-25)

        Each theme must be DIFFERENT and cover a different aspect:
        - 9.1: Core functionality
        - 9.2: A second aspect (security, lifecycle, integration, etc.)
        - 9.3: Edge cases / error handling
        - 9.4: Integration with other tools
        - 9.5: Performance / observability

        Each story format (mimic TOOL-008 EXACTLY):

        **US-NN: <short concrete title>**
        - **As a** <specific role like "dev integrating Stripe">
        - **I want** <specific action>
        - **So that** <specific benefit>
        - **Given:** <concrete preconditions with values, route paths, status codes>
        - **When:** <concrete action with HTTP method + path or function call with args>
        - **Then:**
          - <bullet 1: concrete observable outcome>
          - <bullet 2: another concrete outcome>
          - <bullet 3: optional third outcome>

        Each story MUST be 7-12 lines.
        Each story MUST contain at least 2 concrete values (route path, status code,
        function name, file path, env var, schema field). NEVER generic templates like
        "Given an existing API / When I add v2 / Then both versions work".

        ⚠️ CRITICAL — CROSS-REFERENCES: At least 12 of the 25 stories (48%) must
        contain an explicit cross-reference to an invariant (INV-XX-NN), a completeness
        criterion (CC-NN), or a test case (T-NN) from sections 5-8 above.
        The reviewer REJECTS if < 40% of stories have a cross-reference.
        Embed them naturally in the "Then:" bullets, e.g.:
          - Response matches pre-versioning format exactly (INV-VER-06)
          - Performance within 0.1ms overhead (CC-22)
          - Verified by T-03, T-04

        Stop immediately after US-25's closing bullet. Do NOT include section 10.
        Do NOT add a `---` separator. Output ONLY markdown.
        Start with `## 9. User Stories` on line 1.
        """
    ).strip()


# ============================================================================
# CALL E — Section 10 ALONE (30 Test Plan)
# ============================================================================
SYSTEM_E = dedent(
    """
    You are continuing a rigorous engineering specification. You will produce ONLY
    section 10 (Test Plan): exactly 30 unique tests T-01..T-30 in 5-6 sub-sections.
    Every invariant from section 8 MUST have at least one matching test.
    """
).strip() + "\n\n" + SHARED_RULES


def build_prompt_e(*, tool_num: str, tool_name: str, brief: str, prior: str) -> str:
    ref = _ref_section_10()
    return dedent(
        f"""
        Sections 1-9 already written:

        ```markdown
        {prior}
        ```

        ---

        REFERENCE: section 10 from TOOL-008 (30 concrete test cases).
        Match this density. DO NOT copy content — adapt to the new tool.

        {ref}

        ---

        TOOL BRIEF:

        {brief.strip()}

        ---

        Now write SECTION 10 ONLY for TOOL-{tool_num}-{tool_name}.md.

        ## 10. Test Plan

        EXACTLY 30 unique tests T-01..T-30, distributed across 5-6 sub-sections.

        ### 10.1 <category 1> (e.g. Functional / Routing / Verification)
        ### 10.2 <category 2>
        ### 10.3 <category 3>
        ### 10.4 <category 4>
        ### 10.5 <category 5>
        (### 10.6 optional)

        Each sub-section is a markdown table:

        | # | Test | Setup | Action | Expected |
        |---|------|-------|--------|----------|
        | T-XX | <short title> | <concrete setup> | <concrete action> | <concrete expected result> |

        Distribute the 30 tests so that EVERY invariant INV-XX-NN from section 8 has
        at least one corresponding test (look at section 8 above and ensure coverage).

        Each row must have CONCRETE values:
        - Setup: e.g. "3 items, 1 deleted; user A authenticated"
        - Action: e.g. "GET /api/v1/items/?limit=10"
        - Expected: e.g. "200, data=[2 items], count=2, no deleted in response"

        NEVER vague ("test the feature works", "verify behavior").

        Stop immediately after the last row of T-30. Do NOT include section 11.
        Do NOT add a `---` separator. Output ONLY markdown.
        Start with `## 10. Test Plan` on line 1.
        """
    ).strip()


# ============================================================================
# CALL F — Sections 11-16 (Operations)
# ============================================================================
SYSTEM_F = dedent(
    """
    You are completing a rigorous engineering specification. You will produce
    sections 11 through 16. These cover interaction with other tools, rollback,
    edge cases, acceptance criteria, implementation checklist, and the documentation
    output JSON.
    """
).strip() + "\n\n" + SHARED_RULES


def build_prompt_f(*, tool_num: str, tool_name: str, brief: str, prior: str) -> str:
    ref_13 = _ref_section_13()
    ref_15 = _ref_section_15()
    ref_16 = _ref_section_16()
    return dedent(
        f"""
        Sections 1-10 already written:

        ```markdown
        {prior}
        ```

        ---

        REFERENCE: section 13 from TOOL-008 (15 concrete edge cases):

        {ref_13}

        ---

        REFERENCE: section 15 from TOOL-008 (granular implementation checklist):

        {ref_15}

        ---

        REFERENCE: section 16 from TOOL-008 (full Documentation Output JSON):

        {ref_16}

        ---

        TOOL BRIEF:

        {brief.strip()}

        ---

        Now write SECTIONS 11 THROUGH 16 for TOOL-{tool_num}-{tool_name}.md.

        ## 11. Interaction Matrix

        Markdown table with AT LEAST 15 rows showing how this tool interacts with
        other tools in SKILL-001. You MUST include rows for ALL of these tools:
        add_soft_delete, add_cursor_pagination, add_search, add_audit_log,
        add_data_export, add_bulk_operations, add_multi_tenancy, add_feature_flags,
        add_api_key_auth, add_oauth2_provider, add_rbac, add_mfa, add_cache_layer,
        add_outbox_pattern, add_sse.
        Columns:

        | Other tool | Order matters? | Interaction | Notes |

        The "Order matters?" column must be either "Yes" or "No" with a concrete
        reason. The "Interaction" column must be ✅ Compatible or ⚠️ Caveat.
        The "Notes" column must be a FULL sentence explaining why.

        End with a `**Conflicts:**` section listing conflicts (or "None identified.").

        ## 12. Rollback Procedure

        FIVE sub-sections. EACH must contain real commands in fenced blocks.

        ### Code rollback (before deploy)
        Real `git checkout` and `rm -rf` commands listing EVERY file created/modified.

        ### Database rollback (after deploy)
        If tool creates DB objects: `alembic downgrade -1` + explain what drops.
        If tool is CODE-ONLY and does NOT touch the DB: write this EXACTLY:

        **N/A** — this tool is a code-only refactor. No database tables, columns, or
        indexes are created. `alembic downgrade -1` would be a no-op. Skip this step.

        ⚠️ CRITICAL: Do NOT write `echo "No data..."` or `SELECT 'No changes...'`
        or any other fake command. The reviewer AUTOMATICALLY REJECTS any line that
        matches `echo "No` or `SELECT 'No`. Use the exact N/A format above.

        ### Data preservation rollback
        If tool creates persistent data: show SQL to archive it.
        If code-only: write: **N/A** — no business data is created or migrated
        by this tool. Nothing to archive.

        ⚠️ Same rule: NEVER `echo "No..."`. ALWAYS use **N/A** text.

        ### Failure mode: tool partially modified files
        Concrete recovery: `git status`, `git checkout`, `rm` commands.

        ### Emergency: <relevant emergency scenario>
        1-3 step concrete procedure.

        ## 13. Edge Cases

        Markdown table with EXACTLY 15 rows EC-1..EC-15. Columns: #, Scenario, Expected behavior.
        Each Expected MUST be a complete sentence of at least 6 words (the reviewer
        rejects columns with < 5 words). NEVER write just "Error" or "Rejected".
        Write: "Tool errors with message: 'Alembic not initialized. Run alembic init.'"

        ## 14. Acceptance Criteria (Final Sign-off)

        Numbered list of EXACTLY 10 items, each prefixed with `✅`. Items 1-9 are
        mechanical (CC verified, tests pass, performance met, etc.). Item 10 must be
        a concrete real-world action a developer must perform end-to-end.

        ## 15. Implementation Checklist (Ultra-granular)

        AT LEAST 13 sub-sections (### 15.1 .. ### 15.13+).

        ⚠️ CRITICAL: Each sub-section MUST have AT LEAST 7 checkbox items `- [ ]`.
        NOT 5, NOT 6 — AT LEAST 7. The reviewer multiplies sub-sections × items and
        rejects if total < 85. With 13 sub-sections × 7 items = 91 you have margin.

        Sub-sections MUST include ALL of these (in any order):
        1. Pre-flight checks (validate project, detect existing setup)
        2. Settings (config.py additions)
        3. Models (SQLAlchemy models)
        4. Helper/core modules (utils, constants, decorators)
        5. CRUD layer (database operations)
        6. Pydantic schemas (request/response models)
        7. Routes (FastAPI endpoints)
        8. Middleware or dependencies (if applicable)
        9. Migration (Alembic file generation)
        10. Test generation (test file with all 30 cases)
        11. Atomicity (rollback on failure)
        12. Documentation (KNOWLEDGE.md, manifest.yaml, SKILL.md)
        13. Verification (ast.parse, pytest, benchmarks, idempotency)

        ## 16. Documentation Output

        Single ```json fenced block with the success report. MUST include:
        - status: "success"
        - files_created: list of >= 8 absolute-relative paths
        - files_modified: list of >= 3 paths
        - metrics: object with execution_time_ms, files_changed, lines_added, lines_removed,
          plus 2-4 tool-specific metrics
        - next_steps: list of >= 5 concrete commands or actions
        - warnings: list of >= 2 specific gotchas
        - notes: list of >= 4 facts about what was installed

        The very LAST line of your output MUST be the closing ``` fence of the JSON block.
        Stop immediately after that. Output ONLY the markdown.
        Start with `## 11. Interaction Matrix` on line 1.
        Total section 11-16 output: target 300-400 lines.
        """
    ).strip()


# ============================================================================
# Orchestration
# ============================================================================
@dataclass
class CallSpec:
    name: str
    system_prompt: str
    build_prompt_fn: Callable
    max_tokens: int
    target_min_lines: int


@dataclass
class MultiCallResult:
    sections: dict[str, str] = field(default_factory=dict)
    full_spec: str = ""
    total_cost_usd: float = 0.0
    total_elapsed_seconds: float = 0.0
    total_completion_tokens: int = 0
    total_prompt_tokens: int = 0
    calls: list[CompletionResult] = field(default_factory=list)
    call_models: list[str] = field(default_factory=list)


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```markdown\n"):
        text = text[len("```markdown\n"):]
    elif text.startswith("```\n"):
        text = text[4:]
    if text.endswith("\n```"):
        text = text[:-4]
    return text


def generate_six_call(
    *,
    tool_num: str,
    tool_name: str,
    brief: str,
    date: str = "2026-04-08",
    model: str = "deepseek/deepseek-chat",
    temperature: float = 0.3,
    timeout: int = 600,
    progress_print: bool = True,
) -> MultiCallResult:
    """
    6-call generation pipeline. Returns concatenated full spec.
    """
    out = MultiCallResult()

    def _call(label: str, system: str, prompt: str, max_tokens: int) -> str:
        if progress_print:
            print(f"[multi] call {label}: prompt={len(prompt)} chars, max_tokens={max_tokens}", flush=True)
        res = call_deepseek(
            prompt,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
            system_prompt=system,
        )
        out.calls.append(res)
        out.call_models.append(model)
        out.total_cost_usd += res.cost_usd
        out.total_elapsed_seconds += res.elapsed_seconds
        out.total_completion_tokens += res.completion_tokens
        out.total_prompt_tokens += res.prompt_tokens
        content = _strip_fences(res.content).strip()
        if progress_print:
            lines = len(content.splitlines())
            print(
                f"[multi] call {label} done: {res.elapsed_seconds:.0f}s "
                f"completion_tok={res.completion_tokens} lines={lines} "
                f"cost=${res.cost_usd:.4f}",
                flush=True,
            )
        return content

    # Call A — Header
    prompt_a = build_prompt_a(tool_num=tool_num, tool_name=tool_name, brief=brief, date=date)
    section_a = _call("A header", SYSTEM_A, prompt_a, max_tokens=4_000)
    out.sections["A"] = section_a

    # Call B — Code Examples
    prompt_b = build_prompt_b(
        tool_num=tool_num,
        tool_name=tool_name,
        brief=brief,
        header=section_a,
    )
    section_b = _call("B code", SYSTEM_B, prompt_b, max_tokens=8_000)
    out.sections["B"] = section_b

    # Call C — Standards
    header_and_code = section_a + "\n\n---\n\n" + section_b
    prompt_c = build_prompt_c(
        tool_num=tool_num,
        tool_name=tool_name,
        brief=brief,
        header_and_code=header_and_code,
    )
    section_c = _call("C standards", SYSTEM_C, prompt_c, max_tokens=8_000)
    out.sections["C"] = section_c

    # Call D — Stories
    prior_d = header_and_code + "\n\n---\n\n" + section_c
    prompt_d = build_prompt_d(
        tool_num=tool_num,
        tool_name=tool_name,
        brief=brief,
        prior=prior_d,
    )
    section_d = _call("D stories", SYSTEM_D, prompt_d, max_tokens=10_000)
    out.sections["D"] = section_d

    # Call E — Tests
    prior_e = prior_d + "\n\n---\n\n" + section_d
    prompt_e = build_prompt_e(
        tool_num=tool_num,
        tool_name=tool_name,
        brief=brief,
        prior=prior_e,
    )
    section_e = _call("E tests", SYSTEM_E, prompt_e, max_tokens=6_000)
    out.sections["E"] = section_e

    # Call F — Operations
    prior_f = prior_e + "\n\n---\n\n" + section_e
    prompt_f = build_prompt_f(
        tool_num=tool_num,
        tool_name=tool_name,
        brief=brief,
        prior=prior_f,
    )
    section_f = _call("F operations", SYSTEM_F, prompt_f, max_tokens=10_000)
    out.sections["F"] = section_f

    # Concatenate
    full = (
        section_a
        + "\n\n---\n\n"
        + section_b
        + "\n\n---\n\n"
        + section_c
        + "\n\n---\n\n"
        + section_d
        + "\n\n---\n\n"
        + section_e
        + "\n\n---\n\n"
        + section_f
        + "\n"
    )

    if full.count("```") % 2 == 1:
        full = full.rstrip() + "\n```\n"

    out.full_spec = full
    return out


# ============================================================================
# Section refinement (used by run.py refinement loop)
# ============================================================================
def _refine_call(
    *,
    label: str,
    base_prompt: str,
    system_prompt: str,
    current_section: str,
    review_feedback: str,
    model: str,
    max_tokens: int,
    temperature: float = 0.3,
    timeout: int = 600,
) -> tuple[str, CompletionResult]:
    """Generic refinement: re-call a section with explicit feedback."""
    extra = dedent(
        f"""

        ---

        ## REVIEWER FEEDBACK ON YOUR PREVIOUS ATTEMPT FOR {label}

        Your previous output had these BLOCKING issues:
        {review_feedback}

        Your previous output for {label} was:

        ```markdown
        {current_section}
        ```

        Rewrite the section(s) fixing ALL of the above issues. The output must
        match or exceed the gold reference density. Do not abbreviate. Do not
        repeat the same content — actually expand and fix the specific gaps listed.
        """
    )
    res = call_deepseek(
        base_prompt + extra,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
        system_prompt=system_prompt,
    )
    return _strip_fences(res.content).strip(), res


def refine_section_a(
    *,
    tool_num: str,
    tool_name: str,
    brief: str,
    current_section: str,
    review_feedback: str,
    date: str = "2026-04-08",
    model: str = "deepseek/deepseek-chat",
    temperature: float = 0.3,
) -> tuple[str, CompletionResult]:
    base = build_prompt_a(tool_num=tool_num, tool_name=tool_name, brief=brief, date=date)
    return _refine_call(
        label="sections 1-3 (header)",
        base_prompt=base,
        system_prompt=SYSTEM_A,
        current_section=current_section,
        review_feedback=review_feedback,
        model=model,
        max_tokens=5_000,
        temperature=temperature,
    )


def refine_section_c(
    *,
    tool_num: str,
    tool_name: str,
    brief: str,
    header_and_code: str,
    current_section: str,
    review_feedback: str,
    model: str = "deepseek/deepseek-chat",
    temperature: float = 0.3,
) -> tuple[str, CompletionResult]:
    base = build_prompt_c(
        tool_num=tool_num,
        tool_name=tool_name,
        brief=brief,
        header_and_code=header_and_code,
    )
    return _refine_call(
        label="sections 5-8 (standards)",
        base_prompt=base,
        system_prompt=SYSTEM_C,
        current_section=current_section,
        review_feedback=review_feedback,
        model=model,
        max_tokens=10_000,
        temperature=temperature,
    )


def refine_section_d(
    *,
    tool_num: str,
    tool_name: str,
    brief: str,
    prior: str,
    current_section: str,
    review_feedback: str,
    model: str = "deepseek/deepseek-chat",
    temperature: float = 0.3,
) -> tuple[str, CompletionResult]:
    base = build_prompt_d(tool_num=tool_num, tool_name=tool_name, brief=brief, prior=prior)
    return _refine_call(
        label="section 9 (user stories)",
        base_prompt=base,
        system_prompt=SYSTEM_D,
        current_section=current_section,
        review_feedback=review_feedback,
        model=model,
        max_tokens=12_000,
        temperature=temperature,
    )


def refine_section_e(
    *,
    tool_num: str,
    tool_name: str,
    brief: str,
    prior: str,
    current_section: str,
    review_feedback: str,
    model: str = "deepseek/deepseek-chat",
    temperature: float = 0.3,
) -> tuple[str, CompletionResult]:
    base = build_prompt_e(tool_num=tool_num, tool_name=tool_name, brief=brief, prior=prior)
    return _refine_call(
        label="section 10 (test plan)",
        base_prompt=base,
        system_prompt=SYSTEM_E,
        current_section=current_section,
        review_feedback=review_feedback,
        model=model,
        max_tokens=8_000,
        temperature=temperature,
    )


def refine_section_b(
    *,
    tool_num: str,
    tool_name: str,
    brief: str,
    header: str,
    current_section: str,
    review_feedback: str,
    model: str = "deepseek/deepseek-r1",
    temperature: float = 0.3,
    timeout: int = 600,
) -> tuple[str, CompletionResult]:
    """Re-call section 4 with explicit feedback. Used when reviewer detects issues."""
    base = build_prompt_b(tool_num=tool_num, tool_name=tool_name, brief=brief, header=header)
    extra = dedent(
        f"""

        ---

        ## REVIEWER FEEDBACK ON YOUR PREVIOUS ATTEMPT

        Your previous output had these issues:
        {review_feedback}

        Your previous output was:

        ```markdown
        {current_section}
        ```

        Rewrite section 4 fixing ALL of the above issues. Make Before/After pairs
        SHOW REAL DIFFERENCES. Add MORE code blocks if you had fewer than 6.
        Make every block 10-40 lines of REAL Python.
        """
    )
    res = call_deepseek(
        base + extra,
        model=model,
        max_tokens=10_000,
        temperature=temperature,
        timeout=timeout,
        system_prompt=SYSTEM_B,
    )
    return _strip_fences(res.content).strip(), res


def refine_section_f(
    *,
    tool_num: str,
    tool_name: str,
    brief: str,
    prior: str,
    current_section: str,
    review_feedback: str,
    model: str = "deepseek/deepseek-chat",
    temperature: float = 0.3,
    timeout: int = 600,
) -> tuple[str, CompletionResult]:
    """Re-call sections 11-16 with explicit feedback. Used when 11 or 15 are thin."""
    base = build_prompt_f(tool_num=tool_num, tool_name=tool_name, brief=brief, prior=prior)
    extra = dedent(
        f"""

        ---

        ## REVIEWER FEEDBACK ON YOUR PREVIOUS ATTEMPT

        Your previous output had these issues:
        {review_feedback}

        Your previous output was:

        ```markdown
        {current_section}
        ```

        Rewrite sections 11-16 fixing ALL of the above issues.
        - Section 11 Interaction Matrix: produce AT LEAST 12 data rows.
          List interactions with ALL of: add_soft_delete, add_cursor_pagination,
          add_search, add_audit_log, add_data_export, add_bulk_operations,
          add_multi_tenancy, add_feature_flags, add_api_key_auth, add_oauth2_provider,
          add_rbac, add_mfa, add_cache_layer, add_circuit_breaker, add_outbox_pattern,
          add_long_running_task, add_sse, add_webhook_sender, add_webhook_receiver.
          Pick the 12+ most relevant.
        - Section 15 Implementation Checklist: produce AT LEAST 13 sub-sections,
          each with AT LEAST 6 checkbox items. Total >= 78 checkbox items.
        - Keep all the other sections (12, 13, 14, 16) at high density too.
        - Total length 280-380 lines.
        """
    )
    res = call_deepseek(
        base + extra,
        model=model,
        max_tokens=12_000,
        temperature=temperature,
        timeout=timeout,
        system_prompt=SYSTEM_F,
    )
    return _strip_fences(res.content).strip(), res
