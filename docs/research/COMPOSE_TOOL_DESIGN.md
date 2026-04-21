# `fastapi_meta_compose` — Design Document (v1, 2026-04-20)

> Mission: close the "last mile" between `fastapi_meta_search_search` (find
> primitives) and running code (primitives wired into a FastAPI app). Today
> Maestro must hand-write the glue — `fastapi_meta_compose` emits it.

## TLDR (5 bullets)

1. **Hybrid input; primacy to `recipe_id`.** Accept `recipe_id` OR
   `primitives: list[str]`; reject `capability: str` at this tier
   (that's what `fastapi_meta_search_search` already does — do not duplicate).
   If both are passed, `recipe_id` wins and `primitives` is treated as a
   subset-assertion. Precedent: LlamaIndex `ObjectIndex` is the discovery
   tier; `ToolSpec` bundles are the composition tier — they are deliberately
   two tools (`docs.llamaindex.ai/en/stable/module_guides/deploying/agents/tools/`).
2. **Three emission modes, picked automatically: `adapter_reuse` →
   `recipe_template` → `ad_hoc`.** 32 FastAPI adapters already exist at
   `core/venous/_adapters/fastapi/*Adapter.py` (e.g. `WebhookReceiverAdapter.install()`
   wires exactly `SignatureVerifier + IdempotentConsumer + AuditEvent`).
   When the requested primitive-set matches a shipped adapter, emit a
   3-line `install(app, ...)` call-site instead of re-deriving wiring.
   When no adapter exists but a recipe does, render a vetted Jinja2
   template. Otherwise emit an AST-valid skeleton with a
   `# WARNING: no canonical recipe` banner. This is the Rails-`scaffold`
   → Rails-generator fallthrough (Rails Guides §Command Line).
3. **Emit one file: `app/compositions/<slug>.py` exporting `install(app, ...)`.**
   Mirrors the existing adapter idiom verbatim (see
   `core/venous/_adapters/fastapi/WebhookReceiverAdapter.py:38` for the
   canonical `install(app, *, ...)` signature). FastAPI's own docs treat
   "include_router + wire in main.py" as the project-structure convention
   (`fastapi.tiangolo.com/tutorial/bigger-applications/`). ONE file per
   composition keeps diffs surgical and mypy-checkable.
4. **Jinja2, not AST construction, not pure f-strings.** Recipe template
   bodies live under `engine/templates/compositions/*.py.j2`. AST-build is
   rejected: the emitted surface is 30-line glue, not a DSL; AST construction
   pays a 10× authoring cost for sub-1% correctness gain. Pure f-strings are
   rejected: brittle quoting, no partials. Cookiecutter uses Jinja2 — same
   family; near-zero learning cost.
5. **Scope is INFRASTRUCTURE plumbing only.** Compose wires
   verify-dedup-audit-retry-ratelimit. It does NOT emit domain rules
   ("cancel < 2h charges fee") — those are Aggregate + Specification
   authored by Maestro. If the caller passes an Aggregate-shaped primitive
   (e.g. `Aggregate`, `Specification`, `DomainEvent`), `fastapi_meta_compose`
   refuses with `next_steps = ["Author your Aggregate + Specification; then
   compose the infra plumbing around it."]`. This boundary is load-bearing —
   see §8.

---

## 1. Input schema

```python
def fastapi_meta_compose(
    output_dir: str,                    # required — target project root
    *,
    recipe_id: str | None = None,       # preferred — picks a vetted recipe
    primitives: list[str] | None = None,  # alternative — names from catalog
    name: str | None = None,            # emitted file slug (default derived)
    mount_path: str = "/",              # FastAPI mount point for the router
    dry_run: bool = False,              # return source without writing
    force: bool = False,                # overwrite existing composition
) -> dict:  # tier-1 envelope
```

### Why this shape

- **`recipe_id` first** — The 385 recipes in `catalog.json:5262+` are the
  pre-validated compositions. `AccessLog__03_tamperevidentauditlog-signatureverifier-`
  is a deterministic handle that survives rewording. Precedent: Yeoman
  sub-generators are invoked by slug (`yo angular:controller`); Rails
  scaffold by name (`rails g scaffold User`).
- **`primitives` as escape hatch** — When Maestro already knows it wants
  `SignatureVerifier + IdempotentConsumer + TamperEvidentAuditLog` but no
  recipe id is handy, take the list. The tool then reverse-matches against
  `catalog.recipes[*].primitives` to pick the best recipe; on no match,
  falls through to `ad_hoc` mode.
- **No `capability: str` param** — duplicates `fastapi_meta_search_search`.
  Orthogonality principle (Anthropic tool-writing guide, Oct 2025): "tools
  should do one thing."
- **`mount_path` instead of router name** — FastAPI idiomatic knob
  (`fastapi.tiangolo.com/tutorial/bigger-applications/#include-an-apirouter-with-a-custom-prefix`).
- **`dry_run` is mandatory convention** — every tool in the kit ships it
  (`CLAUDE.md` patterns block: "`dry_run: returns before any write`").

### Rejected alternatives

| Option | Rejected because |
|---|---|
| `capability: str` (NL) | Duplicates search tier; introduces non-determinism. |
| `profile: Literal["minimal","full"]` | Scaffold's concept; compose is slice-level. |
| `models: dict[str, dict]` | Domain concern; compose is infra-only. |
| `router: APIRouter` (object) | Not MCP-serializable. |

---

## 2. Output schema

Uses the tier-1 envelope (`mcp_tools/tier1.py:43-52`):

```python
{
  "ok": bool,
  "what_happened": str,         # "composed 3 primitives into compositions/webhook_sink.py"
  "result": {
    "composition_id": "webhook_sink",                   # slug written
    "mode": "adapter_reuse" | "recipe_template" | "ad_hoc",
    "files_written": ["app/compositions/webhook_sink.py",
                      "app/compositions/test_webhook_sink.py"],
    "composition_source": "<full emitted .py text>",    # for inspection
    "wiring_summary": "SignatureVerifier verifies → IdempotentConsumer dedupes → TamperEvidentAuditLog seals",
    "primitives_used": [
        {"name": "SignatureVerifier", "module": "core.venous.security.SignatureVerifier.SignatureVerifier",
         "role": "entry-guard"},
        {"name": "IdempotentConsumer", "module": "core.venous.events.IdempotentConsumer.IdempotentConsumer",
         "role": "body-gate"},
        {"name": "TamperEvidentAuditLog", "module": "core.venous.compliance.TamperEvidentAuditLog.TamperEvidentAuditLog",
         "role": "post-effect"},
    ],
    "recipe_used": "IdempotentConsumer__01_webhook-receiver" | None,
    "mount": {"router_var": "router", "path": "/webhooks/in"},
    "validation_report": {
        "ast_parse": true,
        "imports_resolved": true,          # all primitive modules found on disk
        "ruff_check": "pass" | "skipped",  # skipped if ruff not installed
        "mypy_strict": "skipped"           # deferred — see §7
    },
  },
  "next_steps": [
      "In app/main.py: from app.compositions.webhook_sink import install; install(app)",
      "Call fastapi_meta_check_audit() to verify contract drift.",
      "Run the emitted test_webhook_sink.py to validate the wiring end-to-end.",
  ],
  "elapsed_ms": int,
}
```

### Why these fields

- `composition_source` — lets Maestro inspect-before-write (token-efficient
  review; precedent: Anthropic Oct 2025 guidance, "tools should let the
  agent see what it got").
- `wiring_summary` — human-readable 1-liner; the 32 recipes we inspected all
  describe composition as "A → B → C"; mirror that.
- `role` per primitive — NOT a free field. Drawn from a closed vocabulary
  (`entry-guard | body-gate | post-effect | outbound | scheduler |
  observer`) derived from the 385-recipe corpus by inspection.
- `recipe_used` is nullable — `mode="ad_hoc"` always null.
- `validation_report` — cheap checks only (AST + import-resolution).
  `mypy --strict` is deliberately deferred to a future `fastapi_meta_verify_compose`
  call; running mypy inline inflates p95 to >5s which kills conversational UX.

---

## 3. Composition strategies — three-tier fallthrough

```
           primitives / recipe_id
                   │
                   ▼
     ┌──────────────────────────┐
     │ 1. match against 32      │   YES → mode="adapter_reuse"
     │    FastAPI adapters      │ ───────► emit 3-line install() call-site
     └──────────────────────────┘
                   │ NO
                   ▼
     ┌──────────────────────────┐
     │ 2. match against 385     │   YES → mode="recipe_template"
     │    recipes in catalog    │ ───────► render Jinja2 template
     └──────────────────────────┘
                   │ NO
                   ▼
     ┌──────────────────────────┐
     │ 3. ad_hoc skeleton       │   mode="ad_hoc"
     │    (banner: unverified)  │ ───────► emit skeleton; flag quality=LOW
     └──────────────────────────┘
```

### A. `adapter_reuse` (highest quality)

Exists today. E.g. `{SignatureVerifier, IdempotentConsumer, AuditEvent}` →
`WebhookReceiverAdapter.install()` at
`core/venous/_adapters/fastapi/WebhookReceiverAdapter.py:38`. The emitted
file is a 20-line wrapper that calls `install()` on the pre-built adapter.
Matching rule: set-equality between requested primitive names and
adapter's imported primitives (discovered by AST-parsing the adapter file
at compose-time — already done by the catalog builder).

### B. `recipe_template` (medium quality)

The 385 recipes are authored bullets like (`catalog.json:5286-5294`):

```json
{
  "id": "AccessLog__03_tamperevidentauditlog-signatureverifier-",
  "primitives": ["SignatureVerifier", "TamperEvidentAuditLog"],
  "intent": "`TamperEvidentAuditLog` + `SignatureVerifier` Access records seal…",
  "description": "**Tamper-evident forensics** → ..."
}
```

Each recipe has a corresponding `engine/templates/compositions/<recipe_id>.py.j2`
maintained ALONGSIDE the source primitive's `.md` (authorship discipline:
if you add a `## Compose with:` bullet, you also add the template). The
catalog builder refuses commit if a recipe has no template (hard gate;
analogous to the T0 compile gate already in the skill).

