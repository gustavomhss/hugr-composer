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

Implementation is split across multi_call__impl1/2/3 to keep each module under
the 500-LOC cap. This module re-exports the public API unchanged.
"""

from __future__ import annotations

from spec_orchestrator.client import CompletionResult
from spec_orchestrator.multi_call__impl1 import (
    GOLD_TOOL_001,
    GOLD_TOOL_008,
    REPO_ROOT,
    SHARED_RULES,
    SYSTEM_A,
    SYSTEM_B,
    SYSTEM_C,
    _extract_section,
    _gold_excerpt,
    _ref_section_4,
    _ref_section_5,
    _ref_section_6,
    _ref_section_8,
    _ref_section_9,
    _ref_section_10,
    _ref_section_13,
    _ref_section_15,
    _ref_section_16,
    build_prompt_a,
    build_prompt_b,
    build_prompt_c,
)
from spec_orchestrator.multi_call__impl2 import (
    SYSTEM_D,
    SYSTEM_E,
    SYSTEM_F,
    build_prompt_d,
    build_prompt_e,
    build_prompt_f,
)
from spec_orchestrator.multi_call__impl3 import (
    CallSpec,
    MultiCallResult,
    _refine_call,
    _strip_fences,
    generate_six_call,
    refine_section_a,
    refine_section_b,
    refine_section_c,
    refine_section_d,
    refine_section_e,
    refine_section_f,
)

__all__ = [
    "CompletionResult",
    "REPO_ROOT",
    "GOLD_TOOL_001",
    "GOLD_TOOL_008",
    "SHARED_RULES",
    "SYSTEM_A",
    "SYSTEM_B",
    "SYSTEM_C",
    "SYSTEM_D",
    "SYSTEM_E",
    "SYSTEM_F",
    "_extract_section",
    "_gold_excerpt",
    "_ref_section_4",
    "_ref_section_5",
    "_ref_section_6",
    "_ref_section_8",
    "_ref_section_9",
    "_ref_section_10",
    "_ref_section_13",
    "_ref_section_15",
    "_ref_section_16",
    "build_prompt_a",
    "build_prompt_b",
    "build_prompt_c",
    "build_prompt_d",
    "build_prompt_e",
    "build_prompt_f",
    "CallSpec",
    "MultiCallResult",
    "_strip_fences",
    "_refine_call",
    "generate_six_call",
    "refine_section_a",
    "refine_section_b",
    "refine_section_c",
    "refine_section_d",
    "refine_section_e",
    "refine_section_f",
]
