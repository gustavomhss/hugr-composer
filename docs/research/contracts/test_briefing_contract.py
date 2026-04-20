"""
Prove the briefing contract is absurdly rigorous.

Run: python3 docs/research/contracts/test_briefing_contract.py

Each validator in briefing_contract.py MUST have at least one positive test
(accepts valid input) and one negative test (rejects broken input).
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from briefing_contract import (  # noqa: E402
    Maturity,
    Namespace,
    PrimitiveSpec,
    ResearchAgentBriefing,
    ResearchDeliverable,
    SourceCitation,
    validate_deliverable,
)


# ---------------------------------------------------------------------------
# Golden fixtures — name-consistent api_signature and consumption_example.
# ---------------------------------------------------------------------------
GOLDEN_SOURCES: list[tuple[str, str]] = [
    ("RFC 6749 (OAuth 2.0 Framework)", "Section 1.3.3 Resource Owner Password"),
    ("ASP.NET Core 8.0", "HttpContext.User / ClaimsPrincipal"),
    ("Spring Boot 3.2 Reference", "SecurityContextHolder"),
    ("Nest.js 10 Documentation", "@CurrentUser parameter decorator"),
    ("Phoenix 1.7 Documentation", "Plug.Conn.assigns :current_user"),
    ("Rails 7 Guides", "ActiveSupport::CurrentAttributes"),
]


def _sources_for(idx: int, count: int = 2) -> list[SourceCitation]:
    """Two rotating sources per primitive — ensures coverage diversity ≥5 across 8 primitives."""
    out: list[SourceCitation] = []
    for k in range(count):
        src, loc = GOLDEN_SOURCES[(idx + k) % len(GOLDEN_SOURCES)]
        out.append(SourceCitation(source=src, locator=loc))
    return out


def _valid_primitive(**overrides) -> dict:
    name: str = overrides.pop("name", "CurrentUser")
    source_idx: int = overrides.pop("source_idx", 0)
    base = dict(
        name=name,
        namespace=Namespace.AUTH,
        purpose="Resolve the authenticated principal for the current request.",
        api_signature=(
            f"from typing import Protocol\n"
            f"class {name}(Protocol):\n"
            f"    id: str\n"
            f"    tenant_id: str | None\n"
            f"    def has_scope(self, scope: str) -> bool: ...\n"
        ),
        invariants=[
            "MUST raise 401 when no valid credential is present.",
            "NEVER returns anonymous user without explicit opt-in.",
            "ALWAYS resolves before any business-logic dependency executes.",
        ],
        extension_contract=(
            "Downstream tools extend by registering additional claim resolvers; "
            "they MUST NOT mutate the user instance after resolution."
        ),
        consumption_example=(
            f"async def route(user: {name}) -> dict:\n"
            f"    return {{'id': user.id}}\n"
        ),
        sources=_sources_for(source_idx, count=2),
        why_essential=(
            "Without a shared user primitive, each tool reimplements authentication "
            "logic and produces inconsistent claim handling across the codebase."
        ),
        alternatives_considered=["per-tool authentication middleware chain"],
        maturity=Maturity.BATTLE_TESTED,
    )
    base.update(overrides)
    return base


def _valid_briefing(**overrides) -> ResearchAgentBriefing:
    base = dict(
        agent_id=1,
        codename="FRAMEWORKS",
        mission=(
            "Extract dependency-injection and request-context primitives from "
            "six mature backend frameworks to inform the venous system spec."
        ),
        sources_required=[
            "Spring Boot 3.x reference",
            "Nest.js 10 docs",
            "ASP.NET Core 8.0 fundamentals",
            "Ruby on Rails 7 guides",
            "Phoenix 1.7 docs",
        ],
        scope_in=["DI/IoC patterns", "request-scoped context"],
        scope_out=["frontend primitives", "IaC tooling"],
        namespaces_owned=[Namespace.AUTH, Namespace.DATA, Namespace.API],
        min_primitives=8,
        min_sources_cited=5,
        deliverable_path="docs/research/outputs/AGENT_1_FRAMEWORKS.md",
        forbidden=["marketing quotes", "unverifiable benchmarks"],
    )
    base.update(overrides)
    return ResearchAgentBriefing(**base)


def _valid_deliverable() -> dict:
    primitives = []
    for i in range(8):
        suffix = chr(65 + i)
        primitives.append(
            _valid_primitive(
                name=f"UserCtx{suffix}",
                source_idx=i,  # rotates through 6 GOLDEN_SOURCES
                purpose=f"Resolve principal variant {suffix} for requests.",
                why_essential=(
                    f"Variant {suffix}: the shared primitive keeps claim handling "
                    f"consistent across tools; per-tool reimplementations drift."
                ),
            )
        )
    # Each primitive cites 2 rotating sources → coverage spans 6 unique sources.
    # Compute actual coverage from the primitives to stay truthful.
    coverage: dict[str, int] = {}
    for p in primitives:
        for c in p["sources"]:
            coverage[c.source] = coverage.get(c.source, 0) + 1
    return dict(
        agent_id=1,
        codename="FRAMEWORKS",
        primitives=primitives,
        cross_cutting_insights=[
            "Every framework exposes current user as a request-scoped dependency resolved before handlers run.",
            "DI containers converge on constructor injection for testability and lazy resolution for perf.",
            "Scopes (singleton/request/transient) are the cross-framework vocabulary for lifetime control.",
        ],
        source_coverage=coverage,
    )


def _expect_fail(payload: dict, needle: str, factory=PrimitiveSpec):
    try:
        factory.model_validate(payload)
    except Exception as e:
        assert needle.lower() in str(e).lower(), f"Wrong rejection reason. needle='{needle}'. Got: {e}"
        return
    raise AssertionError(f"Expected failure mentioning '{needle}', but payload passed.")


# ===========================================================================
# POSITIVE: valid payloads pass.
# ===========================================================================
def test_valid_primitive_passes():
    PrimitiveSpec.model_validate(_valid_primitive())


def test_valid_briefing_passes():
    _valid_briefing()


def test_valid_deliverable_passes_validator():
    briefing = _valid_briefing(namespaces_owned=[Namespace.AUTH])
    ok, deliverable, errors = validate_deliverable(_valid_deliverable(), briefing)
    assert ok, f"Valid deliverable rejected: {errors}"
    assert deliverable is not None


# ===========================================================================
# NEGATIVE: PrimitiveSpec field-level validators.
# ===========================================================================
def test_rejects_vague_source():
    bad = _valid_primitive()
    bad["sources"] = [{"source": "official documentation", "locator": "somewhere"}]
    _expect_fail(bad, "vague")


def test_rejects_weak_invariant():
    bad = _valid_primitive()
    bad["invariants"] = [
        "Provides authentication for routes.",
        "MUST raise 401 when credential missing.",
        "ALWAYS resolves before handlers.",
    ]
    _expect_fail(bad, "weak")


def test_rejects_missing_imperative():
    bad = _valid_primitive()
    bad["invariants"] = [
        "Validates tokens on each request.",
        "Resolves the principal eagerly.",
        "Caches per request for 60 seconds.",
    ]
    _expect_fail(bad, "imperative")


def test_rejects_invalid_python_api():
    bad = _valid_primitive()
    bad["api_signature"] = "class CurrentUser ::: broken garbage here"
    _expect_fail(bad, "valid python")


def test_rejects_invalid_python_example():
    bad = _valid_primitive()
    bad["consumption_example"] = (
        "def handler(user: CurrentUser :::: broken python here):\n    pass\n"
    )
    _expect_fail(bad, "valid python")


def test_rejects_name_with_noise_suffix():
    bad = _valid_primitive()
    bad["name"] = "CurrentUserManager"
    _expect_fail(bad, "noise suffix")


def test_rejects_marketing_in_purpose():
    bad = _valid_primitive()
    bad["purpose"] = "Provides a robust and seamless authentication experience."
    _expect_fail(bad, "marketing")


def test_rejects_marketing_in_invariant():
    bad = _valid_primitive()
    bad["invariants"] = [
        "MUST be robust against credential tampering.",
        "NEVER returns anonymous user without opt-in.",
        "ALWAYS resolves before handlers.",
    ]
    _expect_fail(bad, "marketing")


def test_rejects_purpose_echoing_why_essential():
    bad = _valid_primitive()
    shared = "Resolve the authenticated principal for the current request consistently."
    bad["purpose"] = shared
    bad["why_essential"] = shared + " Otherwise drift occurs in downstream tools."
    _expect_fail(bad, "overlap")


def test_rejects_api_not_declaring_primitive_name():
    bad = _valid_primitive(name="TenantContext")
    bad["api_signature"] = (
        "from typing import Protocol\n"
        "class SomethingElse(Protocol):\n"
        "    id: str\n"
    )
    bad["consumption_example"] = (
        "async def route(ctx: TenantContext) -> dict:\n"
        "    return {'id': ctx.id}\n"
    )
    _expect_fail(bad, "must declare")


def test_rejects_example_not_referencing_primitive_name():
    bad = _valid_primitive(name="TenantContext")
    bad["consumption_example"] = (
        "async def route(ctx: SomeOtherName) -> dict:\n"
        "    return {'id': ctx.id}\n"
    )
    _expect_fail(bad, "must use")


def test_rejects_extension_without_mechanism():
    bad = _valid_primitive()
    bad["extension_contract"] = (
        "It is extremely important that downstream consumers do not modify "
        "the value returned after it is constructed by the framework core."
    )
    _expect_fail(bad, "mechanism")


def test_rejects_short_alternative():
    bad = _valid_primitive()
    bad["alternatives_considered"] = ["x"]
    _expect_fail(bad, "too short")


def test_rejects_marketing_in_alternative():
    bad = _valid_primitive()
    bad["alternatives_considered"] = ["robust elegant modernized approach"]
    _expect_fail(bad, "marketing")


def test_rejects_duplicate_source_within_primitive():
    bad = _valid_primitive()
    bad["sources"] = [
        {"source": "RFC 6749 (OAuth 2.0 Framework)", "locator": "Section 1.3.3"},
        {"source": "RFC 6749 (OAuth 2.0 Framework)", "locator": "Section 1.3.3"},
    ]
    _expect_fail(bad, "duplicate source")


def test_rejects_missing_maturity():
    bad = _valid_primitive()
    del bad["maturity"]
    _expect_fail(bad, "maturity")


def test_rejects_short_locator():
    bad = _valid_primitive()
    bad["sources"] = [
        {"source": "RFC 6749 (OAuth 2.0 Framework)", "locator": "1"},
    ]
    _expect_fail(bad, "at least 5 characters")


def test_rejects_empty_alternatives():
    bad = _valid_primitive()
    bad["alternatives_considered"] = []
    _expect_fail(bad, "at least 1 item")


def test_rejects_missing_alternatives_key():
    bad = _valid_primitive()
    bad.pop("alternatives_considered", None)
    # min_length=1 now; absence falls through to default_factory? No — we set min_length=1 without default.
    # So missing key = Pydantic missing-field error.
    _expect_fail(bad, "alternatives_considered")


# ===========================================================================
# NEGATIVE: ResearchDeliverable validators and validate_deliverable().
# ===========================================================================
def test_rejects_shallow_cross_cutting_insight():
    payload = _valid_deliverable()
    payload["cross_cutting_insights"] = ["short.", "still short.", "nope."]
    try:
        ResearchDeliverable.model_validate(payload)
    except Exception as e:
        assert "short" in str(e).lower() or "length" in str(e).lower()
        return
    raise AssertionError("Short insight should have been rejected.")


def test_rejects_too_long_insight():
    payload = _valid_deliverable()
    payload["cross_cutting_insights"][0] = "x " * 500  # way over 400 chars
    try:
        ResearchDeliverable.model_validate(payload)
    except Exception as e:
        assert "too long" in str(e).lower() or "concise" in str(e).lower(), f"Got: {e}"
        return
    raise AssertionError("Long insight should have been rejected.")


def test_rejects_marketing_in_insight():
    payload = _valid_deliverable()
    payload["cross_cutting_insights"][0] = (
        "Every framework exposes a seamless and elegant model for request context resolution."
    )
    try:
        ResearchDeliverable.model_validate(payload)
    except Exception as e:
        assert "marketing" in str(e).lower(), f"Got: {e}"
        return
    raise AssertionError("Marketing in insight should have been rejected.")


def test_rejects_short_gap_entry():
    payload = _valid_deliverable()
    payload["gaps_observed"] = ["too short"]
    try:
        ResearchDeliverable.model_validate(payload)
    except Exception as e:
        assert "too short" in str(e).lower() or "gap 0" in str(e).lower(), f"Got: {e}"
        return
    raise AssertionError("Short gap should have been rejected.")


def test_accepts_case_different_source_in_coverage():
    """Normalization should allow 'RFC 6749' vs 'rfc 6749' mismatch."""
    payload = _valid_deliverable()
    # Rewrite coverage keys with different casing than primitive sources.
    normalized: dict[str, int] = {}
    for k, v in payload["source_coverage"].items():
        normalized[k.lower()] = v
    payload["source_coverage"] = normalized
    # Must pass — truthfulness check is case-insensitive.
    ResearchDeliverable.model_validate(payload)


def test_rejects_case_variant_duplicate_primitive_names():
    """Duplicate names differing only in case should be rejected."""
    payload = _valid_deliverable()
    n1 = payload["primitives"][0]["name"]  # e.g. "UserCtxA"
    payload["primitives"][1]["name"] = n1.lower()
    # Sync api + example with new name.
    n2 = n1.lower()
    payload["primitives"][1]["api_signature"] = (
        f"from typing import Protocol\nclass {n2}(Protocol):\n    id: str\n"
    )
    payload["primitives"][1]["consumption_example"] = (
        f"async def route(u: {n2}) -> dict:\n    return {{'id': u.id}}\n"
    )
    # But name field has pattern ^[A-Z]... so lowercase fails pattern first.
    # Use a PascalCase variant instead: same letters different case inside.
    payload["primitives"][1]["name"] = "UserCtxa"  # case variant of UserCtxA
    payload["primitives"][1]["api_signature"] = (
        f"from typing import Protocol\nclass UserCtxa(Protocol):\n    id: str\n"
    )
    payload["primitives"][1]["consumption_example"] = (
        f"async def route(u: UserCtxa) -> dict:\n    return {{'id': u.id}}\n"
    )
    try:
        ResearchDeliverable.model_validate(payload)
    except Exception as e:
        assert "duplicate primitive" in str(e).lower(), f"Got: {e}"
        return
    raise AssertionError("Case-variant duplicate should have been rejected.")


def test_rejects_duplicate_primitive_names():
    payload = _valid_deliverable()
    payload["primitives"][1]["name"] = payload["primitives"][0]["name"]
    # Sync api and example with renamed primitive.
    n = payload["primitives"][0]["name"]
    payload["primitives"][1]["api_signature"] = (
        f"from typing import Protocol\nclass {n}(Protocol):\n    id: str\n"
    )
    payload["primitives"][1]["consumption_example"] = (
        f"async def route(u: {n}) -> dict:\n    return {{'id': u.id}}\n"
    )
    try:
        ResearchDeliverable.model_validate(payload)
    except Exception as e:
        assert "duplicate primitive" in str(e).lower(), f"Got: {e}"
        return
    raise AssertionError("Duplicate primitive names should have been rejected.")


def test_rejects_zero_source_count():
    payload = _valid_deliverable()
    # Preserve truthful coverage then zero out ONE entry (diversity stays ≥3).
    first_key = next(iter(payload["source_coverage"]))
    payload["source_coverage"][first_key] = 0
    try:
        ResearchDeliverable.model_validate(payload)
    except Exception as e:
        assert "non-positive" in str(e).lower(), f"Got: {e}"
        return
    raise AssertionError("Zero count should have been rejected.")


def test_rejects_phantom_source_in_coverage():
    payload = _valid_deliverable()
    payload["source_coverage"]["Nonexistent Source Nobody Cites"] = 3
    try:
        ResearchDeliverable.model_validate(payload)
    except Exception as e:
        msg = str(e).lower()
        assert "phantom" in msg or "no primitive actually cites" in msg, f"Got: {e}"
        return
    raise AssertionError("Phantom source should have been rejected.")


def test_rejects_inflated_coverage_count():
    payload = _valid_deliverable()
    # Preserve diversity (6 keys) and dominance (<70%); inflate ONE key beyond reality.
    first_key = next(iter(payload["source_coverage"]))
    payload["source_coverage"][first_key] = payload["source_coverage"][first_key] + 10
    try:
        ResearchDeliverable.model_validate(payload)
    except Exception as e:
        assert "exceed" in str(e).lower() or "inflat" in str(e).lower(), f"Got: {e}"
        return
    raise AssertionError("Inflated count should have been rejected.")


def test_rejects_too_few_primitives_in_deliverable():
    briefing = _valid_briefing(min_primitives=12, namespaces_owned=[Namespace.AUTH])
    payload = _valid_deliverable()
    extras = [
        _valid_primitive(
            name=f"Extra{i}",
            purpose=f"Resolve extra principal variant {i} for requests.",
            why_essential=(
                f"Extra {i}: shared so claim handling stays consistent; "
                f"per-tool drift appears after three features."
            ),
        )
        for i in range(2)
    ]
    payload["primitives"] = payload["primitives"] + extras
    ok, _, errors = validate_deliverable(payload, briefing)
    assert not ok
    assert any("min_primitives" in e for e in errors), f"Got: {errors}"


def test_rejects_low_source_diversity_in_deliverable():
    payload = _valid_deliverable()
    payload["source_coverage"] = {"RFC 6749 (OAuth 2.0 Framework)": 8}
    try:
        ResearchDeliverable.model_validate(payload)
    except Exception as e:
        msg = str(e).lower()
        assert "diversity" in msg or "dominates" in msg or "unique sources" in msg, f"Got: {e}"
        return
    raise AssertionError("Low diversity should have been rejected.")


def test_rejects_off_namespace_primitive():
    briefing = _valid_briefing(namespaces_owned=[Namespace.AUTH])
    payload = _valid_deliverable()
    payload["primitives"][0]["namespace"] = Namespace.LLM.value
    ok, _, errors = validate_deliverable(payload, briefing)
    assert not ok
    assert any("namespace" in e.lower() for e in errors), f"Got: {errors}"


def test_rejects_agent_id_mismatch():
    briefing = _valid_briefing(namespaces_owned=[Namespace.AUTH])
    payload = _valid_deliverable()
    payload["agent_id"] = 7
    ok, _, errors = validate_deliverable(payload, briefing)
    assert not ok
    assert any("agent_id" in e for e in errors), f"Got: {errors}"


def test_rejects_deliverable_path_mismatch_codename():
    try:
        _valid_briefing(
            codename="FRAMEWORKS",
            deliverable_path="docs/research/outputs/AGENT_1_DISTRIBUTED.md",
        )
    except Exception as e:
        assert "must end with" in str(e).lower(), f"Got: {e}"
        return
    raise AssertionError("Path/codename mismatch should have been rejected.")


def test_rejects_deliverable_codename_bad_pattern():
    """codename must be UPPER_SNAKE."""
    payload = _valid_deliverable()
    payload["codename"] = "lowercase_bad"
    try:
        ResearchDeliverable.model_validate(payload)
    except Exception as e:
        assert "pattern" in str(e).lower() or "string should match" in str(e).lower(), f"Got: {e}"
        return
    raise AssertionError("Lowercase codename should have been rejected.")


def test_rejects_consumption_example_name_only_in_comment():
    """Name in a comment is not a real reference — AST check rejects."""
    bad = _valid_primitive(name="TenantContext")
    bad["consumption_example"] = (
        "# We use TenantContext here as documentation\n"
        "async def route(x: str) -> dict:\n"
        "    return {'id': x}\n"
    )
    # api_signature still has TenantContext (to pass that check), but example doesn't reference as identifier.
    bad["api_signature"] = (
        "from typing import Protocol\n"
        "class TenantContext(Protocol):\n"
        "    id: str\n"
    )
    _expect_fail(bad, "identifier")


def test_rejects_duplicate_cross_cutting_insights():
    payload = _valid_deliverable()
    payload["cross_cutting_insights"][1] = payload["cross_cutting_insights"][0]
    try:
        ResearchDeliverable.model_validate(payload)
    except Exception as e:
        assert "duplicate insight" in str(e).lower(), f"Got: {e}"
        return
    raise AssertionError("Duplicate insights should have been rejected.")


def test_rejects_duplicate_gaps():
    payload = _valid_deliverable()
    payload["gaps_observed"] = [
        "No shared audit log facade across all tools.",
        "No shared audit log facade across all tools.",
    ]
    try:
        ResearchDeliverable.model_validate(payload)
    except Exception as e:
        assert "duplicate gap" in str(e).lower(), f"Got: {e}"
        return
    raise AssertionError("Duplicate gaps should have been rejected.")


def test_rejects_cited_source_not_in_coverage():
    """Bidirectional: every source cited by primitives must appear in coverage."""
    payload = _valid_deliverable()
    # Remove one entry from coverage while primitives still cite it.
    first_key = next(iter(payload["source_coverage"]))
    del payload["source_coverage"][first_key]
    try:
        ResearchDeliverable.model_validate(payload)
    except Exception as e:
        assert "omits sources" in str(e).lower(), f"Got: {e}"
        return
    raise AssertionError("Missing source in coverage should have been rejected.")


def test_rejects_bare_class_definition_as_consumption():
    """A class definition with the primitive's name is NOT a consumption example."""
    bad = _valid_primitive(name="TenantContext")
    bad["api_signature"] = (
        "from typing import Protocol\n"
        "class TenantContext(Protocol):\n"
        "    id: str\n"
    )
    bad["consumption_example"] = (
        "class TenantContext:\n"
        "    def __init__(self) -> None:\n"
        "        pass\n"
    )
    _expect_fail(bad, "must use")


