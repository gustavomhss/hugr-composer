"""
Single-primitive briefing — one Sonnet agent per primitive, focused mission.

After the batched dispatch revealed that 8-14 primitives / batch / agent-turn
is too wide (agents honestly halt at 0-2 green of their batch), the correct
sharding is one primitive per agent. This module:

- Loads the full catalog (113 primitives from 8 research deliverables).
- Walks `core/venous/` and identifies which primitives already have a
  manifest.json that passes `accept_delivery()`.
- Emits a `SinglePrimitiveBriefing` for every remaining primitive.
- Renders a tight, focused prompt per primitive.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

HERE = Path(__file__).resolve().parent
ENGINE_ROOT = HERE.parent
SKILL_ROOT = ENGINE_ROOT.parent
REPO_ROOT = SKILL_ROOT.parent.parent
RESEARCH_OUT = REPO_ROOT / "docs" / "research" / "outputs"
VENOUS_ROOT = SKILL_ROOT / "core" / "venous"

sys.path.insert(0, str(ENGINE_ROOT))

from contracts.primitive_delivery_contract import Maturity, accept_delivery  # noqa: E402


# ---------------------------------------------------------------------------
# Heuristic: which primitives are stateful (drives T2/T3/T5 applicability).
# Same logic as builder_briefings.py but repeated here so this module is
# self-contained and importable before the batch infrastructure is torn down.
# ---------------------------------------------------------------------------
_STATEFUL_NAMESPACES = frozenset({
    "auth", "data", "events", "jobs", "cache", "resiliency", "llm", "cost",
})
_STATELESS_NAME_PREFIXES = ("Config", "Value", "Semantic", "Resource", "Histogram",
                            "Encryption", "Policy", "Key", "Retention")


def _is_stateful(name: str, namespace: str, api_signature: str) -> bool:
    if namespace not in _STATEFUL_NAMESPACES:
        return False
    for pref in _STATELESS_NAME_PREFIXES:
        if name.startswith(pref):
            return False
    if "async def" in api_signature or "register_" in api_signature or "acquire(" in api_signature:
        return True
    if "dataclass(frozen=True)" in api_signature and "def " not in api_signature.split("class ", 1)[-1]:
        return False
    return True


# ---------------------------------------------------------------------------
# Per-primitive assignment source table — which agent deliverable each
# primitive's PrimitiveSpec came from (needed for the --catalog-entry CLI arg).
# Inherited from builder_briefings.py's _BATCHES partition.
# ---------------------------------------------------------------------------
_CATALOG_SOURCE: dict[str, str] = {}
_AGENT_FILE: dict[int, str] = {
    1: "AGENT_1_FRAMEWORKS.json",
    2: "AGENT_2_DISTRIBUTED.json",
    3: "AGENT_3_PATTERNS.json",
    4: "AGENT_4_RESILIENCY.json",
    5: "AGENT_5_SECURITY.json",
    6: "AGENT_6_COMPLIANCE.json",
    7: "AGENT_7_OBSERVABILITY.json",
    8: "AGENT_8_LLM_ERA.json",
}


def _load_catalog() -> dict[str, dict]:
    """Return `{primitive_name: {**spec, _source_file: filename, _source_agent: id}}`."""
    out: dict[str, dict] = {}
    for p in sorted(RESEARCH_OUT.glob("AGENT_*.json")):
        aid = int(p.stem.split("_")[1])
        data = json.loads(p.read_text())
        for prim in data["primitives"]:
            # First-seen wins (collisions HealthProbe/RateLimiter live in the earlier agent).
            if prim["name"] not in out:
                spec = dict(prim)
                spec["_source_file"] = p.name
                spec["_source_agent"] = aid
                out[prim["name"]] = spec
    return out


# ---------------------------------------------------------------------------
# Delivery state walk — which primitives are already green?
# ---------------------------------------------------------------------------
def _delivered_primitives() -> tuple[set[str], dict[str, str]]:
    """Return (accepted_names, {name: primitive_dir_path}).

    A primitive is 'accepted' iff `core/venous/<ns>/<Name>/<Name>.manifest.json`
    loads and `accept_delivery()` returns ok=True.
    """
    accepted: set[str] = set()
    paths: dict[str, str] = {}
    if not VENOUS_ROOT.is_dir():
        return accepted, paths
    for ns_dir in sorted(VENOUS_ROOT.iterdir()):
        if not ns_dir.is_dir() or ns_dir.name.startswith((".", "_")):
            continue
        for prim_dir in sorted(ns_dir.iterdir()):
            if not prim_dir.is_dir() or prim_dir.name.startswith((".", "_")):
                continue
            manifest = prim_dir / f"{prim_dir.name}.manifest.json"
            if not manifest.exists():
                continue
            try:
                raw = json.loads(manifest.read_text())
            except json.JSONDecodeError:
                continue
            ok, _, _ = accept_delivery(raw)
            if ok:
                accepted.add(prim_dir.name)
                paths[prim_dir.name] = str(prim_dir.relative_to(REPO_ROOT))
    return accepted, paths


# ---------------------------------------------------------------------------
# Schema for a single-primitive briefing
# ---------------------------------------------------------------------------
_OSS_REF_CACHE: dict[str, dict] | None = None


def _load_oss_reference(primitive_name: str) -> str:
    """Return a formatted OSS-reference section, or empty string if no mapping."""
    global _OSS_REF_CACHE  # noqa: PLW0603 — module-level memoization
    if _OSS_REF_CACHE is None:
        ref_path = Path(__file__).parent / "oss_references.json"
        if ref_path.exists():
            raw = json.loads(ref_path.read_text())
            _OSS_REF_CACHE = {k: v for k, v in raw.items() if not k.startswith("_")}
        else:
            _OSS_REF_CACHE = {}
    entry = _OSS_REF_CACHE.get(primitive_name)
    if entry is None:
        return ""
    return (
        "## OSS reference (copy ALGORITHM; adapt to HuGR shell)\n"
        f"- {entry['ref']}\n"
        f"- Notes: {entry['notes']}\n"
    )


class SinglePrimitiveBriefing(BaseModel):
    """Focused mission for one Sonnet builder: one primitive, full 10-tier gate."""

    primitive_name: str = Field(pattern=r"^[A-Z][a-zA-Z0-9]*$", max_length=40)
    namespace: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=30)
    maturity: Maturity
    is_stateful: bool
    source_agent_id: int = Field(ge=1, le=8)
    source_catalog_file: str = Field(pattern=r"^AGENT_\d_[A-Z_]+\.json$")
    catalog_spec: dict
    # Reference exemplars the agent should study (known-green pilot primitives).
    reference_stateless_impl: str = "skills/SKILL-001-fastapi-production/core/venous/obs/Tracer"
    reference_stateful_impl: str = "skills/SKILL-001-fastapi-production/core/venous/data/UnitOfWork"

    @model_validator(mode="after")
    def spec_matches_identity(self) -> "SinglePrimitiveBriefing":
        if self.catalog_spec.get("name") != self.primitive_name:
            raise ValueError(
                f"catalog_spec['name']={self.catalog_spec.get('name')!r} "
                f"!= primitive_name {self.primitive_name!r}"
            )
        if self.catalog_spec.get("namespace") != self.namespace:
            raise ValueError(
                f"catalog_spec['namespace']={self.catalog_spec.get('namespace')!r} "
                f"!= namespace {self.namespace!r}"
            )
        return self

    def render_prompt(self) -> str:
        reference = (
            self.reference_stateful_impl if self.is_stateful else self.reference_stateless_impl
        )
        oss_ref = _load_oss_reference(self.primitive_name)
        stateful_flag = "--is-stateful" if self.is_stateful else "(omit the flag for stateless)"
        stateful_extras = (
            "\n- `<Name>.tla` + `<Name>.cfg` — TLA+ spec with Init, Next, ≥2 SAFETY invariants mapped to catalog invariants. Run `tlc <Name>.tla` locally until `Model checking completed. No error has been found.`"
            "\n- `state_machine_<Name>.py` — hypothesis `RuleBasedStateMachine` exploring all reachable states."
            "\n- `concurrent_<Name>.py` — linearizability / race-detection suite."
            if self.is_stateful else ""
        )
        hypothesis_conftest = (
            """
