"""
Research Agent Briefing & Deliverable Contracts — ABSURDLY RIGOROUS.

Every research agent receives a `ResearchAgentBriefing` instance as its mission.
Every agent returns a `ResearchDeliverable` that this module validates.

Rigor enforced at schema level:
- No vague sources (must name concrete book/RFC/framework/URL).
- No weak invariants (MUST/NEVER/ALWAYS/CANNOT required).
- api_signature must be syntactically valid Python (ast.parse).
- Source diversity floor (≥3 unique; no single source >70% of primitives).
- Prose length caps (prevents filler + keeps tokens tight).
- Namespace coherence (primitives live where the briefing scoped them).

Failure = reject the deliverable and return diff to the agent.
"""

from __future__ import annotations

import ast
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator


def _norm(s: str) -> str:
    """Unicode-safe identity normalization for dedup & cross-check.

    `.casefold()` beats `.lower()` for locale-insensitive comparison (handles
    German ß → ss, Greek final sigma, etc.). Whitespace is collapsed so
    'Current User' == 'CurrentUser'.
    """
    return "".join(s.casefold().split())


# ---------------------------------------------------------------------------
# Namespace taxonomy — the venous system's top-level organs.
# Extend sparingly. Adding a namespace is a design decision, not a shortcut.
# ---------------------------------------------------------------------------
class Maturity(str, Enum):
    """How battle-tested is this primitive in production?"""

    BATTLE_TESTED = "battle_tested"  # ≥5 years in production at scale; canonical.
    EMERGING = "emerging"            # 1-5 years, multiple implementations, converging.
    EXPERIMENTAL = "experimental"    # <1 year, one or two impls, still learning.


# Mechanism vocabulary — extension_contract must name at least one.
EXTENSION_MECHANISMS = (
    "subclass", "register", "implement", "extend", "decorator",
    "hook", "provider", "adapter", "bind", "compose",
    "plugin", "middleware", "interceptor", "filter",
)


class Namespace(str, Enum):
    AUTH = "auth"                # identity, session, impersonation
    DATA = "data"                # db, UoW, repo, txn, tenant scope
    EVENTS = "events"            # bus, outbox, saga, webhook dispatch
    OBS = "obs"                  # logger, tracer, metrics, audit
    POLICY = "policy"            # RBAC, ABAC, Cedar/OPA facade
    FLAGS = "flags"              # feature flags, toggles, experiments
    COST = "cost"                # cost tracker, quota, budget
    JOBS = "jobs"                # enqueuer (arq/celery/temporal), scheduler
    CACHE = "cache"              # L1/L2 cache, distributed lock, idempotency
    API = "api"                  # response/error, paginator, filter, sort
    FILES = "files"              # storage facade, signed URLs, image pipeline
    SECURITY = "security"        # crypto, secrets, CSRF, input/output hygiene
    RESILIENCY = "resiliency"    # circuit breaker, bulkhead, retry, timeout
    COMPLIANCE = "compliance"    # audit tamper-evident, retention, consent, DSAR
    LLM = "llm"                  # prompt mgmt, model registry, vector, guardrails
    EXTRAS = "extras"            # provenance, intent logger, request shape


# ---------------------------------------------------------------------------
# Source citations — no vibes, no "official docs", no "common knowledge".
# ---------------------------------------------------------------------------
VAGUE_SOURCE_FRAGMENTS = (
    "official documentation", "official docs", "the documentation",
    "the framework", "common knowledge", "industry standard",
    "best practice", "widely known", "the community", "the docs",
    "various sources", "online resources",
)

# Marketing vocabulary — banned in prose fields. Primitives are described by
# what they DO and what RULES they enforce, not by adjectives.
MARKETING_WORDS = (
    "robust", "powerful", "seamless", "effortless", "elegant",
    "cutting-edge", "state-of-the-art", "next-generation", "enterprise-grade",
    "world-class", "best-in-class", "lightning-fast", "blazing", "intuitive",
    "innovative", "premium", "superior", "revolutionary",
    "game-changing", "paradigm-shift", "next-level", "unparalleled",
    "industry-leading", "future-proof", "battle-hardened",
    # note: 'leading' removed (false positive on 'leading zero' / 'leading digit')
    # note: 'modern' removed (valid in 'modern Python 3.12+ syntax' and similar)
)


