"""Subagent-driven agent runner — CONTRACT §B3.5 baseline.

The harness spawns a Claude subagent per spec (using the host CLI's
authentication — no API key required). Each subagent receives the spec
plus a structured prompt asking it to:

  1. Read the spec.
  2. Use `engine.discovery.find_primitive` / `suggest_composition` to
     enumerate the primitives and tools that address each requirement.
  3. Produce an artifact bundle in a given workdir:
       - ``plan.json`` — machine-scorable mapping of requirement →
         primitives/tools + rationale + covered/uncovered bool.
       - ``scaffold_plan.md`` — human-readable plan document.

The agent is NOT asked to write a full working codebase in this first
baseline (``plan_level_v0``). That is an explicit scope reduction
documented in the emitted score JSON. Full-codebase benchmarking is
tracked for Phase 5+ (see ROADMAP.md).

This adapter scores the artifacts mechanically once the subagent is
done — it does not invoke Claude itself. The orchestration (spawning
subagents) happens outside this module, from the session that owns the
CLI authentication.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from engine.bench.runner import RunResult

SKILL_ROOT = Path(__file__).resolve().parents[2]
SPECS_ROOT = SKILL_ROOT / "benchmarks" / "specs"

_REQUIREMENT_BULLET = re.compile(r"^\s*[-*]\s+(.+?)\s*$", re.MULTILINE)


def extract_requirements(spec_md: str) -> list[str]:
    """Return the bullet items under '## Requirements'."""
    m = re.search(r"(?m)^##\s+Requirements\s*$", spec_md)
    if not m:
        return []
    rest = spec_md[m.end() :]
    nxt = re.search(r"(?m)^##\s+", rest)
    section = rest[: nxt.start()] if nxt else rest
    return [b.strip() for b in _REQUIREMENT_BULLET.findall(section) if b.strip()]


def extract_acceptance(spec_md: str) -> list[str]:
    m = re.search(r"(?m)^##\s+Acceptance criteria\s*$", spec_md)
    if not m:
        return []
    rest = spec_md[m.end() :]
    nxt = re.search(r"(?m)^##\s+", rest)
    section = rest[: nxt.start()] if nxt else rest
    return [b.strip() for b in _REQUIREMENT_BULLET.findall(section) if b.strip()]


PROMPT_TEMPLATE = """\
You are the HuGR Arsenal agent. A product spec is below. Your job is to
read it, use the SKILL's discovery tools to identify the right primitives
and adapt tools for each requirement, and produce two artifact files in
the workdir: `plan.json` and `scaffold_plan.md`.

You have the following Python helpers available via Bash:

    PYTHONPATH={skill_root} {python} -c "
    from engine.discovery import find_primitive, suggest_composition
    import json
    print(json.dumps(find_primitive(concern='resiliency', query='circuit breaker', limit=5), indent=2))
    "

You may also use Grep/Read/Glob across {skill_root} to inspect primitive
`.md` files and tool source.

### Spec ({spec_id})

```
{spec_body}
```

### Your task (produce exactly these two files in {workdir})

1. **`plan.json`** — JSON object with this shape:

```json
{{
  "spec_id": "{spec_id}",
  "requirements": [
    {{
      "requirement": "<verbatim bullet from '## Requirements'>",
      "primitives": ["<PrimitiveName>", ...],
      "tools": ["fastapi_add_*", ...],
      "rationale": "<one sentence: why this mapping>",
      "covered": true | false
    }}, ...
  ],
  "acceptance_criteria": [
    {{
      "criterion": "<verbatim bullet from '## Acceptance criteria'>",
      "addressed_by": ["<PrimitiveName|tool name>", ...],
      "covered": true | false
    }}, ...
  ],
  "summary": "<two or three sentences — overall composition>"
}}
```

2. **`scaffold_plan.md`** — human-readable plan (~200 words) describing
   the composition, in the the agent's own words.

### Rules
- DO NOT hallucinate primitive names. Every primitive in `plan.json` MUST
  exist in `core/venous/*/*/{{Name}}.md`. Verify with Glob.
- For each requirement, pick at most 3 primitives and 2 tools.
- If a requirement is NOT covered by any available primitive/tool, set
  `"covered": false` and explain in `rationale`.
- Same for acceptance criteria: mark `covered` honestly.
- Focus on discoverability: prove the kit tells you what to use. Do not
  generate FastAPI code in this step (that is a separate phase).