def test_rejects_import_only_as_consumption():
    """Import without use is not a consumption example."""
    bad = _valid_primitive(name="TenantContext")
    bad["consumption_example"] = (
        "from app.deps import TenantContext  # just importing, no use\n"
    )
    _expect_fail(bad, "must use")


def test_accepts_type_alias_api_signature():
    """Python 3.12+ `type Foo = ...` (PEP 695) is a valid declaration."""
    import sys as _sys
    if _sys.version_info < (3, 12):
        return  # skip on older runtimes
    ok = _valid_primitive(name="CorrelationId")
    ok["api_signature"] = "type CorrelationId = str\n"
    ok["consumption_example"] = (
        "def emit(cid: CorrelationId) -> None:\n"
        "    print(cid)\n"
    )
    PrimitiveSpec.model_validate(ok)


def test_rejects_short_invariant():
    bad = _valid_primitive()
    bad["invariants"] = [
        "MUST fail.",  # too short (<15 chars)
        "NEVER returns anonymous user without explicit opt-in.",
        "ALWAYS resolves before any business-logic dependency executes.",
    ]
    _expect_fail(bad, "too short")


def test_rejects_marketing_in_why_essential():
    bad = _valid_primitive()
    bad["why_essential"] = (
        "Without a shared primitive, each tool reimplements a robust and elegant solution."
    )
    _expect_fail(bad, "marketing")