def _reject_marketing(field_name: str, value: str) -> str:
    low = value.lower()
    hits = [w for w in MARKETING_WORDS if w in low]
    if hits:
        raise ValueError(
            f"{field_name} contains marketing vocabulary: {hits}. "
            f"Describe what it DOES and what RULES it enforces, not adjectives."
        )
    return value


class SourceCitation(BaseModel):
    """Traceable provenance. Every primitive must cite ≥1.

    Standards: see `docs/research/CONTRACT_STANDARDS.md` §1.
    - Completeness: SRC-CC-01, SRC-CC-02
    - Invariants:   SRC-INV-01, SRC-INV-02, SRC-INV-03
    - Quality:      SRC-QS-01, SRC-QS-02
    """

    source: str = Field(
        min_length=5,
        max_length=200,
        description="Concrete: book title, RFC number, framework name + version, URL, class name.",
    )
    locator: str = Field(
        min_length=5,
        max_length=200,
        description="Page, chapter, section, URL fragment, class path. Must let a human verify.",
    )

    @field_validator("source")
    @classmethod
    def reject_vague(cls, v: str) -> str:
        low = v.lower()
        for frag in VAGUE_SOURCE_FRAGMENTS:
            if frag in low:
                raise ValueError(
                    f"Source too vague: '{v}'. "
                    f"Name a specific book/RFC/framework/class/URL (banned: '{frag}')."
                )
        return v


# ---------------------------------------------------------------------------
# PrimitiveSpec — the atomic unit of the venous system.
# ---------------------------------------------------------------------------
IMPERATIVE_KEYWORDS = ("MUST", "NEVER", "ALWAYS", "CANNOT", "SHALL", "FORBIDDEN")
WEAK_PREFIXES = ("provides", "allows", "enables", "offers", "gives", "supports", "helps")


