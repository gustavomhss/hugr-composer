"""Internal: prompt builders D/E/F (stories, test plan, operations).

Split out of multi_call.py to keep modules <=500 LOC. Not a public API; import
from `spec_orchestrator.multi_call` instead.
"""

from __future__ import annotations

from textwrap import dedent

from spec_orchestrator.multi_call__impl1 import (
    SHARED_RULES,
    _ref_section_9,
    _ref_section_10,
    _ref_section_13,
    _ref_section_15,
    _ref_section_16,
)

# ============================================================================
# CALL D — Section 9 ALONE (25 User Stories)
# ============================================================================
SYSTEM_D = (
    dedent(
        """
    You are continuing a rigorous engineering specification. You will produce ONLY
    section 9 (User Stories): exactly 25 stories in 5 sub-sections of 5 each.
    Stories must cross-reference the tool's invariants from section 8.
    """
    ).strip()
    + "\n\n"
    + SHARED_RULES
)


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
SYSTEM_E = (
    dedent(
        """
    You are continuing a rigorous engineering specification. You will produce ONLY
    section 10 (Test Plan): exactly 30 unique tests T-01..T-30 in 5-6 sub-sections.
    Every invariant from section 8 MUST have at least one matching test.
    """
    ).strip()
    + "\n\n"
    + SHARED_RULES
)


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
SYSTEM_F = (
    dedent(
        """
    You are completing a rigorous engineering specification. You will produce
    sections 11 through 16. These cover interaction with other tools, rollback,
    edge cases, acceptance criteria, implementation checklist, and the documentation
    output JSON.
    """
    ).strip()
    + "\n\n"
    + SHARED_RULES
)


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