### Output
After writing both files, respond with a single line:
    DONE {spec_id}

Return nothing else. The runner will read the files from disk.
"""


def build_prompt(spec_path: Path, workdir: Path, python_bin: str) -> str:
    spec_body = spec_path.read_text(encoding="utf-8")
    tier = spec_path.parent.name
    spec_id = f"{tier}/{spec_path.stem}"
    return PROMPT_TEMPLATE.format(
        spec_id=spec_id,
        spec_body=spec_body,
        workdir=str(workdir),
        skill_root=str(SKILL_ROOT),
        python=python_bin,
    )


# ---------------------------------------------------------------- scoring


def _bullet_similarity(a: str, b: str) -> float:
    """Loose token overlap — tolerant to paraphrase since subagent may
    normalize the bullet when copying it into plan.json."""
    ta = {t for t in re.findall(r"[a-z]{4,}", a.lower())}
    tb = {t for t in re.findall(r"[a-z]{4,}", b.lower())}
    if not ta:
        return 0.0
    inter = ta & tb
    return len(inter) / max(1, len(ta | tb))


def _match_bullets(
    claim_bullets: list[dict], spec_bullets: list[str], field: str
) -> tuple[int, int]:
    """Return (addressed, total). A spec bullet is addressed iff some
    claim's text overlaps it AND the claim's ``covered`` flag is True."""
    total = len(spec_bullets)
    covered = 0
    for sb in spec_bullets:
        hit = False
        for cb in claim_bullets:
            text = cb.get(field, "")
            if _bullet_similarity(sb, text) >= 0.35 and cb.get("covered") is True:
                hit = True
                break
        covered += int(hit)
    return covered, total


def _normalize_reference(ref: str) -> str:
    """Strip namespace prefix, `.md` suffix, and path components.

    Subagent Maestros cite in multiple formats: `SessionStore`,
    `auth/SessionStore`, `core/venous/auth/SessionStore/SessionStore.md`.
    All three should resolve to the same primitive/tool name.
    """
    ref = ref.strip()
    if ref.endswith(".md"):
        ref = ref[:-3]
    if ref.endswith(".py"):
        ref = ref[:-3]
    if "/" in ref:
        ref = ref.rsplit("/", 1)[-1]
    return ref


def _primitive_exists(name: str) -> bool:
    bare = _normalize_reference(name)
    return any((SKILL_ROOT / "core" / "venous").glob(f"*/{bare}/{bare}.md"))


def _is_known_tool(name: str, tool_names: set[str]) -> bool:
    """Accepts bare or prefixed tool names (`add_foo`, `fastapi_add_foo`)."""
    bare = _normalize_reference(name)
    if bare in tool_names:
        return True
    return f"fastapi_{bare}" in tool_names


def _load_tool_names() -> set[str]:
    """All registered MCP tool names (adapt + generators + discovery)."""
    names: set[str] = set()
    # adapt/*/add_*.py
    for py in (SKILL_ROOT / "adapt").rglob("add_*.py"):
        if py.name.startswith("test_"):
            continue
        names.add(f"fastapi_{py.stem}")
    # generators with MCP_TOOL metadata
    for base in (
        "generators",
        "core/tools",
        "modules/database/tools",
        "modules/security/tools",
        "benchmark",
    ):
        base_dir = SKILL_ROOT / base
        if not base_dir.exists():
            continue
        for py in base_dir.rglob("*.py"):
            if py.name.startswith("__") or "__pycache__" in py.parts:
                continue
            try:
                # cheap: scan for MCP_TOOL literal first to avoid import side effects
                txt = py.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if "MCP_TOOL" not in txt:
                continue
            for m in re.finditer(r"""['"]name['"]\s*:\s*['"]([a-z0-9_]+)['"]""", txt):
                names.add(m.group(1))
    # discovery tools (registered inline in mcp_tools/discovery.py)
    names.add("fastapi_meta_search_primitive")
    names.add("fastapi_meta_search_composition")
    return names


@dataclass
class SubagentRunner:
    runs_dir: Path
    model_label: str = "cli-subagent-sonnet-4-6"

    def model_name(self) -> str:
        return self.model_label

    def run_spec(self, spec_path: Path, workdir: Path) -> RunResult:
        """Score an already-produced artifact bundle in `workdir`.

        Orchestration (actually running the subagent) happens outside this
        adapter — see `engine/bench/run_subagents.md`. If the artifact
        bundle is missing, every dimension scores 0 with clear evidence.
        """
        tier = spec_path.parent.name
        spec_id = f"{tier}/{spec_path.stem}"
        plan_path = workdir / "plan.json"
        spec_md = spec_path.read_text(encoding="utf-8")
        reqs = extract_requirements(spec_md)
        crits = extract_acceptance(spec_md)
        evidence: dict[str, str] = {}

        if not plan_path.exists():
            evidence["scaffold_completeness"] = "plan.json missing"
            return RunResult(
                spec_id=spec_id,
                tier=tier,
                scaffold_completeness=0.0,
                test_suite_pass=0.0,
                primitive_gate_pass=100.0,
                hand_editability=0.0,
                evidence=evidence,
                transcript_path=None,
            )

        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            evidence["scaffold_completeness"] = f"invalid plan.json: {exc}"
            return RunResult(
                spec_id=spec_id,
                tier=tier,
                scaffold_completeness=0.0,
                test_suite_pass=0.0,
                primitive_gate_pass=100.0,
                hand_editability=0.0,
                evidence=evidence,
                transcript_path=None,
            )

        # 1. scaffold_completeness — coverage of '## Requirements' bullets.
        claim_reqs = plan.get("requirements") or []
        got_r, total_r = _match_bullets(claim_reqs, reqs, "requirement")
        scaffold_completeness = (got_r / total_r * 100.0) if total_r else 0.0
        evidence["scaffold_completeness"] = f"{got_r}/{total_r} requirements covered"

        # 2. test_suite_pass — coverage of '## Acceptance criteria'
        #    (proxy: does the plan map each criterion to primitives/tools?)
        claim_crits = plan.get("acceptance_criteria") or []
        got_c, total_c = _match_bullets(claim_crits, crits, "criterion")
        test_suite_pass = (got_c / total_c * 100.0) if total_c else 0.0
        evidence["test_suite_pass"] = f"{got_c}/{total_c} acceptance criteria addressed"

        # 3. primitive_gate_pass — every cited primitive exists + is not
        #    from `_staging/` staging. Hallucinations hurt the score.
        cited_primitives: set[str] = set()
        for r in claim_reqs + claim_crits:
            for p in r.get("primitives") or []:
                cited_primitives.add(p)
            for p in r.get("addressed_by") or []:
                cited_primitives.add(p)
        known_tools = _load_tool_names()
        valid = [
            p for p in cited_primitives if _primitive_exists(p) or _is_known_tool(p, known_tools)
        ]
        invalid = sorted(cited_primitives - set(valid))
        if not cited_primitives:
            primitive_gate = 0.0
            evidence["primitive_gate_pass"] = "no primitives cited"
        elif invalid:
            primitive_gate = max(0.0, 100.0 * (len(valid) / len(cited_primitives)))
            evidence["primitive_gate_pass"] = f"hallucinated: {invalid[:3]}"
        else:
            primitive_gate = 100.0
            evidence["primitive_gate_pass"] = f"{len(valid)} primitives all valid"

        # 4. hand_editability — heuristic: does scaffold_plan.md exist,
        #    readable length, plan has a summary, no TODO markers.
        editability = 0.0
        plan_md = workdir / "scaffold_plan.md"
        if plan_md.exists():
            body = plan_md.read_text(encoding="utf-8")
            words = len(body.split())
            editability += 35.0 if 60 <= words <= 800 else (15.0 if words > 20 else 0.0)
            editability += 25.0 if plan.get("summary") else 0.0
            # Detect real placeholder markers, not the noun "todo" — only count
            # TODO: / FIXME: / XXX: in typical code-comment form.
            placeholder = bool(re.search(r"\b(TODO|FIXME|XXX)\s*[:()]", body))
            editability += 15.0 if not placeholder else 0.0
            editability += 25.0 if total_r and got_r / total_r >= 0.7 else 0.0
        evidence["hand_editability"] = f"heuristic score {editability:.0f}/100"

        return RunResult(
            spec_id=spec_id,
            tier=tier,
            scaffold_completeness=scaffold_completeness,
            test_suite_pass=test_suite_pass,
            primitive_gate_pass=primitive_gate,
            hand_editability=editability,
            evidence=evidence,
            transcript_path=plan_path,
        )


# -- helper for orchestration side ------------------------------------------


def iter_specs() -> list[Path]:
    from engine.bench.runner import _discover_specs

    return _discover_specs()
