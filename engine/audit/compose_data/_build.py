"""WP-17 — §B1.1 + §B1.2 builder: the only filesystem-touching module.

Implements ``build()``: scan ``core/venous/*/*/*.manifest.json`` (excluding
``_staging/``), validate every curated ``E`` entry against the manifest
set, emit ``engine/primitives_by_concern.yaml`` sorted by ``(namespace,
name)`` with the hand-rolled YAML writer (see F-07 — do NOT swap to
``yaml.safe_dump``), and idempotently append the ``## Compose with:``
section to every primitive ``.md`` that lacks one.

Idempotency contract (F-06): the ``if "## Compose with:" in body:`` short-
circuit MUST stay byte-for-byte; second run reports ``appended=0``.
"""

from __future__ import annotations

import json
from pathlib import Path

from engine.audit.compose_data._assembly import EMERGING, E
from engine.audit.compose_data._constants import (
    REGISTRY,
    SKILL_ROOT,
    VENOUS,
    concern_for,
)

__all__ = ["build"]


def build() -> None:
    # Collect manifests
    manifests = sorted([m for m in VENOUS.rglob("*.manifest.json") if "_staging" not in m.parts])

    primitives = []
    known_names: set[str] = set()
    for m in manifests:
        data = json.loads(m.read_text())
        known_names.add(data["name"])

    missing_data = [name for name in known_names if name not in E]
    if missing_data:
        raise SystemExit(f"Missing curated entries for: {sorted(missing_data)}")

    for m in manifests:
        data = json.loads(m.read_text())
        ns = data["namespace"]
        name = data["name"]
        purpose, compose_with, _patterns = E[name]
        # Validate compose_with: 2-5 siblings, all known
        if not (2 <= len(compose_with) <= 5):
            raise SystemExit(f"{name}: compose_with has {len(compose_with)} entries (need 2-5)")
        bad = [c for c in compose_with if c not in known_names]
        if bad:
            raise SystemExit(f"{name}: dangling compose_with refs: {bad}")
        primitives.append(
            {
                "name": name,
                "namespace": ns,
                "concern": concern_for(ns, name),
                "purpose": purpose,
                "compose_with": compose_with,
            }
        )

    # Sort by (namespace, name)
    primitives.sort(key=lambda p: (p["namespace"], p["name"]))

    # Emit YAML by hand (no dep)
    def yaml_str(s: str) -> str:
        # Always quote to be safe for YAML 1.2; escape embedded quotes.
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'

    lines = ["version: 1", "primitives:"]
    for p in primitives:
        lines.append(f"  - name: {p['name']}")
        lines.append(f"    namespace: {p['namespace']}")
        lines.append(f"    concern: {p['concern']}")
        lines.append(f"    purpose: {yaml_str(p['purpose'])}")
        lines.append("    compose_with:")
        for c in p["compose_with"]:
            lines.append(f"      - {c}")
    REGISTRY.write_text("\n".join(lines) + "\n")
    print(f"[§B1.1] wrote {REGISTRY.relative_to(SKILL_ROOT)} with {len(primitives)} entries")

    # Include emerging primitives in the universe so cross-refs validate.
    known_all = set(known_names) | set(EMERGING.keys())

    # §B1.2 — append Compose with: section (production + emerging)
    appended = 0
    already = 0
    # Build an iterable of (md_path, name, patterns) covering both.
    targets: list[tuple[Path, str, list]] = []
    for m in manifests:
        data = json.loads(m.read_text())
        name = data["name"]
        md_path = m.parent / f"{name}.md"
        _purpose, _cw, patterns = E[name]
        targets.append((md_path, name, patterns))
    for name, patterns in EMERGING.items():
        # discover md path by searching
        hits = list(VENOUS.rglob(f"{name}/{name}.md"))
        hits = [h for h in hits if "_staging" not in h.parts]
        if not hits:
            raise SystemExit(f"emerging {name}: md not found under core/venous/*/{name}/")
        targets.append((hits[0], name, patterns))

    for md_path, name, patterns in targets:
        if not md_path.exists():
            raise SystemExit(f"Missing .md: {md_path}")
        body = md_path.read_text()
        if "## Compose with:" in body:
            already += 1
            continue
        if len(patterns) < 3:
            raise SystemExit(f"{name}: need ≥3 compose patterns, got {len(patterns)}")
        for pname, siblings, _inv in patterns:
            if len(siblings) < 2:
                raise SystemExit(f"{name}/{pname}: need ≥2 siblings")
            bad = [s for s in siblings if s not in known_all]
            if bad:
                raise SystemExit(f"{name}/{pname}: dangling refs {bad}")
        _ = patterns  # keep below
        # Build section text
        out = []
        out.append("## Compose with:")
        out.append("")
        for pname, siblings, inv in patterns:
            bullets = " + ".join(f"`{s}`" for s in siblings)
            out.append(f"- **{pname}** → {bullets}")
            out.append(f"  {inv}")
            out.append("")
        section = "\n".join(out).rstrip() + "\n"
        # Ensure trailing newline before append
        if not body.endswith("\n"):
            body += "\n"
        if not body.endswith("\n\n"):
            body += "\n"
        md_path.write_text(body + section)
        appended += 1
    print(f"[§B1.2] appended {appended} sections; {already} already present")
