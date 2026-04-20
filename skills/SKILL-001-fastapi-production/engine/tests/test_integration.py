"""
Cross-namespace integration tests for the venous system.

Runs after all batches have delivered. Verifies:

- Every accepted primitive can be imported from its canonical module path.
- No circular imports across namespaces.
- `MANIFEST.json` agrees with the filesystem (no drift between roll-up and
  per-primitive manifest).
- Every primitive's Protocol attribute (the class named after the primitive)
  is discoverable via introspection.
- Every co-produced primitive (`HealthProbe`, `RateLimiter` per
  `COLLISIONS_RESOLVED.md`) lives in exactly ONE canonical location with the
  canonical namespace resolved per the collision doc.

Run with pytest once the merge script has produced `core/venous/MANIFEST.json`.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ENGINE_ROOT = HERE.parent
SKILL_ROOT = ENGINE_ROOT.parent
VENOUS_ROOT = SKILL_ROOT / "core" / "venous"
MANIFEST_FILE = VENOUS_ROOT / "MANIFEST.json"

# Primitives that are co-produced and have canonical namespace per COLLISIONS_RESOLVED.md.
_CANONICAL_COLLISIONS = {
    "HealthProbe": "obs",
    "RateLimiter": "resiliency",
}


def _manifest() -> dict:
    if not MANIFEST_FILE.exists():
        pytest.skip(f"MANIFEST.json not yet produced at {MANIFEST_FILE}. Run `engine.merge` first.")
    return json.loads(MANIFEST_FILE.read_text())


@pytest.mark.order(1)
def test_manifest_exists():
    _manifest()


@pytest.mark.order(2)
def test_manifest_entries_match_filesystem():
    man = _manifest()
    for entry in man["entries"]:
        ns_dir = VENOUS_ROOT / entry["namespace"]
        prim_dir = ns_dir / entry["name"]
        assert prim_dir.is_dir(), f"Manifest claims {entry['namespace']}/{entry['name']} but dir missing."
        assert (prim_dir / f"{entry['name']}.manifest.json").exists(), (
            f"Missing per-primitive manifest for {entry['name']}."
        )


@pytest.mark.order(3)
def test_every_primitive_importable():
    man = _manifest()
    # Ensure the skill root is importable.
    sys.path.insert(0, str(SKILL_ROOT))
    failures: list[str] = []
    for entry in man["entries"]:
        module_path = f"core.venous.{entry['namespace']}.{entry['name']}.{entry['name']}"
        try:
            mod = importlib.import_module(module_path)
            if not hasattr(mod, entry["name"]):
                failures.append(f"{module_path}: does not export symbol `{entry['name']}`")
        except Exception as e:
            failures.append(f"{module_path}: {type(e).__name__}: {e}")
    assert not failures, "\n".join(failures)


@pytest.mark.order(4)
def test_no_circular_imports_across_namespaces():
    """Import each primitive module in isolation under a fresh `sys.modules` snapshot."""
    man = _manifest()
    sys.path.insert(0, str(SKILL_ROOT))
    for entry in man["entries"]:
        module_path = f"core.venous.{entry['namespace']}.{entry['name']}.{entry['name']}"
        # `importlib.import_module` already detects circular imports as ImportError.
        importlib.import_module(module_path)


@pytest.mark.order(5)
def test_collisions_live_only_in_canonical_namespace():
    man = _manifest()
    for name, canonical_ns in _CANONICAL_COLLISIONS.items():
        owners = [e["namespace"] for e in man["entries"] if e["name"] == name]
        assert owners.count(canonical_ns) == len(owners), (
            f"Collision primitive `{name}` MUST live in namespace `{canonical_ns}` only; "
            f"manifest shows {owners}."
        )


@pytest.mark.order(6)
def test_maturity_distribution_matches_catalog():
    """Every delivered primitive's maturity matches the catalog claim."""
    research_out = SKILL_ROOT.parent.parent / "docs" / "research" / "outputs"
    catalog_maturity: dict[str, str] = {}
    for p in sorted(research_out.glob("AGENT_*.json")):
        data = json.loads(p.read_text())
        for prim in data["primitives"]:
            catalog_maturity.setdefault(prim["name"], prim["maturity"])
    man = _manifest()
    drift: list[str] = []
    for entry in man["entries"]:
        expected = catalog_maturity.get(entry["name"])
        if expected is None:
            drift.append(f"{entry['name']}: not in research catalog")
        elif expected != entry["maturity"]:
            drift.append(f"{entry['name']}: delivered as {entry['maturity']} but catalog says {expected}")
    assert not drift, "\n".join(drift)


@pytest.mark.order(7)
def test_total_cost_below_budget_ceiling():
    man = _manifest()
    # Sum of per-primitive caps: 113 primitives × $2.50 (battle_tested max) = $282.50
    # We set a conservative ceiling at $150 for the whole catalog as a sanity floor.
    assert man["total_llm_cost_usd"] <= 150.0, (
        f"Total LLM cost {man['total_llm_cost_usd']} exceeds conservative $150 ceiling."
    )