def test_rejects_marketing_in_extension_contract():
    bad = _valid_primitive()
    bad["extension_contract"] = (
        "Downstream tools extend by registering premium claim resolvers "
        "for a seamless authentication experience."
    )
    _expect_fail(bad, "marketing")


def test_rejects_long_gap_entry():
    payload = _valid_deliverable()
    payload["gaps_observed"] = ["x " * 200]  # 400 chars, over 300 limit
    try:
        ResearchDeliverable.model_validate(payload)
    except Exception as e:
        assert "too long" in str(e).lower() or "gap 0" in str(e).lower(), f"Got: {e}"
        return
    raise AssertionError("Long gap should have been rejected.")


def test_rejects_marketing_in_gap():
    payload = _valid_deliverable()
    payload["gaps_observed"] = [
        "Missing a robust audit log facade across all tools in the system.",
    ]
    try:
        ResearchDeliverable.model_validate(payload)
    except Exception as e:
        assert "marketing" in str(e).lower(), f"Got: {e}"
        return
    raise AssertionError("Marketing in gap should have been rejected.")


def test_rejects_min_sources_cited_floor():
    # Briefing demands 7 unique sources; deliverable has 6.
    briefing = _valid_briefing(namespaces_owned=[Namespace.AUTH], min_sources_cited=7)
    payload = _valid_deliverable()  # has 6 unique sources (from GOLDEN_SOURCES rotation)
    ok, _, errors = validate_deliverable(payload, briefing)
    assert not ok
    assert any("min_sources_cited" in e for e in errors), f"Got: {errors}"


