# Contributing to HuGR Arsenal

> **Scope:** this guide teaches a first-time contributor how to land a
> primitive, a tool, or a composition recipe without maintainer
> intervention. Target: **time-to-first-PR < 1 hour.**
>
> Every PR is judged against `CONTRACT.md` §C (Phase, §A compliance,
> DoD, Invariants, Completeness, Quality). No exceptions.

---

## 1. Local dev setup (5 min)

```bash
git clone https://github.com/humangr-labs/HuGR-Arsenal.git
cd HuGR_Arsenal/skills/SKILL-001-fastapi-production

python3.12 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements-mcp.txt
.venv/bin/pip install pytest pytest-asyncio aiosqlite httpx

# Verify the kit is healthy — 37/37 rules must pass before any PR.
PYTHONPATH=. .venv/bin/python -m engine.audit.contract_check
```

Expected output ends with `37/37 contract items satisfied — ALL GREEN`.
If not, stop and open an issue; do not land new work on a red tree.

---

## 2. Anatomy of a contribution

Three surfaces. Pick **exactly one** per PR.

| Surface      | What it is                                          | Where it lives                                        |
| ------------ | --------------------------------------------------- | ----------------------------------------------------- |
| Primitive    | Framework-agnostic Lego block (Protocol + impl)     | `core/venous/<concern>/<Name>/`                       |
| Tool         | MCP-registered code generator or adapt operation    | `adapt/extend/` or `generators/`                      |
| Recipe       | Composition of ≥2 primitives documented in `.md`    | `core/venous/<concern>/<Name>/<Name>.md`              |

---

## 3. Adding a primitive

A primitive passes the **10-tier gate** before it ships. The rules are
machine-enforced via `engine/audit/contract_check.py` + the primitive's
`.contract.json`.

### 3.1 File layout (mandatory)

```
core/venous/<concern>/<Name>/
├── <Name>.py               # reference implementation (framework-free)
├── <Name>.protocol.py      # Protocol — the typed interface
├── <Name>.md               # docs + invariants + Compose with: section
├── <Name>.contract.json    # machine-readable contract (name, invariants, T-gates)
├── test_<Name>.py          # ≥ 1 test per invariant
├── __init__.py             # exports the Protocol + impl
└── _provenance.json        # OSS origin (if adapted) — URL + license
```

### 3.2 The 10-tier gate

| Tier | Name                   | What it checks                                        |
| ---- | ---------------------- | ----------------------------------------------------- |
| T0   | Compile                | `python -m py_compile` clean                          |
| T1   | Types                  | Protocol matches impl; no `Any` leaks                 |
| T2   | Unit                   | Every invariant has ≥1 direct test                    |
| T3   | Framework-free         | No `fastapi` / `sqlalchemy` imports in primitive      |
| T4   | Metamorphic            | Property tests: swap input → output invariants hold   |
| T5   | Concurrency            | asyncio stress ≥ 100 concurrent callers               |
| T6   | Idempotency            | Same input twice → same state (where applicable)      |
| T7   | Observability          | Emits metric names present in `observability_schema`  |
| T8   | Recovery               | Failure injection: restart / crash → still converges  |
| T9   | Provenance             | `_provenance.json` cites OSS source + license         |

### 3.3 Invariants are load-bearing

Every primitive declares invariants in its `.contract.json`:

```json
{
  "name": "SessionCache",
  "namespace": "cache",
  "invariants": [
    {"id": "SC_INV_01", "statement": "get() after put() returns the same value within TTL"},
    {"id": "SC_INV_02", "statement": "get() after expiry returns None (sentinel)"}
  ],
  "compose_with": ["RedisAdapter", "IdempotentConsumer"]
}
```

Each `*_INV_*` must have at least one test in `test_<Name>.py` whose name
references it (e.g. `test_inv_01_get_within_ttl`).

### 3.4 Register the primitive

```bash
# Edit engine/primitives_by_concern.yaml — add the entry
# Run the registry sync check
PYTHONPATH=. .venv/bin/python -m engine.audit.contract_check --item B1.1
# Must report: "registry synced: N entries match disk"
```

### 3.5 PR checklist

- [ ] 10-tier gate green (`pytest` on the primitive dir)
- [ ] `B1.1` (registry sync) + `B1.2` (Compose-with) green
- [ ] `_provenance.json` cites OSS origin if adapted (or `"origin": "native"`)
- [ ] One-line entry in `CHANGELOG.md` under `## [Unreleased]`

---

## 4. Adding a tool

A tool is an MCP-registered operation. The shape is enforced by
`tests/contracts/delivery_contract.py` (Pydantic).

### 4.1 File layout