import os
import tempfile
from hypothesis import settings
from hypothesis.database import DirectoryBasedExampleDatabase

_HYP_DIR = tempfile.mkdtemp(prefix=\"hypothesis_\")
os.environ.setdefault(\"HYPOTHESIS_STORAGE_DIRECTORY\", _HYP_DIR)
settings.register_profile(
    \"venous\",
    database=DirectoryBasedExampleDatabase(_HYP_DIR),
    deadline=None,
)
settings.load_profile(\"venous\")"""
            if self.is_stateful else ""
        )
        return f"""\
# BUILDER — ONE PRIMITIVE: {self.primitive_name}

You build exactly ONE primitive end-to-end to all 10 tier gates (exit 0 on
`check_primitive.py`). No other primitives, no shortcuts, no soft-accepts.

## Primitive facts
- Name: `{self.primitive_name}`
- Namespace: `{self.namespace}`
- Maturity: `{self.maturity.value}`
- is_stateful: **{self.is_stateful}** → T2 (TLA+)/T3 (hypothesis)/T5 (concurrency) {"REQUIRED" if self.is_stateful else "auto-SKIPPED"}
- Source catalog: `docs/research/outputs/{self.source_catalog_file}` (copy PrimitiveSpec verbatim into `{self.primitive_name}.contract.json` — drift rejection is strict)
- Target dir: `skills/SKILL-001-fastapi-production/core/venous/{self.namespace}/{self.primitive_name}/`

## Reference pilot (study this byte-for-byte for the HuGR *shell*)
`{reference}`
The Protocol shape, docstring style, invariant-ID citations, test slug
conventions, observability schema format, chaos harness, TLA+ spec structure
(if stateful) — all green on all 10 tiers. Mirror the pattern.

{oss_ref}

**CRITICAL token-efficiency directive**: do NOT re-derive well-known algorithms
from first principles. Read the OSS reference above for the algorithm, then
ADAPT to the HuGR shell (Protocol, invariants, TLA+, observability). You are
writing ~30% novel code (HuGR shell) and ~70% informed-by-reference code
(algorithm). Building CircuitBreaker from zero when `pybreaker` exists is
wasted tokens.

## Working directory
`cd /Users/gustavoschneiter/Documents/HuGR/HuGR_Arsenal`

## Deliverable artefacts (in order, to avoid mid-build halts)
1. `__init__.py` in target dir, `<namespace>/`, `core/venous/`, and `core/` (idempotent touch — empty files)
2. `{self.primitive_name}.contract.json` — verbatim copy of PrimitiveSpec from the source catalog file
3. `{self.primitive_name}.py` — Protocol + reference impl + runtime invariant checkers. mypy --strict clean, ruff (curated ALL) clean, zero bare `# type: ignore` / `# noqa` (attach rationale citing INV-ID when needed)
4. `invariant_bindings.json` — `{{"invariant_bindings": [...]}}` one entry per catalog invariant with confirms/prevents/under_failure test names sharing a slug
5. `test_{self.primitive_name}.py` — 3 tests per invariant, matching the slug in `invariant_bindings.json`
6. `behavioral_{self.primitive_name}.py` — ≥5 end-to-end scenarios that PROVE invariants at runtime
7. `metamorphic_{self.primitive_name}.py` — algebraic laws / differential parity
8. `chaos_{self.primitive_name}.py` — fault injection + game-day scripts
9. `observability_{self.primitive_name}.py` + `observability_schema.json` + `dashboard.json`
10. `{self.primitive_name}.md` — narrative spec citing invariant IDs + provenance + alternatives
11. `persona_reviews.json`, `proposed_invariants.json` — stub files; runner fills{stateful_extras}
12. `conftest.py` — pytest cache redirect (copy from pilot), {"AND hypothesis storage redirect (see below)" if self.is_stateful else "no hypothesis stanza needed"}

{"### Required conftest.py stanza for stateful primitives (prevents .hypothesis/ dotdir rejection by FileArtefact validator)" + hypothesis_conftest if self.is_stateful else ""}

## Pilot-learned landmines (all will hit T0 ruff/mypy if ignored)
- `contextmanager` return type: `Iterator[T]` from `collections.abc`, never `object`.
- `dict` MUST be parameterized: `dict[str, object]`, `dict[str, float]`. Only `isinstance(x, dict)` may be bare.
- Use `collections.abc.{{Mapping,Iterator,Sequence}}`, not `typing.{{Mapping,Iterator,Sequence}}`.
- `from __future__ import annotations` is default — don't quote annotations (`user: {self.primitive_name}`, not `user: "{self.primitive_name}"`).
- Every `# type: ignore` / `# noqa` needs a rationale after `—` or an INV-ID citation. Bare suppressions fail T0.
- Side-effect-free import — lazy-import optional SDKs inside functions.
- Protocol must match catalog byte-for-byte (names, annotations, defaults).

## Self-check (run ONCE per primitive, iterate until exit 0)
```bash
PATH=$HOME/.local/bin:$PATH \\
PYTHONPATH=skills/SKILL-001-fastapi-production \\
  skills/SKILL-001-fastapi-production/.venv/bin/python \\
  -m engine.check_primitive \\
  --primitive-dir skills/SKILL-001-fastapi-production/core/venous/{self.namespace}/{self.primitive_name} \\
  --catalog-entry docs/research/outputs/{self.source_catalog_file} \\
  --maturity {self.maturity.value} \\
  --builder-agent 99 \\
  --invariant-bindings skills/SKILL-001-fastapi-production/core/venous/{self.namespace}/{self.primitive_name}/invariant_bindings.json{" \\" if self.is_stateful else ""}{"  --is-stateful" if self.is_stateful else ""}
```

TLC 2.19 is at `~/.local/bin/tlc`. mypy 1.20, ruff 0.15, hypothesis 6.152, pytest, pytest-asyncio, pydantic, opentelemetry, structlog, httpx are in the venv.

## Return (≤ 200 words)
- CLI exit code (goal: 0)
- Tier pass/skip summary (e.g. `T0-T9 all PASS`, `T2/T3/T5 SKIPPED (stateless)`)
- Wall clock + LLM cost (T6 ≈ 65s / ≈$0.30; T9 ≈ 65s / ≈$0.35)
- If a tier failed: specific tier + first-line error + the fix you applied
- Key paths to the produced artefacts

Minimum bar: exit 0. Nothing else counts.
"""


# ---------------------------------------------------------------------------
# Builder — produce a list of briefings for every un-delivered primitive
# ---------------------------------------------------------------------------
def pending_briefings() -> list[SinglePrimitiveBriefing]:
    """Return one SinglePrimitiveBriefing for every primitive not yet accepted."""
    catalog = _load_catalog()
    accepted, _ = _delivered_primitives()
    pending: list[SinglePrimitiveBriefing] = []
    for name, spec in catalog.items():
        if name in accepted:
            continue
        pending.append(SinglePrimitiveBriefing(
            primitive_name=name,
            namespace=spec["namespace"],
            maturity=Maturity(spec["maturity"]),
            is_stateful=_is_stateful(name, spec["namespace"], spec["api_signature"]),
            source_agent_id=spec["_source_agent"],
            source_catalog_file=spec["_source_file"],
            catalog_spec={k: v for k, v in spec.items() if not k.startswith("_")},
        ))
    return pending


if __name__ == "__main__":
    briefings = pending_briefings()
    accepted, _ = _delivered_primitives()
    print(f"Accepted to date: {len(accepted)} primitives")
    print(f"Pending: {len(briefings)} primitives\n")
    by_ns: dict[str, int] = {}
    stateful = 0
    for b in briefings:
        by_ns[b.namespace] = by_ns.get(b.namespace, 0) + 1
        stateful += int(b.is_stateful)
    print("Pending by namespace:")
    for ns, n in sorted(by_ns.items()):
        print(f"  {ns:14s} {n:3d}")
    print(f"\nPending stateful: {stateful}  stateless: {len(briefings) - stateful}")
    if briefings:
        sample = briefings[0]
        p = sample.render_prompt()
        print(f"\nSample prompt ({sample.primitive_name}): {len(p)} chars (~{len(p)//4} tokens)")