class PrimitiveSpec(BaseModel):
    """Atomic unit of the venous system. Every field earns its place.

    Standards: see `docs/research/CONTRACT_STANDARDS.md` §2.
    - Completeness: PRIM-CC-01 .. PRIM-CC-11 (11 required fields + shape)
    - Invariants:   PRIM-INV-01 .. PRIM-INV-09 (name hygiene, imperatives,
                    AST declarations, AST usage, mechanism words, no echoing,
                    universal marketing scan)
    - Quality:      PRIM-QS-01 .. PRIM-QS-06 (readability, testability, substance)
    - DoD:          every CC + INV green; sampled QS confirmed on review.
    """

    name: str = Field(
        min_length=3,
        max_length=40,
        pattern=r"^[A-Z][a-zA-Z0-9]*$",
        description="PascalCase identifier, no suffix noise (no 'Manager', 'Helper', 'Util').",
    )
    namespace: Namespace
    purpose: str = Field(
        min_length=20,
        max_length=200,
        description="ONE sentence: what this primitive exists to do. No marketing verbs.",
    )
    api_signature: str = Field(
        min_length=20,
        max_length=2000,
        description="Python type stub, multi-line OK. MUST be ast.parse-valid.",
    )
    invariants: list[str] = Field(
        min_length=3,
        max_length=10,
        description="Rules that ALWAYS hold. Each MUST use an imperative keyword.",
    )
    extension_contract: str = Field(
        min_length=40,
        max_length=600,
        description="How a downstream tool EXTENDS this primitive without breaking invariants.",
    )
    consumption_example: str = Field(
        min_length=40,
        max_length=800,
        description="Canonical Python snippet showing USE. Must be ast.parse-valid. ≥40 chars: trivial one-liners are not consumption.",
    )
    sources: list[SourceCitation] = Field(min_length=1, max_length=5)
    why_essential: str = Field(
        min_length=30,
        max_length=400,
        description="Why a primitive vs. left per-tool? What breaks if it is not shared?",
    )
    alternatives_considered: list[str] = Field(
        min_length=1,
        max_length=5,
        description="Other approaches considered (e.g., 'middleware vs dependency'). ≥1 required — SOTA thinks about alternatives. Items ≥15 chars.",
    )
    maturity: Maturity = Field(
        description=(
            "How production-proven is this primitive? "
            "battle_tested = ≥5y at scale; emerging = 1-5y converging; experimental = <1y."
        ),
    )

    @field_validator("invariants", mode="after")
    @classmethod
    def invariants_must_be_imperative(cls, v: list[str]) -> list[str]:
        for inv in v:
            head = inv.strip().split(maxsplit=1)[0].lower() if inv.strip() else ""
            if head in WEAK_PREFIXES:
                raise ValueError(
                    f"Invariant opens with weak verb ('{head}'): '{inv}'. "
                    f"Use MUST/NEVER/ALWAYS/CANNOT/SHALL."
                )
            upper = inv.upper()
            if not any(kw in upper for kw in IMPERATIVE_KEYWORDS):
                raise ValueError(
                    f"Invariant lacks imperative keyword: '{inv}'. "
                    f"Required one of: {IMPERATIVE_KEYWORDS}."
                )
            if len(inv) < 15:
                raise ValueError(f"Invariant too short to be meaningful: '{inv}'.")
            # Marketing sneaks in through "MUST be robust" — catch it.
            low = inv.lower()
            hits = [w for w in MARKETING_WORDS if w in low]
            if hits:
                raise ValueError(
                    f"Invariant contains marketing vocabulary {hits}: '{inv}'. "
                    f"Describe verifiable behavior, not adjectives."
                )
        return v

    @field_validator("alternatives_considered")
    @classmethod
    def alternatives_substantive(cls, v: list[str]) -> list[str]:
        for item in v:
            if len(item.strip()) < 15:
                raise ValueError(
                    f"alternatives_considered item too short ({len(item)} chars): '{item}'. "
                    f"Explain the alternative briefly."
                )
            _reject_marketing("alternatives_considered", item)
        return v

    @field_validator("sources")
    @classmethod
    def sources_unique(cls, v: list[SourceCitation]) -> list[SourceCitation]:
        seen: set[tuple[str, str]] = set()
        for c in v:
            key = (_norm(c.source), _norm(c.locator))
            if key in seen:
                raise ValueError(
                    f"Duplicate source citation: ({c.source} | {c.locator}). "
                    f"Each (source, locator) pair must be unique."
                )
            seen.add(key)
        return v

    @model_validator(mode="after")
    def api_signature_declares_name(self) -> "PrimitiveSpec":
        """The api_signature MUST declare a class/protocol/function/type named after the primitive."""
        try:
            tree = ast.parse(self.api_signature)
        except SyntaxError:
            return self  # defensive; already caught by field_validator
        declared: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                declared.add(node.name)
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        declared.add(t.id)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                declared.add(node.target.id)
            # Python 3.12+ `type Foo = ...` (PEP 695)
            elif hasattr(ast, "TypeAlias") and isinstance(node, ast.TypeAlias):
                if isinstance(node.name, ast.Name):
                    declared.add(node.name.id)
        if self.name not in declared:
            raise ValueError(
                f"api_signature must declare '{self.name}' (class / function / assignment / type alias). "
                f"Declared: {sorted(declared)}"
            )
        return self

    @model_validator(mode="after")
    def consumption_example_references_name(self) -> "PrimitiveSpec":
        """Name MUST appear as a Name node (actual USE), not only as a ClassDef/FunctionDef
        declaration or an unused import. A redefinition is not consumption."""
        try:
            tree = ast.parse(self.consumption_example)
        except SyntaxError:
            return self  # already caught earlier
        used: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                used.add(node.id)
        if self.name not in used:
            raise ValueError(
                f"consumption_example must USE '{self.name}' as an identifier "
                f"(annotation, call, assignment, or expression) — a bare class/function "
                f"definition with that name is NOT usage, and a string/comment is NOT usage. "
                f"Name uses seen: {sorted(used)[:15]}"
            )
        return self

    @model_validator(mode="after")
    def extension_contract_names_mechanism(self) -> "PrimitiveSpec":
        low = self.extension_contract.lower()
        hits = [m for m in EXTENSION_MECHANISMS if m in low]
        if not hits:
            raise ValueError(
                f"extension_contract for '{self.name}' must name a concrete mechanism "
                f"(one of {list(EXTENSION_MECHANISMS)}). Got: {self.extension_contract[:120]}..."
            )
        return self

    @field_validator("api_signature", "consumption_example")
    @classmethod
    def must_be_valid_python(cls, v: str) -> str:
        try:
            ast.parse(v)
        except SyntaxError as e:
            raise ValueError(f"Not valid Python: {e}. Content:\n{v[:200]}...")
        return v

    @field_validator("name")
    @classmethod
    def no_suffix_noise(cls, v: str) -> str:
        noise = ("Manager", "Helper", "Util", "Utils", "Service", "Handler")
        for n in noise:
            if v.endswith(n) and v != n:
                raise ValueError(
                    f"Name '{v}' ends with noise suffix '{n}'. "
                    f"Primitives are named by what they ARE, not by their role."
                )
        return v

    @field_validator("purpose", "why_essential", "extension_contract")
    @classmethod
    def no_marketing_prose(cls, v: str, info) -> str:
        return _reject_marketing(info.field_name, v)

    @model_validator(mode="after")
    def purpose_and_why_distinct(self) -> "PrimitiveSpec":
        # why_essential should explain WHY as primitive; purpose explains WHAT.
        # If they overlap heavily, one of them is filler.
        p_norm = "".join(c.lower() for c in self.purpose if c.isalnum())
        w_norm = "".join(c.lower() for c in self.why_essential if c.isalnum())
        if p_norm and w_norm:
            shorter, longer = sorted([p_norm, w_norm], key=len)
            if shorter in longer or longer.startswith(shorter[:30]):
                raise ValueError(
                    f"purpose and why_essential overlap heavily for '{self.name}'. "
                    f"purpose = WHAT it does. why_essential = WHY a shared primitive vs per-tool."
                )
        return self


