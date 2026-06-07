"""Internal: orchestration (generate_six_call + refine_section_*).

Split out of multi_call.py to keep modules <=500 LOC. Not a public API; import
from `spec_orchestrator.multi_call` instead.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from textwrap import dedent

from spec_orchestrator.client import CompletionResult, call_deepseek
from spec_orchestrator.multi_call__impl1 import (
    SYSTEM_A,
    SYSTEM_B,
    SYSTEM_C,
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
        text = text[len("```markdown\n") :]
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
            print(
                f"[multi] call {label}: prompt={len(prompt)} chars, max_tokens={max_tokens}",
                flush=True,
            )
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