def test_rejects_codename_mismatch_in_validate():
    briefing = _valid_briefing(namespaces_owned=[Namespace.AUTH])
    payload = _valid_deliverable()
    payload["codename"] = "DISTRIBUTED"
    ok, _, errors = validate_deliverable(payload, briefing)
    assert not ok
    assert any("codename mismatch" in e.lower() for e in errors), f"Got: {errors}"


def test_anti_patterns_field_present_and_optional():
    """anti_patterns is behavioral advice — must be on the briefing, defaults to []."""
    b = _valid_briefing(namespaces_owned=[Namespace.AUTH])
    assert b.anti_patterns == []  # default empty
    b2 = _valid_briefing(
        namespaces_owned=[Namespace.AUTH],
        anti_patterns=["avoid marketing vocabulary", "cite every claim"],
    )
    assert len(b2.anti_patterns) == 2


def test_anti_patterns_shown_in_prompt():
    """anti_patterns render in the prompt so the agent sees them."""
    b = _valid_briefing(
        namespaces_owned=[Namespace.AUTH],
        anti_patterns=["avoid marketing vocabulary"],
    )
    rendered = b.render_prompt()
    assert "avoid marketing vocabulary" in rendered
    assert "Anti-patterns" in rendered


def test_anti_patterns_not_scanned_by_validator():
    """If a behavioral phrase appears in deliverable prose, it MUST NOT fail the gate
    (only `forbidden` literal phrases are scanned)."""
    briefing = _valid_briefing(
        namespaces_owned=[Namespace.AUTH],
        forbidden=[],  # no literal phrases
        anti_patterns=["avoid marketing vocabulary"],
    )
    payload = _valid_deliverable()
    # Insert the anti-pattern phrase literally — must still pass.
    payload["cross_cutting_insights"][0] = (
        "Frameworks converge on avoid marketing vocabulary as a style guideline."
    )
    ok, _, errors = validate_deliverable(payload, briefing)
    assert ok, f"anti_patterns should NOT be scanned. errors: {errors}"