**Note on scale:** 385 templates is too many to hand-author on day one.
Pragmatic rollout: ship templates for the **top 30 recipes by BM25
centrality** (= recipes whose primitives appear in the most other
recipes). The remaining 355 degrade to `ad_hoc` with a banner. Telemetry
drives what to promote next.

### C. `ad_hoc` (low quality, always emits a banner)

Last-resort skeleton:

```python
# WARNING: no canonical recipe exists for this primitive combination.
# This composition is a best-effort skeleton — review carefully before
# deploying. Consider filing a new `## Compose with:` bullet upstream.
```

Skeleton walks the primitives in import-order (namespace then name,
deterministic), instantiates each via its documented factory, and wires
them in a linear pipeline. Quality flag surfaced in `validation_report`.

---

## 4. Output file layout

```
<output_dir>/
  app/
    compositions/
      __init__.py                   # created if absent
      <slug>.py                     # THE emitted composition
      test_<slug>.py                # smoke test (adapter_reuse+recipe modes)
    main.py                         # NOT TOUCHED — Maestro wires the import
```

### Why this layout

- `app/compositions/` is a new directory — no collision with existing
  scaffold layout (verified: `generators/orchestrator.py` emits
  `app/{core,routers,models,middleware,...}` but no `compositions/`).
- ONE file per composition — supports surgical diffs, per-composition
  tests, and MCP-sized tool calls (a compose invocation returns ≤ 2 files).
  Contrast with the auth-bundle path (`mcp_tools/tree/auth.py:252`) which
  emits 8 slices at once — that's scaffold-tier; compose is slice-tier.
- `install(app, *, ...)` callable exported. Signature copied verbatim from
  `WebhookReceiverAdapter.install` at line 38. FastAPI convention:
  routers are functions of `FastAPI` instances
  (`fastapi.tiangolo.com/tutorial/bigger-applications/`).
- `main.py` is NEVER edited by compose. Rationale: two-way-merge on
  `main.py` is the #1 source of "silently broke my app" bug reports in
  similar tools (Rails PR#42901 `app/application_controller.rb` wars).
  Maestro gets a `next_steps` breadcrumb with the exact one-line import.

---

## 5. Template engine

**Decision: Jinja2.**

| Option | Verdict | Rationale |
|---|---|---|
| Pure f-strings | Rejected | Brittle quoting, no conditionals, no partials. |
| Jinja2 | **Chosen** | Familiar, proven (Cookiecutter, FastAPI docs, Flask). Standard lib for templating in Python. Supports includes/macros for the 30 recipe templates → shared `_imports.j2` macro. |
| AST construction (`ast.Module`) | Rejected | 10× authoring cost for <1% correctness gain. Emitted code is 30-line glue, not a DSL. |
| Per-recipe hand-written `.py` files that import-and-run | Rejected | 385 files; maintenance nightmare; kills the catalog-as-data-only invariant (recipes are data in JSON; code is derived). |

Existing skill code already depends on Jinja2 implicitly via Alembic
(`generators/database/`) — adding it explicitly costs zero.

Template location: `skills/SKILL-001-fastapi-production/engine/templates/compositions/`.
Naming: one `<recipe_id>.py.j2` per shipped template. A shared
`_base.py.j2` handles the `install(app, ...)` scaffolding + banner.

---

## 6. Type-safety + validation

**Must run** (before return, within the 5-min cache window):

1. **`ast.parse(source)`** — already a kit pattern
   (`CLAUDE.md` patterns: "`ast_parse: validation loop before success return`").
   Hard fail on syntax error.
2. **Import resolution check** — for each `from core.venous.X.Y import Z`,
   verify `<output_dir>/app/core/venous/X/Y.py` exists (the scaffold or
   a prior `fastapi_auth(action='primitive')` call must have copied it).
   Surfaces the "you called compose before copying the primitives" failure
   with a clean error.

**Must NOT run inline** (deferred to `fastapi_meta_verify`):

3. `ruff check` — nice-to-have; skip when `ruff` not on PATH.
4. `mypy --strict` — too slow (p95 >3s on a 30-line file). Emitted code is
   annotated with PEP 604 types and stdlib-only (except for primitive
   imports), so mypy is valuable but not latency-appropriate for compose.

Precedent: SWE-agent ACI principle "lint-on-edit, not compile-on-edit"
(arxiv:2405.15793, §3). Fast feedback for syntax; defer semantic checks.

---

## 7. Failure modes + recovery

All failures return `ok=False` with an actionable `next_steps`. Closed list:

| Failure | Shape of error | `next_steps` breadcrumb |
|---|---|---|
| Unknown primitive name | `what_happened="unknown primitive 'Foo'"` + `result.suggestions=[3 closest]` | `["fastapi_meta_search_search(query='Foo') to find the correct name."]` |
| Unknown `recipe_id` | `what_happened="no recipe with id '<id>'"` | `["Call fastapi_meta_search_describe('<id>') — maybe a stale id."]` |
| `primitives` disagrees with `recipe_id` contents | `what_happened="recipe <id> requires [A,B,C]; you passed [A,B,D]"` | `["Drop the 'primitives' arg and keep only recipe_id.", "Or drop recipe_id and let compose match from primitives."]` |
| Incompatible signatures (rare — adapter mode only) | `what_happened="cannot wire X.output (A) into Y.input (B) — type mismatch"` | `["Add a translating primitive (AntiCorruptionLayer) between X and Y."]` |
| Duplicate primitive in list | Deduplicate silently; log in `what_happened` | `[]` |
| Target file exists + `force=False` | `what_happened="app/compositions/<slug>.py exists; pass force=True to overwrite"` | `["Re-call with force=True to overwrite, or choose a different name='<slug2>'."]` |
| Generated code has syntax error | Self-abort, return `ok=False`, DO NOT write | `["File an issue with the recipe_id; this is a template bug."]` (internal corruption — should never happen; if it does, template needs fixing, not caller) |
| Domain-concern primitive requested (`Aggregate`, `Specification`, `DomainEvent`) | `what_happened="compose is infra-only; <Primitive> is a domain building block"` | `["Author Aggregate + Specification yourself in app/domain/.", "Compose handles verify/dedupe/audit/retry/ratelimit."]` |
| Scaffold not yet run (`<output_dir>/app` absent) | `what_happened="no app/ directory at <output_dir>"` | `["Call fastapi_meta_generate_scaffold first."]` |

Note: **no partial writes** — either all `files_written` succeed or none
do. Atomic write pattern: write to `<slug>.py.tmp`, fsync, rename.

---

## 8. Integration with existing pipeline

```
Maestro                                                    Kit
  │                                                         │
  │  user: "build me a webhook endpoint with HMAC + dedup"  │
  │                                                         │
  │─────── fastapi_meta_search_home() ─────────────────────►│  landscape
  │◄────── (domains, counts, workflow) ─────────────────────│
  │                                                         │
  │─────── fastapi_meta_search_search("webhook HMAC") ─────►│  BM25
  │◄────── hits: SignatureVerifier, IdempotentConsumer,     │
  │        TamperEvidentAuditLog, recipe:Webhook__01_...    │
  │                                                         │
  │─────── fastapi_meta_search_describe("recipe:...") ─────►│
  │◄────── full recipe + primitive list ────────────────────│
  │                                                         │
  │─────── fastapi_meta_generate_scaffold(output_dir) ─────►│  new project
  │◄────── files_created: [app/main.py, ...] ───────────────│
  │                                                         │
  │─────── fastapi_auth(action='primitive',                 │  copy primitives
  │          name='SignatureVerifier', output_dir=...) ────►│  into app/core/venous/
  │─── (... repeat per primitive, or bundle=True...)  ─────►│
  │                                                         │
  │─────── fastapi_meta_compose(                            │  ◄── THIS TOOL
  │          recipe_id="Webhook__01_...",                   │
  │          output_dir=..., mount_path="/webhooks/in") ───►│  wire them
  │◄────── files_written: [                                 │
  │          app/compositions/webhook_sink.py,              │
  │          app/compositions/test_webhook_sink.py],        │
  │        next_steps: [import install() in main.py, ...]   │
  │                                                         │
  │─────── fastapi_meta_check_audit() ────────────────────►│   verify contract
  │◄────── ok=True ────────────────────────────────────────│