```
adapt/extend/<category>/add_<feature>.py            # the tool
adapt/extend/<category>/test_add_<feature>.py       # unit tests
adapt/extend/<category>/test_add_<feature>_behavior.py   # behavior scenario
specs/TOOL-NNN-add_<feature>.md                     # formal 16-section spec
```

### 4.2 Mandatory patterns (from `tests/contracts/AGENT_BRIEFING_TEMPLATE.md`)

```python
MCP_TOOL = {
    "name": "fastapi_add_<feature>",
    "description": "<one-paragraph what + when>",
    "input_schema": {...},
}

async def add_<feature>(...) -> ToolResult:
    t0 = time.perf_counter()
    ensure_prerequisites(...)              # CC-01
    if fingerprint_match(...): return no_op(elapsed_ms=...)   # CC-02 idempotency
    if dry_run: return dry_run_result(elapsed_ms=...)         # CC-03
    ...
    ast.parse(generated_source)            # CC-17 validation loop
    return ToolResult(ok=True, elapsed_ms=ms(t0), files_created=[...])
```

Anti-patterns that will get your PR rejected (see the briefing template
for the full list of 9):

- No `elapsed_ms` on a return path.
- Eager import of an optional SDK (use lazy imports inside the function).
- `@mcp_app.tool` decorator on the function (auto-discovery only).
- Generator emits code that does **not** import from `core.venous.*` when
  a matching primitive exists.

### 4.3 Wire into test infrastructure

```bash
# Boot test picks up the tool automatically; just run it:
PYTHONPATH=. .venv/bin/python tests/test_boot.py

# Property tests (8 properties × every tool):
PYTHONPATH=. .venv/bin/python tests/property_tests.py
```

### 4.4 PR checklist

- [ ] Tool passes all 8 property tests
- [ ] Behavior test covers ≥1 domain scenario end-to-end
- [ ] `B1.3` (tools import primitives) still green if applicable
- [ ] `B1.5` (no manual decorators) + `B1.6` (no orphan generators) green
- [ ] `CHANGELOG.md` `## [Unreleased]` entry

---

## 5. Adding a composition recipe

A recipe lives inside a primitive's `.md` under the **`## Compose with:`**
section. Every production primitive has one (enforced by `B1.2`).

### 5.1 Shape

```markdown
## Compose with:

- `SignatureVerifier` + `IdempotentConsumer` → **webhook receiver with
  single-delivery guarantee + tamper-evident audit trail**. Pair when
  the upstream retries on timeout.

- `RateLimiter` + `Bulkhead` → **DoS-resistant public endpoint**. Use
  when the caller population is untrusted.
```

Each bullet must name **≥2 sibling primitives by exact registry name**,
describe the emergent capability, and state when to reach for it.

### 5.2 Quality bar

A recipe is useful only if `suggest_composition` can retrieve it for a
realistic query. Verify:

```bash
PYTHONPATH=. .venv/bin/python engine/discovery/compose_bench.py
# top-1 accuracy must stay ≥ 70%, P@3 ≥ 90%
```

### 5.3 PR checklist

- [ ] Recipe references ≥2 existing primitives (names match registry)
- [ ] `B2.2` suggest_composition quality gate still green
- [ ] One-line `CHANGELOG.md` entry under `## [Unreleased]`

---

## 6. Before you open the PR

Run the full local gate:

```bash
cd skills/SKILL-001-fastapi-production
./ci.sh --no-pg                # ~5 min; all suites must pass
PYTHONPATH=. .venv/bin/python -m engine.audit.contract_check
# 37/37 ALL GREEN
```

Then in the PR description, cite CONTRACT.md's six fields:

```
Phase:        <e.g. 5 — gap-driven>
§A compliance: <which §A rules this work respects; any exceptions>
DoD:          <the specific contract item DoD bullet you satisfied>
Invariants:   <which invariants added / changed / tested>
Completeness: <what's in scope; what's explicitly not>
Quality:      <SOTA bar met — tests, observability, docs>
```

---

## 7. What gets rejected (fast)

- Work on a red tree (any contract item failing).
- Primitives with framework imports (`fastapi`, `sqlalchemy`, etc.).
- Tools without `elapsed_ms` on every return path.
- Generators that emit code duplicating a primitive instead of importing it.
- PRs mixing two surfaces (split a tool + primitive PR into two).
- "Aspirational" docs — numbers must match `contract_check`'s live count.

---

## 8. Getting help

- **Design question:** open a GitHub Discussion, tag `design`.
- **Bug:** open an issue with the failing `contract_check` item name.
- **Security:** email gustavo@humangr.com directly.

---

Signed: HuGR maintainers.