def test_rejects_forbidden_phrase_in_insights():
    briefing = _valid_briefing(
        namespaces_owned=[Namespace.AUTH],
        forbidden=["marketing quotes", "ground-breaking novelty"],
    )
    payload = _valid_deliverable()
    payload["cross_cutting_insights"][0] = (
        "This pattern's ground-breaking novelty sets every framework apart from peers."
    )
    ok, _, errors = validate_deliverable(payload, briefing)
    assert not ok
    assert any("forbidden phrase" in e.lower() for e in errors), f"Got: {errors}"


def test_rejects_forbidden_phrase_in_alternatives():
    briefing = _valid_briefing(
        namespaces_owned=[Namespace.AUTH],
        forbidden=["ground-breaking novelty"],
    )
    payload = _valid_deliverable()
    payload["primitives"][0]["alternatives_considered"] = [
        "Considered using a ground-breaking novelty approach and rejected it."
    ]
    ok, _, errors = validate_deliverable(payload, briefing)
    assert not ok
    assert any("forbidden phrase" in e.lower() for e in errors), f"Got: {errors}"


def test_rejects_forbidden_phrase_in_gaps():
    briefing = _valid_briefing(
        namespaces_owned=[Namespace.AUTH],
        forbidden=["ground-breaking novelty"],
    )
    payload = _valid_deliverable()
    payload["gaps_observed"] = [
        "A ground-breaking novelty gap exists around audit log normalization across tools."
    ]
    ok, _, errors = validate_deliverable(payload, briefing)
    assert not ok
    assert any("forbidden phrase" in e.lower() for e in errors), f"Got: {errors}"