```

### Boundaries with adjacent tools

- **vs `fastapi_meta_generate_scaffold`** — scaffold is project-level
  (emits ~60 files: main, db, auth, docker, CI). Compose is slice-level
  (emits 1-2 files). Compose assumes scaffold already ran; refuses
  otherwise (see §7 "Scaffold not yet run").
- **vs `fastapi_auth`** — `fastapi_auth(action='bundle')` composes 8 auth
  slices via ready-made generator fan-out. `fastapi_meta_compose` is the
  domain-neutral, primitive-level equivalent. Tree dispatcher = scaffold
  for a curated set; compose = surgical for arbitrary sets. These are
  deliberately separate: auth-domain has 15 hand-crafted slice
  generators (`mcp_tools/tree/auth.py:40-57`) whose output quality is
  higher than anything compose can derive from raw primitives.
- **vs `fastapi_meta_search_search`** — search returns NAMES; compose
  consumes names. No overlap. Compose NEVER does NL matching.

---

## 9. Unit-test plan — 14 specific tests

| # | Test name | Assertion | Fixture |
|---|---|---|---|
| 1 | `test_adapter_reuse_exact_match` | `{SignatureVerifier, IdempotentConsumer, AuditEvent}` → `mode="adapter_reuse"`, emitted source calls `WebhookReceiverAdapter.install()` | scaffolded tmpdir + 3 primitives copied |
| 2 | `test_recipe_id_drives_template` | `recipe_id="IdempotentConsumer__01_..."` → emitted source imports the recipe's listed primitives, no others | tmpdir with scaffold + recipe-declared primitives |
| 3 | `test_primitives_fallback_matches_recipe` | list `[A,B,C]` that equals an existing recipe's set → same output as passing that `recipe_id` | — |
| 4 | `test_ad_hoc_fallback_emits_banner` | Two primitives with no recipe → `mode="ad_hoc"`, source contains `# WARNING: no canonical recipe` | two unrelated primitives |
| 5 | `test_unknown_primitive_suggests_fuzzy` | `primitives=["SignatureVerifyr"]` → `ok=False`, `result.suggestions[0]=="SignatureVerifier"` | — |
| 6 | `test_domain_primitive_refused` | `primitives=["Aggregate"]` → `ok=False`, `what_happened` mentions "infra-only" | — |
| 7 | `test_dry_run_writes_nothing` | `dry_run=True` → `files_written=[]`, `composition_source` non-empty, no files on disk | tmpdir |
| 8 | `test_force_overwrite` | Call twice same slug, second with `force=True` → both succeed; without `force` → second returns `ok=False` | tmpdir |
| 9 | `test_ast_parse_valid` | `ast.parse(result["composition_source"])` succeeds for every shipped adapter-reuse combination | — |
| 10 | `test_imports_resolve_on_disk` | `validation_report.imports_resolved=True` when primitives copied; `False` with remediation breadcrumb when not | tmpdir w/ and w/o primitive copy |
| 11 | `test_envelope_shape` | Return value matches tier-1 envelope (`ok`, `what_happened`, `result`, `next_steps ≤5`, `elapsed_ms`) | — |
| 12 | `test_idempotency_fingerprint` | Two identical calls with same inputs produce byte-identical output files; fingerprint short-circuits | tmpdir |
| 13 | `test_mount_path_threads_through` | `mount_path="/hooks"` → emitted source has `@router.post("/hooks")` or equivalent | tmpdir |
| 14 | `test_no_main_py_modification` | Compose never modifies `<output_dir>/app/main.py` (hash before == hash after) | scaffolded tmpdir |