# ---------------------------------------------------------------------------
# ResearchAgentBriefing — the mission handed to a Sonnet agent.
# Token-efficient: no context dumps, only the contract + pointers.
# ---------------------------------------------------------------------------
class ResearchAgentBriefing(BaseModel):
    """The agent's mission. Sealed contract. Self-contained.

    Standards: see `docs/research/CONTRACT_STANDARDS.md` §3.
    - Completeness: BRIEF-CC-01 .. BRIEF-CC-09
    - Invariants:   BRIEF-INV-01 .. BRIEF-INV-05 (path-codename bind,
                    cohort uniqueness, forbidden-phrase teeth)
    - Quality:      BRIEF-QS-01 .. BRIEF-QS-04 (token discipline, version pinning)
    - DoD:          all 8 briefings pass `_sanity_check` at import; prompts fit budget.
    """

    agent_id: int = Field(ge=1, le=8)
    codename: str = Field(
        min_length=3,
        max_length=40,
        pattern=r"^[A-Z][A-Z0-9_]*$",
        description="UPPER_SNAKE codename, e.g. FRAMEWORKS, DISTRIBUTED.",
    )
    mission: str = Field(
        min_length=40,
        max_length=300,
        description="One paragraph. Precise. What this agent is researching and why.",
    )
    sources_required: list[str] = Field(
        min_length=3,
        max_length=15,
        description="MUST research each. Name specific books/frameworks/RFCs/URLs.",
    )
    scope_in: list[str] = Field(
        min_length=2,
        max_length=15,
        description="What the agent MUST cover. Bullet points, terse.",
    )
    scope_out: list[str] = Field(
        min_length=2,
        max_length=15,
        description="What the agent MUST NOT cover. Prevents drift.",
    )
    namespaces_owned: list[Namespace] = Field(
        min_length=1,
        max_length=6,
        description="Namespaces this agent is authoritative over.",
    )
    min_primitives: int = Field(ge=8, le=40, description="Floor. Fewer = auto-reject.")
    min_sources_cited: int = Field(ge=5, description="Total unique sources in deliverable.")
    deliverable_path: str = Field(
        pattern=r"^docs/research/outputs/AGENT_\d_[A-Z_]+\.md$",
        description="Exact path. Agent writes ONLY here.",
    )
    forbidden: list[str] = Field(
        default_factory=list,
        max_length=20,
        description=(
            "LITERAL phrases the validator scans for across every prose field. "
            "Each item must be the exact text that would flag a deliverable. "
            "Semantic / behavioral advice belongs in `anti_patterns`, NOT here."
        ),
    )
    anti_patterns: list[str] = Field(
        default_factory=list,
        max_length=20,
        description=(
            "Behavioral / semantic anti-patterns shown to the agent in the prompt "
            "but NOT scanned by the validator (e.g. 'do not use framework-specific "
            "names'). Keep `forbidden` for literal strings, this for judgment calls."
        ),
    )

    @model_validator(mode="after")
    def deliverable_path_matches_codename(self) -> "ResearchAgentBriefing":
        expected_suffix = f"AGENT_{self.agent_id}_{self.codename}.md"
        if not self.deliverable_path.endswith(expected_suffix):
            raise ValueError(
                f"deliverable_path must end with '{expected_suffix}'. "
                f"Got: '{self.deliverable_path}'."
            )
        return self

    def render_prompt(self) -> str:
        """Render this briefing as a token-tight prompt for a Sonnet agent."""
        def bullets(items: list[str]) -> str:
            return "\n".join(f"  - {it}" for it in items) if items else "  - (none)"

        json_path = self.deliverable_path.replace(".md", ".json")
        owned = ", ".join(n.value for n in self.namespaces_owned)

        return f"""\
# RESEARCH AGENT {self.agent_id} — {self.codename}

## Mission
{self.mission}

## Scope — IN (cover)
{bullets(self.scope_in)}

## Scope — OUT (do NOT cover)
{bullets(self.scope_out)}

## Sources you MUST research (concrete, non-vague)
{bullets(self.sources_required)}

## Namespaces you own (all primitives must be in these)
{owned}

## Quality floors
- Minimum primitives: {self.min_primitives}
- Minimum unique sources cited: {self.min_sources_cited}

## Forbidden LITERAL phrases (validator scans prose for these, rejects on hit)
{bullets(self.forbidden)}

## Anti-patterns (judgment calls — you MUST avoid, not auto-scanned)
{bullets(self.anti_patterns)}

## Contract
The deliverable contract lives at `docs/research/contracts/briefing_contract.py`.
Every field is schema-validated. Key rules:
- Every primitive has PascalCase name, namespace, purpose (≤200 ch, no marketing),
  api_signature (valid Python, declares the primitive name),
  3-10 invariants (each with MUST/NEVER/ALWAYS/CANNOT/SHALL, no marketing),
  extension_contract naming a concrete mechanism (subclass / register / decorator / adapter / hook / ...),
  consumption_example (valid Python, uses the primitive name as an IDENTIFIER),
  1-5 unique SourceCitation entries (source + locator, both non-vague),
  why_essential (distinct from purpose),
  ≥1 alternatives_considered, maturity enum.
- Deliverable: ≥{self.min_primitives} primitives, ≥{self.min_sources_cited} unique sources (no one >70%),
  3-10 cross_cutting_insights (30-400 ch each, unique, no marketing), truthful source_coverage,
  optional gaps_observed (15-300 ch each, unique).

## Deliverables
Write BOTH:
1. `{self.deliverable_path}` — human-readable markdown narrative.
2. `{json_path}` — structured JSON matching `ResearchDeliverable` shape.

## Self-check BEFORE submitting
```
python3 docs/research/contracts/check_deliverable.py \\
    --agent {self.agent_id} --deliverable {json_path}
```
Fix every error until the CLI exits 0. No soft-accepts.

## Full process spec
`docs/research/RESEARCH_PHASE_SPEC.md`

## Contract standards (CCs / INVs / QSs / DoD with rationale)
`docs/research/CONTRACT_STANDARDS.md` — every rejection cites by ID.
"""