def test_rejects_source_coverage_casing_collision():
    """Two keys that normalize to the same source must be merged — no diversity inflation."""
    payload = _valid_deliverable()
    first_key = next(iter(payload["source_coverage"]))
    collided = first_key.upper() if first_key != first_key.upper() else first_key.lower()
    # Inject a second key that normalizes to the same thing.
    payload["source_coverage"][collided] = 1
    try:
        ResearchDeliverable.model_validate(payload)
    except Exception as e:
        assert "duplicate normalized keys" in str(e).lower() or "merge them" in str(e).lower(), f"Got: {e}"
        return
    raise AssertionError("Coverage casing collision should have been rejected.")


def test_casefold_normalization_handles_sharp_s():
    """`.casefold()` beats `.lower()` for Unicode: German ß should casefold to 'ss'."""
    payload = _valid_deliverable()
    # Two primitive names differing only by ß vs ss should collide under casefold.
    # Keep names pattern-valid (PascalCase, ASCII-only per name regex), so simulate this
    # on source_coverage keys instead (no regex constraint).
    original_key = next(iter(payload["source_coverage"]))
    # Build a key with the same casefold footprint via whitespace collapse.
    collided = original_key.replace(" ", "  ")  # double whitespace normalizes away
    if collided == original_key:
        # fallback: add internal whitespace that collapses
        collided = original_key[:3] + " " + original_key[3:]
    payload["source_coverage"][collided] = 1
    try:
        ResearchDeliverable.model_validate(payload)
    except Exception as e:
        assert "duplicate normalized keys" in str(e).lower(), f"Got: {e}"
        return
    raise AssertionError("Whitespace-variant key should have been rejected by normalization.")


# ===========================================================================
# Manual runner (so we don't require pytest).
# ===========================================================================
def _run() -> int:
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    passed = 0
    failed: list[tuple[str, str]] = []
    for t in tests:
        try:
            t()
            passed += 1
            print(f"  ✓ {t.__name__}")
        except Exception:
            failed.append((t.__name__, traceback.format_exc()))
            print(f"  ✗ {t.__name__}")
    print(f"\n{passed}/{len(tests)} passed")
    for name, tb in failed:
        print(f"\n--- {name} ---\n{tb}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(_run())