Fixtures live in `tests/common/` (already established — `CLAUDE.md`
mentions the "fixture factory").

---

## 10. Worked example — end-to-end

**Call:**

```python
fastapi_meta_compose(
    output_dir="/tmp/x",
    primitives=["SignatureVerifier", "IdempotentConsumer", "TamperEvidentAuditLog"],
    name="webhook_sink",
    mount_path="/webhooks/in",
)
```

**Kit behavior:**

1. Resolve primitives against `catalog.json`. All three exist. ✅
2. Match against 32 adapters. `WebhookReceiverAdapter` imports exactly
   `{SignatureVerifier, IdempotentConsumer, AuditEvent}`. Set-differ:
   caller asked for `TamperEvidentAuditLog`, not `AuditEvent`. They compose
   (`TamperEvidentAuditLog` wraps `AuditEvent`) — partial match; prefer
   the more specific one. `mode = "adapter_reuse"` but with a `tamper_evident=True` flag threaded to `install()`. (If the flag doesn't exist on the adapter, fall through to `recipe_template`.)
3. Match against 385 recipes. `IdempotentConsumer.md:171-172` declares
   recipe `"Webhook receiver → SignatureVerifier + InboxDeduplicator"` —
   close but swapped `InboxDeduplicator` for `IdempotentConsumer`. Pick
   the closest recipe: `Webhook__01`.
4. Render template → emit file.

**Emitted `app/compositions/webhook_sink.py`:**

```python
"""Webhook sink composition — HMAC verify + exactly-once dedup + tamper-evident audit.

Generated by fastapi_meta_compose (mode=recipe_template, recipe=Webhook__01).
Style-matched to examples/02-webhook-sink/app.py.
"""
from __future__ import annotations

from fastapi import APIRouter, FastAPI, Header, HTTPException, Request

from app.core.venous.security.SignatureVerifier.SignatureVerifier import (
    ALG_HMAC_SHA256, DetachedSigner, TrustAnchor,
)
from app.core.venous.events.IdempotentConsumer.IdempotentConsumer import (
    BaseIdempotentConsumer,
)
from app.core.venous.events.InboxDeduplicator.InboxDeduplicator import (
    InMemoryInboxDeduplicator,
)
from app.core.venous.events.TransactionalOutbox.TransactionalOutbox import (
    InMemoryTransactionalOutbox,
)
from app.core.venous.compliance.TamperEvidentAuditLog.TamperEvidentAuditLog import (
    TamperEvidentAuditLog,
)

_MAX_BODY_BYTES = 1_048_576


class _SinkConsumer(BaseIdempotentConsumer):
    def __init__(self, *, inbox, outbox, audit: TamperEvidentAuditLog) -> None:
        super().__init__(inbox=inbox, outbox=outbox, consumer_name="webhook_sink")
        self.audit = audit

    def _do_handle(self, message, enqueue):
        self.audit.append(
            event_type="webhook.received",
            actor="system",
            payload={"event_id": str(message["id"])},
        )
        return {"ok": True}


def install(
    app: FastAPI,
    *,
    hmac_key: bytes,
    key_id: str = "default",
    mount_path: str = "/webhooks/in",
) -> dict:
    """Wire SignatureVerifier → IdempotentConsumer → TamperEvidentAuditLog onto *app*."""
    anchor = TrustAnchor()
    anchor.register(
        key_id=key_id, algorithm=ALG_HMAC_SHA256,
        public_key=hmac_key, private_key=hmac_key,
    )
    signer = DetachedSigner(anchor, default_msg_type="webhook")
    audit = TamperEvidentAuditLog()
    consumer = _SinkConsumer(
        inbox=InMemoryInboxDeduplicator(),
        outbox=InMemoryTransactionalOutbox(),
        audit=audit,
    )

    router = APIRouter()

    @router.post(mount_path)
    async def _receive(
        request: Request,
        x_signature: str = Header(...),
        x_event_id: str = Header(...),
    ) -> dict:
        body = await request.body()
        if len(body) > _MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="payload too large")
        try:
            signer.verify_typed(
                body, bytes.fromhex(x_signature), key_id, msg_type="webhook",
            )
        except Exception as exc:  # noqa: BLE001 — SignatureVerifier is the boundary
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        before = consumer.handle_calls
        consumer.handle({"id": x_event_id, "body": body})
        return {
            "received": True,
            "duplicate": consumer.duplicate_calls > 0
                         and consumer.handle_calls == before + 1,
        }

    app.include_router(router)
    app.state.webhook_sink = {"signer": signer, "consumer": consumer, "audit": audit}
    return app.state.webhook_sink
```

The emitted code mirrors `WebhookReceiverAdapter.py` (lines 38-60) verbatim
in style. A `test_webhook_sink.py` is also emitted — a 20-line pytest
fixture that boots `TestClient`, POSTs a signed body, asserts 200, POSTs
the same body again, asserts the response `{"duplicate": True}`.

The `next_steps` returned:

```
[
  "In app/main.py: from app.compositions.webhook_sink import install; install(app, hmac_key=os.environ['WEBHOOK_SECRET'].encode())",
  "Run the emitted test_webhook_sink.py: pytest app/compositions/test_webhook_sink.py",
  "Call fastapi_meta_check_audit() to verify contract drift.",
]
```

---

## 11. Open questions

1. **Who owns the template catalog — Opus or a builder?** Templates need
   authoring discipline (one per recipe). Option A: Opus hand-authors top-30
   now; builder agent auto-generates the rest under Opus audit. Option B:
   ship only the 30 and accept `ad_hoc` for the long tail indefinitely.
   Decision needed: timeline for filling tail + whose budget pays.

2. **Adapter-reuse vs. copy-adapter-into-project.** Today's adapters live
   under `core/venous/_adapters/fastapi/` in the SKILL repo. When compose
   detects an adapter match, does it (a) emit a 3-line file calling into
   the shipped adapter (but then the adapter must be copied to the target
   project), or (b) inline the adapter body into `app/compositions/<slug>.py`
   (self-contained file; no cross-directory coupling)? Recommendation: (b),
   because the ADR 0002 "copy-in distribution" principle already governs
   primitives.

3. **Does `compose` copy primitives, or assume they're already copied?**
   Today, `fastapi_auth(action='primitive', name=X)` copies. Compose could
   (a) assume prior copy calls and refuse if missing, or (b) auto-copy any
   missing primitives. Recommendation: (a) — keeps responsibilities clear;
   the error message in §7 points Maestro at the copy step. Alternative
   (b) is one-shot-friendly but hides a write in what should be pure
   composition.

4. **Composition id collision across reruns.** If Maestro calls compose
   twice with the same `primitives` but different `mount_path`, do we
   overwrite, emit two files, or refuse? Recommendation: require explicit
   `name=` when two compositions share primitives; default slug is a
   deterministic hash of `(recipe_id, sorted(primitives))` — so identical
   inputs collide (idempotent). Different `mount_path` alone is not enough
   to differentiate — the file system is the wrong layer to encode runtime
   config.

5. **Should compose ever edit `app/main.py`?** Design says no; tempting to
   say yes for UX. If we reverse, need a format-preserving Python editor
   (libcst). Recommendation: defer until telemetry shows Maestro fails to
   follow the `next_steps` wire-up breadcrumb >30% of the time. Not now.

---

## Sources

- `/Users/gustavoschneiter/Documents/HuGR/HuGR_Skills/skills/SKILL-001-fastapi-production/core/venous/_adapters/fastapi/WebhookReceiverAdapter.py` — canonical composition idiom, `install()` signature at line 38; the emitted code style guide.
- `/Users/gustavoschneiter/Documents/HuGR/HuGR_Skills/skills/SKILL-001-fastapi-production/mcp_tools/tier1.py` — envelope contract (lines 43-52), workflow breadcrumbs (lines 111-117).
- `/Users/gustavoschneiter/Documents/HuGR/HuGR_Skills/skills/SKILL-001-fastapi-production/mcp_tools/tree/auth.py` — tree-dispatcher precedent (lines 173-201); bundle-vs-slice-vs-primitive granularity model.
- `/Users/gustavoschneiter/Documents/HuGR/HuGR_Skills/skills/SKILL-001-fastapi-production/engine/index/catalog.json` — 295 tools, 122 primitives, 385 recipes; recipe schema at lines 5262-5339.
- `/Users/gustavoschneiter/Documents/HuGR/HuGR_Skills/skills/SKILL-001-fastapi-production/engine/index/schemas.py:92-100` — `RecipeEntry` pydantic contract.
- `/Users/gustavoschneiter/Documents/HuGR/HuGR_Skills/skills/SKILL-001-fastapi-production/core/venous/events/IdempotentConsumer/IdempotentConsumer.md:169-181` — canonical `## Compose with:` bullet format.
- `/Users/gustavoschneiter/Documents/HuGR/HuGR_Skills/examples/02-webhook-sink/app.py` — the style guide for emitted compositions.
- `/Users/gustavoschneiter/Documents/HuGR/HuGR_Skills/docs/research/TOOL_UX_PRODUCTION.md` §2 (patterns: ToolSpec bundles, Rails scaffold, retrieval-over-registry).
- `/Users/gustavoschneiter/Documents/HuGR/HuGR_Skills/docs/research/DUAL_INDEX_DESIGN.md` — overall tier-1/tier-2 architecture.
- [FastAPI bigger applications](https://fastapi.tiangolo.com/tutorial/bigger-applications/) — `APIRouter` + `include_router` as the composition idiom.
- [FastAPI dependencies](https://fastapi.tiangolo.com/tutorial/dependencies/) — `Annotated[T, Depends(...)]` as the sub-dependency pattern.
- [Rails Guides — Command Line](https://guides.rubyonrails.org/command_line.html#rails-generate) — scaffold-as-meta-generator precedent.
- [Yeoman composability](https://yeoman.io/authoring/composability.html) — sub-generator `composeWith` pattern.
- [LlamaIndex Tools](https://docs.llamaindex.ai/en/stable/module_guides/deploying/agents/tools/) — ToolSpec bundles = composition tier, separate from retrieval (ObjectIndex).
- [Anthropic "Writing effective tools for AI agents" (Oct 2025)](https://www.anthropic.com/engineering/writing-tools-for-agents) — orthogonality principle ("tools should do one thing"); name ≤ 1024 chars; return value should support inspection.
- [Semantic Kernel plugins](https://learn.microsoft.com/en-us/semantic-kernel/concepts/plugins/) — `KernelFunction` composition model; planners deprecated in favor of native function calling.
- [SWE-agent ACI (arxiv:2405.15793)](https://arxiv.org/abs/2405.15793) — "lint-on-edit, not compile-on-edit"; fast feedback before semantic checks.
- [Cookiecutter Hooks](https://cookiecutter.readthedocs.io/en/stable/advanced/hooks.html) — pre_gen / post_gen as precedent for `dry_run` + validation gates.