# ---------------------------------------------------------------------------
# ResearchDeliverable — what the agent returns. Validator runs after write.
# ---------------------------------------------------------------------------
class ResearchDeliverable(BaseModel):
    """Agent's output. Validated against briefing.

    Standards: see `docs/research/CONTRACT_STANDARDS.md` §4.
    - Completeness: DEL-CC-01 .. DEL-CC-06
    - Invariants:   DEL-INV-01 .. DEL-INV-10 (unique primitive names via `_norm`;
                    coverage bidirectional, non-zero, non-inflated, unique keys
                    under normalization, diversity counted on normalized keys;
                    dominance ≤70%; dedup insights/gaps via `_norm`;
                    universal marketing scan)
    - Quality:      DEL-QS-01 .. DEL-QS-06 (insight span, gap actionability,
                    namespace distribution, roundtrip, maturity traceability)
    - DoD:          `validate_deliverable()` returns (True, <obj>, []).
    """

    agent_id: int = Field(ge=1, le=8)
    codename: str = Field(
        min_length=3,
        max_length=40,
        pattern=r"^[A-Z][A-Z0-9_]*$",
        description="UPPER_SNAKE, must match briefing codename.",
    )
    primitives: list[PrimitiveSpec] = Field(min_length=8)
    cross_cutting_insights: list[str] = Field(
        min_length=3,
        max_length=10,
        description="Patterns spanning multiple primitives or sources. Each 30-400 chars.",
    )
    source_coverage: dict[str, int] = Field(
        description="Source name → primitive count citing it. Proves breadth.",
    )
    gaps_observed: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="Primitives that should exist in SKILL-001 but likely don't. Each 15-300 chars.",
    )

    @field_validator("cross_cutting_insights")
    @classmethod
    def insights_substantive(cls, v: list[str]) -> list[str]:
        seen: set[str] = set()
        for i, ins in enumerate(v):
            if len(ins) < 30:
                raise ValueError(f"Insight {i} too short ({len(ins)} chars): '{ins}'")
            if len(ins) > 400:
                raise ValueError(
                    f"Insight {i} too long ({len(ins)} chars, max 400): '{ins[:60]}...'. "
                    f"Be concise — filler is rejected."
                )
            _reject_marketing(f"cross_cutting_insights[{i}]", ins)
            key = _norm(ins)
            if key in seen:
                raise ValueError(f"Duplicate insight {i}: '{ins[:60]}...'")
            seen.add(key)
        return v

    @field_validator("gaps_observed")
    @classmethod
    def gaps_substantive(cls, v: list[str]) -> list[str]:
        seen: set[str] = set()
        for i, g in enumerate(v):
            if len(g) < 15:
                raise ValueError(f"Gap {i} too short ({len(g)} chars): '{g}'")
            if len(g) > 300:
                raise ValueError(
                    f"Gap {i} too long ({len(g)} chars, max 300): '{g[:60]}...'."
                )
            _reject_marketing(f"gaps_observed[{i}]", g)
            key = _norm(g)
            if key in seen:
                raise ValueError(f"Duplicate gap {i}: '{g[:60]}...'")
            seen.add(key)
        return v

    @model_validator(mode="after")
    def enforce_source_coverage_keys_unique(self) -> "ResearchDeliverable":
        """Keys must be unique under normalization — 'RFC 6749' and 'rfc 6749' are ONE source."""
        seen: dict[str, str] = {}
        for k in self.source_coverage:
            n = _norm(k)
            if n in seen and seen[n] != k:
                raise ValueError(
                    f"source_coverage has duplicate normalized keys: "
                    f"'{seen[n]}' and '{k}' collapse to '{n}'. Merge them."
                )
            seen[n] = k
        return self

    @model_validator(mode="after")
    def enforce_source_diversity(self) -> "ResearchDeliverable":
        # Count unique NORMALIZED keys — prevents casing-collision gaming.
        unique_norm = {_norm(k) for k in self.source_coverage}
        if len(unique_norm) < 3:
            raise ValueError(
                f"Source diversity floor violated: {len(unique_norm)} unique sources "
                f"(after normalization). Need ≥3."
            )
        total = sum(self.source_coverage.values())
        if total == 0:
            raise ValueError("source_coverage sums to 0. No citations?")
        dominant = max(self.source_coverage.values())
        if dominant / total > 0.7:
            top = max(self.source_coverage, key=self.source_coverage.get)
            raise ValueError(
                f"Single source dominates: '{top}' = {dominant}/{total} "
                f"({dominant/total:.0%}). Max allowed: 70%."
            )
        return self

    @model_validator(mode="after")
    def enforce_primitive_count_vs_sources(self) -> "ResearchDeliverable":
        # DEFENSIVE DEAD CODE: `PrimitiveSpec.sources` has `min_length=1`, so this
        # inequality cannot fire for a successfully-parsed deliverable. Kept as a
        # belt-and-braces check in case the field constraint is ever relaxed.
        cited_in_primitives = sum(len(p.sources) for p in self.primitives)
        if cited_in_primitives < len(self.primitives):
            raise ValueError(
                f"Each primitive must cite ≥1 source. "
                f"Got {cited_in_primitives} citations for {len(self.primitives)} primitives."
            )
        return self

    @model_validator(mode="after")
    def enforce_unique_primitive_names(self) -> "ResearchDeliverable":
        # Unicode-safe: 'CurrentUser' == 'currentuser' == 'current user' (casefold + ws collapse).
        seen: dict[str, str] = {}
        dupes: list[tuple[str, str]] = []
        for p in self.primitives:
            key = _norm(p.name)
            if key in seen and seen[key] != p.name:
                dupes.append((seen[key], p.name))
            elif key in seen:
                dupes.append((p.name, p.name))
            seen[key] = p.name
        if dupes:
            raise ValueError(
                f"Duplicate primitive names (case/whitespace-normalized): {dupes}. "
                f"Each primitive must have a distinct identity."
            )
        return self

    @model_validator(mode="after")
    def enforce_source_coverage_truthfulness(self) -> "ResearchDeliverable":
        # Every count must be >0.
        zero_or_negative = {k: v for k, v in self.source_coverage.items() if v <= 0}
        if zero_or_negative:
            raise ValueError(f"source_coverage has non-positive counts: {zero_or_negative}")

        # Unicode-safe normalization (casefold + whitespace collapse) — see `_norm`.
        actually_cited_norm: dict[str, str] = {}  # norm → first original (as seen in primitives)
        for p in self.primitives:
            for c in p.sources:
                actually_cited_norm.setdefault(_norm(c.source), c.source)

        claimed_norm = {_norm(k): k for k in self.source_coverage}

        # Phantom: coverage lists source no primitive cites.
        phantom = [claimed_norm[n] for n in claimed_norm if n not in actually_cited_norm]
        if phantom:
            raise ValueError(
                f"source_coverage claims sources no primitive actually cites: {sorted(phantom)}. "
                f"Coverage must mirror reality."
            )

        # Bidirectional: every source cited by any primitive MUST appear in coverage.
        omitted = [
            actually_cited_norm[n] for n in actually_cited_norm if n not in claimed_norm
        ]
        if omitted:
            raise ValueError(
                f"source_coverage omits sources cited by primitives: {sorted(omitted)}. "
                f"Coverage must include EVERY source actually referenced."
            )

        # Counts in coverage must not exceed actual citation count for that source.
        actual_counts: dict[str, int] = {}
        for p in self.primitives:
            for c in p.sources:
                actual_counts[_norm(c.source)] = actual_counts.get(_norm(c.source), 0) + 1

        inflated = {
            original: (self.source_coverage[original], actual_counts.get(_norm(original), 0))
            for original in self.source_coverage
            if self.source_coverage[original] > actual_counts.get(_norm(original), 0)
        }
        if inflated:
            raise ValueError(
                f"source_coverage counts exceed actual citations: {inflated}. "
                f"Format: {{source: (claimed, actual)}}."
            )
        return self


