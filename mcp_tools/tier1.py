"""Tier-1 meta-tools — the "awakening" surface the agent always sees.

Design per `/docs/research/DUAL_INDEX_DESIGN.md` §4.1 + ADR-0003. These
are the eight MCP tools defined in this module and always loaded into
the Claude session (primacy position 1). Everything else in the 201-tool
catalog becomes tier-2 (deferred) reachable via `fastapi_meta_search`,
`fastapi_meta_list_bundle`, or session activation via
`fastapi_meta_activate_bundle`.

DO NOT add a ninth tier-1 tool in this module without a protocol-version
bump. The cognition research (cap ≤ 8) + Anthropic's 30–50-tool
degradation threshold are the load-bearing constraints.

All eight return a uniform envelope:

    {
      "ok": bool,
      "what_happened": str,         # one-sentence human-readable
      "result": dict,                # the actual payload
      "next_steps": list[str],       # 2-5 concrete tool invocations
                                     # the agent should consider next
      "elapsed_ms": int,
    }

`next_steps` is THE affordance that drives natural use of the kit —
every return gives the agent 2-5 candidate next actions, phrased as
tool-invocation breadcrumbs. See the `breadcrumbs` module.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

SKILL_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = SKILL_ROOT / "engine" / "index" / "catalog.json"


# ---------------------------------------------------------------------------
# Shared envelope
# ---------------------------------------------------------------------------


def _envelope(
    *,
    ok: bool,
    what: str,
    result: Any,
    next_steps: list[str],
    t0: float,
) -> dict:
    return {
        "ok": ok,
        "what_happened": what,
        "result": result,
        "next_steps": next_steps[:5],  # cap — cognition says 3-5
        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
    }


def _load_catalog() -> dict:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# fastapi_home — the landscape at position 1
# ---------------------------------------------------------------------------

MCP_TOOL = {
    "name": "fastapi_meta_home",
    "description": (
        "ALWAYS CALL FIRST when asked to build / extend / deploy a FastAPI "
        "backend. Returns a compact map of the HuGR Arsenal: 10 domains "
        "(auth, data, api, realtime, resiliency, observability, compliance, "
        "deployment, testing, meta), per-domain tool counts, top-3 "
        "canonical tools per domain, primitive count, recipe count, and "
        "workflow breadcrumbs. One 1200-token call replaces flat 202-tool "
        "catalog introspection. Returns CATALOG state only — it does NOT "
        "read your repo; inspect the working directory yourself to decide "
        "whether to scaffold. After this, narrow with fastapi_meta_search "
        "or jump straight into fastapi_meta_scaffold."
    ),
    "tags": ["generator", "meta", "discovery"],
    "annotations": {"readOnlyHint": True, "destructiveHint": False},
}


def fastapi_meta_home() -> dict:
    """Return the landscape map. See MCP_TOOL description for intent."""
    t0 = time.perf_counter()
    catalog = _load_catalog()
    tools = catalog["tools"]
    primitives = catalog["primitives"]
    recipes = catalog["recipes"]

    # Domain map — for each domain, canonical top-3 tools by name (stable).
    by_domain: dict[str, list[dict]] = {}
    for t in tools:
        by_domain.setdefault(t["domain"], []).append(t)
    landscape: list[dict] = []
    for domain in catalog["domains"]:
        bucket = sorted(by_domain.get(domain, []), key=lambda x: x["name"])
        landscape.append(
            {
                "domain": domain,
                "tools": len(bucket),
                "top_3": [{"name": b["name"], "synopsis": b["synopsis"]} for b in bucket[:3]],
            }
        )
    # Schema v2 hierarchical surface (ADR-0003): skills + bundles. The
    # agent reads this to know which bundles exist BEFORE deciding
    # whether to activate one via fastapi_meta_activate_bundle.
    skills_view: list[dict] = []
    for s in catalog.get("skills", []):
        skills_view.append(
            {
                "name": s["name"],
                "version": s.get("version", ""),
                "type": s.get("type", "local"),
                "bundles": [
                    {
                        "name": b["name"],
                        "tool_count": b["tool_count"],
                        "tags": list(b.get("tags", [])),
                    }
                    for b in s.get("bundles", [])
                ],
            }
        )

    result = {
        "version": catalog.get("kit_commit", "unknown"),
        "schema_version": catalog["schema_version"],
        "counts": catalog["counts"],
        "verbs": list(catalog["verbs"]),
        "domains": list(catalog["domains"]),
        "skills": skills_view,
        "landscape": landscape,
        "workflow": [
            "1. fastapi_meta_scaffold(models={...}, owner_models={...}) — scaffold a fresh project (inspect your working directory first; the catalog map this tool returns does NOT include repo state)",
            '2. fastapi_meta_search(query="...") — find a capability in the 202-tool catalog',
            "3. <one of the returned fastapi_<domain>_add_*> — emit the slice",
            "4. fastapi_meta_audit() — verify the SKILL-KIT contract (not the emitted project; run pytest inside the scaffold for project-level validation)",
            "5. fastapi_meta_verify() — 10-tier quality gate on the skill's primitive registry (also skill-kit scoped)",
        ],
    }
    return _envelope(
        ok=True,
        what=f"landscape: {len(tools)} tools across {len(catalog['domains'])} domains, "
        f"{len(primitives)} primitives, {len(recipes)} recipes",
        result=result,
        next_steps=[
            "Call fastapi_meta_scaffold if you're starting a fresh project.",
            "Call fastapi_meta_search(query) to find a specific capability by natural language.",
            "Call fastapi_meta_describe(name) for the full schema of any tool / primitive / recipe.",
        ],
        t0=t0,
    )


# ---------------------------------------------------------------------------
# fastapi_search — BM25 over the catalog
# ---------------------------------------------------------------------------

# A tiny in-memory BM25 (Porter-light stemmer — matches engine/discovery
# conventions). Index is built lazily on first call, cached by catalog path.
_BM25_CACHE: dict | None = None


def _bm25_index(catalog: dict) -> dict:
    """Minimal BM25 index over tool/primitive/recipe synopses."""
    global _BM25_CACHE
    if _BM25_CACHE is not None and _BM25_CACHE.get("_sig") == catalog.get("kit_commit"):
        return _BM25_CACHE
    docs: list[dict] = []
    for t in catalog["tools"]:
        text = " ".join(
            [
                t["name"].replace("_", " "),
                t.get("synopsis", ""),
                t.get("when_to_call", ""),
                " ".join(t.get("tags", [])),
            ]
        ).lower()
        docs.append(
            {
                "kind": "tool",
                "name": t["name"],
                "synopsis": t["synopsis"],
                "domain": t["domain"],
                "verb": t["verb"],
                "tokens": _tokens(text),
            }
        )
    for p in catalog["primitives"]:
        text = f"{p['name']} {p['purpose']} {p['concern']}".lower()
        docs.append(
            {
                "kind": "primitive",
                "name": p["name"],
                "synopsis": p["purpose"],
                "domain": p["namespace"],
                "verb": "compose",
                "tokens": _tokens(text),
            }
        )
    # Inverted index
    n_docs = len(docs)
    df: dict[str, int] = {}
    for d in docs:
        for tok in set(d["tokens"]):
            df[tok] = df.get(tok, 0) + 1
    avgdl = sum(len(d["tokens"]) for d in docs) / n_docs if n_docs else 1
    _BM25_CACHE = {
        "_sig": catalog.get("kit_commit"),
        "docs": docs,
        "df": df,
        "N": n_docs,
        "avgdl": avgdl,
    }
    return _BM25_CACHE


_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return _WORD_RE.findall(text)


def _bm25_score(
    query_tokens: list[str], doc: dict, idx: dict, *, k1: float = 1.5, b: float = 0.75
) -> float:
    import math

    score = 0.0
    dl = len(doc["tokens"])
    if dl == 0:
        return 0.0
    tf_map: dict[str, int] = {}
    for t in doc["tokens"]:
        tf_map[t] = tf_map.get(t, 0) + 1
    for q in query_tokens:
        if q not in idx["df"]:
            continue
        tf = tf_map.get(q, 0)
        if tf == 0:
            continue
        df = idx["df"][q]
        idf = math.log((idx["N"] - df + 0.5) / (df + 0.5) + 1)
        denom = tf + k1 * (1 - b + b * dl / idx["avgdl"])
        score += idf * tf * (k1 + 1) / denom
    return score


MCP_TOOL_SEARCH = {
    "name": "fastapi_meta_search",
    "description": (
        "Search the HuGR FastAPI catalog (202 tools + 298 primitives + "
        "392 recipes) by natural language. Returns the top-K matching "
        "entries with synopsis, domain, verb, and next-step breadcrumbs. "
        "Use this when you know WHAT you need (e.g. 'exactly-once webhook', "
        "'tamper-evident audit', 'priority rate limiting') but NOT the "
        "exact tool name. Do NOT call on every turn — prefer direct tool "
        "invocation once you know the name. Accepts optional `domain` and "
        "`verb` filters to narrow."
    ),
    "tags": ["meta", "discovery"],
    "annotations": {"readOnlyHint": True, "destructiveHint": False},
}


def fastapi_meta_search(
    query: str,
    *,
    domain: str | None = None,
    verb: str | None = None,
    k: int = 10,
) -> dict:
    t0 = time.perf_counter()
    catalog = _load_catalog()
    idx = _bm25_index(catalog)
    q_tokens = _tokens(query.lower())
    if not q_tokens:
        return _envelope(
            ok=False,
            what="empty query",
            result={"hits": []},
            next_steps=["Pass a non-empty `query` string."],
            t0=t0,
        )
    scored: list[tuple[float, dict]] = []
    for doc in idx["docs"]:
        if domain and doc["domain"] != domain:
            continue
        if verb and doc["verb"] != verb:
            continue
        score = _bm25_score(q_tokens, doc, idx)
        if score > 0:
            scored.append((score, doc))
    scored.sort(key=lambda x: (-x[0], x[1]["name"]))  # stable tie-break by name
    top = scored[: max(1, min(int(k), 20))]
    hits = [
        {
            "kind": d["kind"],
            "name": d["name"],
            "synopsis": d["synopsis"],
            "domain": d["domain"],
            "verb": d["verb"],
            "score": round(s, 4),
        }
        for s, d in top
    ]
    next_steps: list[str] = []
    if hits:
        first = hits[0]
        if first["kind"] == "tool":
            next_steps.append(f"Call {first['name']}(...) with the inputs required by its schema.")
        else:
            next_steps.append(
                f"Compose with primitive {first['name']} — call fastapi_meta_describe('{first['name']}') for its Protocol + invariants."
            )
        next_steps.append("Need more detail on any hit? call fastapi_meta_describe(name).")
    else:
        next_steps.append("No hits — try a broader query or drop the domain/verb filter.")
        next_steps.append("Call fastapi_meta_home() for the landscape.")
    return _envelope(
        ok=True,
        what=f"{len(hits)} hit(s) for query {query!r}"
        + (f" in domain={domain}" if domain else "")
        + (f" verb={verb}" if verb else ""),
        result={"query": query, "domain": domain, "verb": verb, "hits": hits},
        next_steps=next_steps,
        t0=t0,
    )


# ---------------------------------------------------------------------------
# fastapi_describe — deep dive on a tool / primitive / recipe by name
# ---------------------------------------------------------------------------

MCP_TOOL_DESCRIBE = {
    "name": "fastapi_meta_describe",
    "description": (
        "Return the FULL catalog entry for a specific tool, primitive, or "
        "recipe. Accepts the canonical name (e.g. 'fastapi_auth_add_oauth2' "
        "or 'OptimisticConcurrency' or a recipe id). Returns: schema, "
        "when-to-call, when-NOT-to-call, primitives composed, test paths, "
        "example inputs/outputs. Use after fastapi_meta_search when "
        "you have a name and need the exact invocation shape."
    ),
    "tags": ["meta", "discovery"],
    "annotations": {"readOnlyHint": True, "destructiveHint": False},
}


def fastapi_meta_describe(name: str) -> dict:
    t0 = time.perf_counter()
    catalog = _load_catalog()
    for t in catalog["tools"]:
        if t["name"] == name or t.get("legacy_name") == name:
            return _envelope(
                ok=True,
                what=f"tool: {t['name']}",
                result={"kind": "tool", **t},
                next_steps=[
                    f"Call {t['name']}(...) with the appropriate arguments.",
                    "Call fastapi_meta_home() to zoom back out.",
                ],
                t0=t0,
            )
    for p in catalog["primitives"]:
        if p["name"] == name:
            return _envelope(
                ok=True,
                what=f"primitive: {p['name']}",
                result={"kind": "primitive", **p},
                next_steps=[
                    f"Import with: from core.venous.{p['namespace']}.{p['name']} import {p['name']}",
                    f"Search for recipes composing {p['name']} via fastapi_meta_search(query='{p['name']}').",
                ],
                t0=t0,
            )
    for r in catalog["recipes"]:
        if r["id"] == name:
            return _envelope(
                ok=True,
                what=f"recipe: {r['id']}",
                result={"kind": "recipe", **r},
                next_steps=[
                    f"Compose primitives: {', '.join(r['primitives'])}",
                    "Call fastapi_meta_describe(<primitive>) on each to see its Protocol.",
                ],
                t0=t0,
            )
    return _envelope(
        ok=False,
        what=f"no match for {name!r}",
        result={"kind": None},
        next_steps=[
            f"Call fastapi_meta_search(query='{name}') — the name may have legacy form.",
            "Call fastapi_meta_home() to browse the landscape.",
        ],
        t0=t0,
    )


# ---------------------------------------------------------------------------
# fastapi_scaffold — Rails-for-LLMs entry point
# ---------------------------------------------------------------------------

MCP_TOOL_SCAFFOLD = {
    "name": "fastapi_meta_scaffold",
    "description": (
        "Rails-for-LLMs macro scaffold. Pass `name` + `models` (dict of "
        "model_name → field_spec) + `owner_models` (dict of "
        "model → owner_field) and receive a fully-wired production FastAPI "
        "project: DB engine, alembic, auth (optional), middleware stack, "
        "CRUD routes, observability, Docker, tests. The opinionated default "
        "is profile='full'; pass profile='minimal' for a bare starter. "
        "BOLA opt-out: pass `shared_models` (iterable of model names also "
        "listed in `owner_models`) to suppress the per-object ownership "
        "guard for catalogue / lookup tables that track who created a row "
        "but are not user-private; each opt-out is captured in an audit "
        "test file the reviewer can grep for ('test_bola_shared_models'). "
        "After this call, use fastapi_<domain>_add_* tools to bolt on "
        "spec-specific capabilities (webhooks, rate limiting, RBAC, etc). "
        "This wraps generators.orchestrator.generate_project with "
        "Arsenal-aware defaults and emits `next_steps` that point at the "
        "exact add_* tools to call next given the requested models."
    ),
    "tags": ["generator", "meta"],
    "annotations": {"readOnlyHint": False, "destructiveHint": False},
}


def fastapi_meta_scaffold(
    output_dir: str,
    name: str = "app",
    models: dict[str, dict[str, str]] | None = None,
    owner_models: dict[str, str] | None = None,
    shared_models: list[str] | set[str] | None = None,
    *,
    profile: str = "full",
    with_auth: bool | None = None,
) -> dict:
    t0 = time.perf_counter()
    try:
        from generators.orchestrator import generate_project
    except ImportError as exc:
        return _envelope(
            ok=False,
            what=f"generators.orchestrator unavailable: {exc}",
            result={},
            next_steps=[],
            t0=t0,
        )
    kwargs: dict[str, Any] = {"output_dir": output_dir, "name": name, "profile": profile}
    if models is not None:
        kwargs["models"] = models
    if owner_models is not None:
        kwargs["owner_models"] = owner_models
    if shared_models is not None:
        # Normalise to set — generate_project accepts any iterable and
        # rejects names that are not in owner_models (caller-typo guard).
        kwargs["shared_models"] = set(shared_models)
    if with_auth is not None:
        kwargs["with_auth"] = with_auth
    try:
        res = generate_project(**kwargs)
    except Exception as exc:  # noqa: BLE001
        return _envelope(
            ok=False,
            what=f"scaffold failed: {exc}",
            result={},
            next_steps=[
                "Check that `models` is a dict of model_name → field-type map.",
                "Call fastapi_meta_home() for the expected signature.",
            ],
            t0=t0,
        )
    files = res.get("files_created") if isinstance(res, dict) else None
    files_count = len(files) if isinstance(files, list) else -1
    next_steps = [
        "Boot: python -m uvicorn app.main:app --port 8000 then GET /health.",
        f"For auth (signup/login/MFA/RBAC/sessions) → CALL fastapi_auth(action='bundle', params={{'output_dir':'{output_dir}'}}).",
        "For ONE auth feature only → fastapi_auth(action='<slice>', params={...}); use action='list' to see the tree.",
        "For exactly-once / idempotency / webhooks / rate-limit → fastapi_meta_search(query='<need>', k=5).",
        "When done, fastapi_meta_audit() validates the structural contract.",
    ]
    return _envelope(
        ok=True,
        what=f"scaffold emitted {files_count} files at {output_dir}",
        result={
            "files_created": files,
            "notes": res.get("notes") if isinstance(res, dict) else None,
        },
        next_steps=next_steps,
        t0=t0,
    )


# ---------------------------------------------------------------------------
# fastapi_audit — run contract_check
# ---------------------------------------------------------------------------

MCP_TOOL_AUDIT = {
    "name": "fastapi_meta_audit",
    "description": (
        "Run the full contract audit (engine.audit.contract_check — 36 "
        "machine-checkable rules spanning Phases 0-6) against the current "
        "SKILL-KIT tree (cwd=SKILL_ROOT). Returns rule-by-rule verdict + "
        "which rules failed + a one-line remediation per failing rule. "
        "Use after scaffolding + editing the kit itself (new primitive, "
        "new tool, doc update) to catch structural drift. Skill-kit "
        "integrity ONLY — this does NOT validate an emitted project; "
        "for project-level validation, run `pytest` inside the scaffold. "
        "Cheap — completes in ≤ 10 seconds."
    ),
    "tags": ["meta", "testing"],
    "annotations": {"readOnlyHint": True, "destructiveHint": False},
}


def fastapi_meta_audit() -> dict:
    t0 = time.perf_counter()
    import subprocess
    import sys

    out = subprocess.run(
        [sys.executable, "-m", "engine.audit.contract_check", "--quiet"],
        cwd=SKILL_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    text = (out.stdout or "") + (out.stderr or "")
    # The quiet mode prints only failures; success prints the final summary line.
    lines = [line for line in text.splitlines() if line.strip()]
    summary = lines[-1] if lines else ""
    failures = [line for line in lines if line.strip().startswith("✗")]
    ok = out.returncode == 0 and not failures
    next_steps: list[str] = []
    if ok:
        next_steps.append("Contract green. If benchmarking, call the blind harness.")
    else:
        for f in failures[:3]:
            next_steps.append(f"Fix: {f.strip()}")
        next_steps.append("Rerun fastapi_meta_audit() after each fix.")
    return _envelope(
        ok=ok,
        what=summary or ("audit passed" if ok else f"audit exited {out.returncode}"),
        result={"summary": summary, "failures": failures, "returncode": out.returncode},
        next_steps=next_steps,
        t0=t0,
    )


# ---------------------------------------------------------------------------
# fastapi_verify — 10-tier gate on a primitive
# ---------------------------------------------------------------------------

MCP_TOOL_VERIFY = {
    "name": "fastapi_meta_verify",
    "description": (
        "Run the 10-tier quality gate (T0 compile → T9 provenance) on a "
        "single primitive or the full primitive registry of the SKILL KIT "
        "(cwd=SKILL_ROOT, not an emitted project). Returns per-tier "
        "pass/fail + which primitives failed which tier. Use after adding "
        "a new primitive or refactoring an existing one; a CI-grade sanity "
        "check stricter than `fastapi_meta_audit`. Skill-kit integrity "
        "ONLY — for emitted-project validation, run `pytest` inside the "
        "scaffold. Pass `primitive=<Name>` for a single primitive, or "
        "omit for all 124 registered."
    ),
    "tags": ["meta", "testing"],
    "annotations": {"readOnlyHint": True, "destructiveHint": False},
}


def fastapi_meta_verify(primitive: str | None = None) -> dict:
    t0 = time.perf_counter()
    import subprocess
    import sys

    cmd = [sys.executable, "-m", "engine.check_primitive"]
    if primitive:
        cmd += ["--name", primitive]
    out = subprocess.run(
        cmd,
        cwd=SKILL_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    text = (out.stdout or "") + (out.stderr or "")
    return _envelope(
        ok=out.returncode == 0,
        what=f"10-tier gate exit={out.returncode}"
        + (f" on {primitive}" if primitive else " on all primitives"),
        result={"returncode": out.returncode, "tail": text[-1500:]},
        next_steps=(
            ["Fix the failing tier (see tail)."]
            if out.returncode != 0
            else ["All tiers green. Continue development or commit."]
        ),
        t0=t0,
    )


# ---------------------------------------------------------------------------
# fastapi_meta_list_bundle — list tools in a bundle (schema v2)
#
# Sits between fastapi_meta_home (skill+bundle map) and fastapi_meta_describe
# (single-entry schema). When a bundle name has been identified, this tool
# returns the bundle's tool roster — bounded by ~80 entries even at 10K
# total catalog size, so it stays useful as the kit federates.
# ---------------------------------------------------------------------------

MCP_TOOL_LIST_BUNDLE = {
    "name": "fastapi_meta_list_bundle",
    "description": (
        "List the tools belonging to a specific bundle within a skill. "
        "Call this after fastapi_meta_home / fastapi_meta_search identifies "
        "a bundle you want to explore (e.g. 'crud_data', 'auth_access', "
        "'infrastructure'). Returns the bundle's tool names + synopses + "
        "tags. Caps at one bundle's slice (typically a few dozen entries) "
        "vs the full 202 tools diluted in a flat list, and scales the same "
        "way as the kit grows toward 10K tools. Pass `skill` only when "
        "SKILL-002 onward ship; "
        "today the single skill SKILL-001-fastapi-production is the default."
    ),
    "tags": ["meta", "discovery"],
    "entry": "fastapi_meta_list_bundle",
    "annotations": {"readOnlyHint": True, "destructiveHint": False},
}


def fastapi_meta_list_bundle(bundle_name: str, skill: str | None = None) -> dict:
    """Return tools belonging to the named bundle.

    Args:
        bundle_name: e.g. "crud_data", "auth_access", "infrastructure".
        skill: Optional skill name; defaults to the only skill present
            (SKILL-001-fastapi-production today). Required only when
            SKILL-002 onwards ship.

    Returns: standard meta envelope with:
        result.bundle: {name, skill, tool_count, tags}
        result.tools: [{name, synopsis, domain, verb, tags}, ...]
        next_steps: ["fastapi_meta_describe(name=...) for details",
                     "fastapi_meta_activate_bundle to surface these in
                      tools/list", ...]
    """
    t0 = time.perf_counter()
    catalog = _load_catalog()
    skills_list = catalog.get("skills", [])
    if not skills_list:
        return _envelope(
            ok=False,
            what="catalog has no skills entry",
            result={"bundle": None, "tools": []},
            next_steps=["Regenerate catalog: python -m engine.index.manifest build"],
            t0=t0,
        )
    if skill is None:
        skill = skills_list[0].get("name")
    skill_entry = next((s for s in skills_list if s.get("name") == skill), None)
    if skill_entry is None:
        return _envelope(
            ok=False,
            what=f"unknown skill {skill!r}",
            result={"bundle": None, "tools": []},
            next_steps=[
                "Call fastapi_meta_home() to list available skills.",
            ],
            t0=t0,
        )
    bundle_entry = next(
        (b for b in skill_entry.get("bundles", []) if b.get("name") == bundle_name),
        None,
    )
    if bundle_entry is None:
        available = [b.get("name") for b in skill_entry.get("bundles", [])]
        return _envelope(
            ok=False,
            what=f"unknown bundle {bundle_name!r} in {skill}",
            result={"bundle": None, "tools": [], "available": available},
            next_steps=[
                "Call fastapi_meta_home() to see all bundles in this skill.",
                f"Available bundles: {', '.join(available)}",
            ],
            t0=t0,
        )

    tools_view = [
        {
            "name": t["name"],
            "synopsis": t.get("synopsis", ""),
            "domain": t.get("domain", ""),
            "verb": t.get("verb", ""),
            "tags": list(t.get("tags", [])),
        }
        for t in catalog["tools"]
        if t.get("skill") == skill and t.get("bundle") == bundle_name
    ]
    tools_view.sort(key=lambda x: x["name"])

    return _envelope(
        ok=True,
        what=f"bundle {bundle_name!r}: {len(tools_view)} tools in {skill}",
        result={
            "bundle": {
                "name": bundle_name,
                "skill": skill,
                "tool_count": bundle_entry.get("tool_count", len(tools_view)),
                "tags": list(bundle_entry.get("tags", [])),
            },
            "tools": tools_view,
        },
        next_steps=[
            f"Call fastapi_meta_describe(name='{tools_view[0]['name']}') for details on the first tool."
            if tools_view
            else "Bundle is empty; try fastapi_meta_home() to pick another.",
            f"Call fastapi_meta_activate_bundle(bundle_name='{bundle_name}') to surface these tools in tools/list.",
            "Call fastapi_meta_search(query=...) inside this bundle's domain to narrow further.",
        ],
        t0=t0,
    )


# ---------------------------------------------------------------------------
# fastapi_meta_activate_bundle — session-scoped bundle activation
#
# Activation toggles a bundle's tools INTO tools/list for the current
# session. Default tools/list returns only the eight tier-1 meta tools;
# activating a bundle adds its slice on top. This is CLUTTER management
# (keeps the agent's tool surface focused), NOT access control — every
# tool remains callable via tools/call regardless of activation; auth/
# scopes still gate the actual call.
# ---------------------------------------------------------------------------

MCP_TOOL_ACTIVATE_BUNDLE = {
    "name": "fastapi_meta_activate_bundle",
    "description": (
        "Mark a bundle as ACTIVE in the current session. Subsequent "
        "tools/list calls will include this bundle's tools alongside "
        "the tier-1 meta tools. Use to surface a focused tool subset "
        "for a working session without loading the entire catalogue "
        "(clutter management, not access control — scopes still gate "
        "tools/call). Activation is session-scoped via a ContextVar; "
        "resetting the session clears it."
    ),
    "tags": ["meta", "discovery", "session"],
    "entry": "fastapi_meta_activate_bundle",
    "annotations": {"readOnlyHint": False, "destructiveHint": False},
}


def fastapi_meta_activate_bundle(bundle_name: str, skill: str | None = None) -> dict:
    """Activate a bundle for the current session.

    Uses a contextvars.ContextVar (see ``mcp_tools.discovery``) to track
    active bundles per session. On session close, state resets.

    Returns: envelope with result.activated_bundles list + total tool
    count surfaced in tools/list afterwards.
    """
    t0 = time.perf_counter()
    catalog = _load_catalog()
    skills_list = catalog.get("skills", [])
    if skill is None and skills_list:
        skill = skills_list[0].get("name")
    skill_entry = next((s for s in skills_list if s.get("name") == skill), None)
    if skill_entry is None:
        return _envelope(
            ok=False,
            what=f"unknown skill {skill!r}",
            result={"activated_bundles": [], "tool_count": 0},
            next_steps=["Call fastapi_meta_home() to list skills."],
            t0=t0,
        )
    available = {b.get("name") for b in skill_entry.get("bundles", [])}
    if bundle_name not in available:
        return _envelope(
            ok=False,
            what=f"unknown bundle {bundle_name!r}",
            result={"activated_bundles": [], "tool_count": 0, "available": sorted(available)},
            next_steps=[
                f"Available: {', '.join(sorted(available))}",
                "Call fastapi_meta_home() for the full skill/bundle map.",
            ],
            t0=t0,
        )
    # Import lazily to avoid a cyclic import with discovery.py.
    from mcp_tools.discovery import activate_bundle as _activate

    active = _activate(bundle_name)
    bundle_tool_count = sum(
        1 for t in catalog["tools"] if t.get("bundle") in active and t.get("skill") == skill
    )
    return _envelope(
        ok=True,
        what=f"activated bundle {bundle_name!r} ({len(active)} bundle(s) active)",
        result={
            "activated_bundles": sorted(active),
            "tool_count": bundle_tool_count,
        },
        next_steps=[
            "Subsequent tools/list calls now include this bundle's tools.",
            f"Call fastapi_meta_list_bundle(bundle_name='{bundle_name}') to inspect them.",
            "Activation resets when the session ends.",
        ],
        t0=t0,
    )


# ---------------------------------------------------------------------------
# MCP_TOOL surface inventory — eight tier-1 dicts in this module.
#
# Naming convention: each module-level `MCP_TOOL*` variable is a distinct
# dict that the discovery scanner registers. The set is enforced by audit
# rule B2.7 (engine/audit/contract_check.py). The eight are:
#
#   MCP_TOOL                  → fastapi_meta_home
#   MCP_TOOL_SEARCH           → fastapi_meta_search
#   MCP_TOOL_DESCRIBE         → fastapi_meta_describe
#   MCP_TOOL_SCAFFOLD         → fastapi_meta_scaffold
#   MCP_TOOL_AUDIT            → fastapi_meta_audit
#   MCP_TOOL_VERIFY           → fastapi_meta_verify
#   MCP_TOOL_LIST_BUNDLE      → fastapi_meta_list_bundle
#   MCP_TOOL_ACTIVATE_BUNDLE  → fastapi_meta_activate_bundle
#
# `MCP_TOOL_HOME` was retired during WAVE-0-F2 (it aliased MCP_TOOL — a
# dummy entry inflated the surface count without adding a distinct
# behaviour). The compose tool lives in `mcp_tools/compose.py` and is
# registered by `register_tier1_tools` alongside this set.
# ---------------------------------------------------------------------------

# Wire each MCP_TOOL_<X> to the matching entry function — the discovery
# loop needs to know which callable to register for each metadata dict.
MCP_TOOL["entry"] = "fastapi_meta_home"
MCP_TOOL_SEARCH["entry"] = "fastapi_meta_search"
MCP_TOOL_DESCRIBE["entry"] = "fastapi_meta_describe"
MCP_TOOL_SCAFFOLD["entry"] = "fastapi_meta_scaffold"
MCP_TOOL_AUDIT["entry"] = "fastapi_meta_audit"
MCP_TOOL_VERIFY["entry"] = "fastapi_meta_verify"
MCP_TOOL_LIST_BUNDLE["entry"] = "fastapi_meta_list_bundle"
MCP_TOOL_ACTIVATE_BUNDLE["entry"] = "fastapi_meta_activate_bundle"