# ---------------------------------------------------------------------------
# Validator entrypoint — run this against every delivered JSON before accepting.
# ---------------------------------------------------------------------------
def validate_deliverable(
    raw: dict,
    briefing: ResearchAgentBriefing,
) -> tuple[bool, ResearchDeliverable | None, list[str]]:
    """Acceptance gate.

    Returns (ok, parsed_deliverable, errors).
    If ok=False, errors contains specific rejection reasons.

    Standards: see `docs/research/CONTRACT_STANDARDS.md` §5.
    - Completeness: GATE-CC-01 .. GATE-CC-07 (schema, agent_id, codename,
                    min_primitives floor, min_sources_cited floor, namespace
                    scope, forbidden-phrase scan)
    - Invariants:   GATE-INV-01 .. GATE-INV-04 (typed return, no silent pass,
                    actionable errors, schema short-circuits)
    - Quality:      GATE-QS-01 .. GATE-QS-03 (idempotent, pinpoint errors, fast)
    - DoD:          every self-test in `test_briefing_contract.py` green; CLI wrapper
                    exits 0 (accepted) / 1 (rejected) / 2 (I/O) with structured stderr.
    """
    errors: list[str] = []

    try:
        deliverable = ResearchDeliverable.model_validate(raw)
    except Exception as e:
        return False, None, [f"Schema validation failed: {e}"]

    if deliverable.agent_id != briefing.agent_id:
        errors.append(f"agent_id mismatch: briefing={briefing.agent_id}, delivery={deliverable.agent_id}")

    if deliverable.codename != briefing.codename:
        errors.append(f"codename mismatch: briefing={briefing.codename}, delivery={deliverable.codename}")

    if len(deliverable.primitives) < briefing.min_primitives:
        errors.append(
            f"min_primitives violated: got {len(deliverable.primitives)}, "
            f"required ≥{briefing.min_primitives}"
        )

    if len(deliverable.source_coverage) < briefing.min_sources_cited:
        errors.append(
            f"min_sources_cited violated: got {len(deliverable.source_coverage)}, "
            f"required ≥{briefing.min_sources_cited}"
        )

    owned = set(briefing.namespaces_owned)
    off_namespace = [
        p.name for p in deliverable.primitives if p.namespace not in owned
    ]
    if off_namespace:
        errors.append(
            f"Primitives outside owned namespaces: {off_namespace}. "
            f"Owned: {[n.value for n in owned]}"
        )

    # Forbidden-phrase scan across ALL prose fields. Briefing.forbidden is enforced, not decorative.
    prose_blocks: list[tuple[str, str]] = []
    for p in deliverable.primitives:
        prose_blocks.extend([
            (f"primitive[{p.name}].purpose", p.purpose),
            (f"primitive[{p.name}].extension_contract", p.extension_contract),
            (f"primitive[{p.name}].why_essential", p.why_essential),
        ])
        for idx, inv in enumerate(p.invariants):
            prose_blocks.append((f"primitive[{p.name}].invariants[{idx}]", inv))
        for idx, alt in enumerate(p.alternatives_considered):
            prose_blocks.append((f"primitive[{p.name}].alternatives_considered[{idx}]", alt))
    for idx, ins in enumerate(deliverable.cross_cutting_insights):
        prose_blocks.append((f"cross_cutting_insights[{idx}]", ins))
    for idx, g in enumerate(deliverable.gaps_observed):
        prose_blocks.append((f"gaps_observed[{idx}]", g))

    for phrase in briefing.forbidden:
        needle = phrase.strip().lower()
        if len(needle) < 4:
            continue  # skip trivially-short terms that would false-match
        for location, text in prose_blocks:
            if needle in text.lower():
                errors.append(
                    f"Forbidden phrase '{phrase}' appears in {location}. "
                    f"Briefing.forbidden is enforced, not decorative."
                )

    return (len(errors) == 0), deliverable, errors
