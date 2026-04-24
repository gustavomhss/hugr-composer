# not-yet-covered.md — honest evidence gaps at v1.0.0

> Listed here: every PRODUCT.md claim the evidence package does NOT prove at the v1.0.0 tag cut, with an honest reason + milestone that would enable evidence.
>
> If a claim is material to the product but lives only in this file, it is a **stated caveat**, not proof. Codex v6 LAUNCH review B2 correctly flagged that hiding gaps behind confident language is the primary failure mode. They live here explicitly instead.

---

## §1 — MCP server against Claude Desktop / Cursor / Zed

**PRODUCT §3 secondary claim.** The skill exposes an MCP server (`mcp_tools/`) intended to be discoverable + invocable by any MCP-compatible client. We have:

- `mcp_tools/server.py` that boots and serves the Tier-1 + Tier-2 surface.
- `mcp_tools/auto_discovery.py` that enumerates tools for the client.
- `examples/claude_code.mcp.json` as a registration shape.

What we do NOT have at v1.0.0:

- Automated end-to-end test against Claude Desktop, Cursor, or Zed as live clients. Integration is manually verified only.

**Milestone to close:** v1.1+ — build a harness that launches each client headlessly, installs the kit, and asserts tool-discovery + one successful invocation.

---

## §2 — Generated code survives hand-editing (longitudinal soak)

**PRODUCT §6.3 claim.** Emit-time idempotency IS covered: the `_r_generator_*` contract rules assert that re-running the same generator on an already-scaffolded project produces a no-op diff, and that marker-delimited blocks are edit-safe. What this proves: at t=0, the emitted code is structured so hand edits can coexist with subsequent tool applications.

What this does NOT prove:

- **Longitudinal soak:** "apply tool → hand-edit → apply tool → hand-edit → apply tool" over N cycles, across many projects and edit styles, without divergence.

**Milestone to close:** v1.1+ — soak-edit harness that randomly perturbs emitted code between tool applications and checks the generators continue to produce no-op diffs on the non-perturbed regions.

---

## §3 — "Cheaper than hand-coded" as an absolute claim

**PRODUCT §1 + §4 implicit economic claim.** We evidence a relative form:

- `counterfactual/` compares same-model same-spec WITH-HuGR vs WITHOUT-HuGR: token cost, time-to-first-boot, LOC, and grade.

That establishes HuGR-assisted is cheaper than same-model raw generation for the 10 FNF specs at the benchmark HEAD. It does NOT establish:

- "Cheaper for real teams with real feature specs at production scale" as an absolute. That requires population-scale telemetry (real users, real specs, real PR merge cycles).

**Milestone to close:** v1.2+ — opt-in telemetry from Phase B cohort (install-completion + first-scaffold-boot + extend-tool-activation rates) surfaces the real-team ratio. Until then this is a research-benchmark claim, not a billing-slide claim.

---

## §4 — "SOTA for FastAPI scaffold generation" as a cross-framework claim

**PRODUCT §1 framing.** v1.0.0 ships a SINGLE skill: `SKILL-001-fastapi-production`. Benchmark scores + counterfactual runs are all within FastAPI. Any claim of "SOTA backend generation" must scope to FastAPI at v1.0.0.

**Milestone to close:** v1.2+ (Rust / Go / Django skills). At that point the benchmark corpus broadens and cross-framework comparisons become testable.

---

## §5 — Production hardening evidence beyond static scan

**PRODUCT §4 "production-grade" framing.** Deterministic artefacts cover:

- Static security (bandit + semgrep, 0 HIGH / 0 CRITICAL across 20 examples).
- Boot + emitted-pytest green in the `install_docker_run.log`.
- Full kit pytest sweep green (5387/0/8).

What we do NOT have at v1.0.0:

- Penetration testing of emitted scaffolds against OWASP Top-10 payloads by an external pentest vendor.
- Load testing of emitted scaffolds beyond the 5-min soak test against the kit itself.
- Long-running prod deployments from real users (by definition, pre-launch).

**Milestone to close:** Phase B (POST_RELEASE.md telemetry) + external pentest commission between Phase B exit and Phase C prerequisites. The `install-docker.yml` nightly-green streak ≥30 days is a proxy for operational stability but is not a substitute for a pentest.

---

## §6 — Governance + bus-factor

LAUNCH.md §3.3 makes the bus-factor-1 risk explicit: Phase C is blocked on a NAMED HUMAN backup on-call with commit access + release secrets + yank authority. At Wave-H this human is not yet named. This is not an evidence gap of the TECHNICAL product — it is a launch-readiness gap tracked in LAUNCH.md §1.4 + §3.3.

**Milestone to close:** before Phase C opens. Before the v1.0.0 tag cut, the gap is acknowledged (LAUNCH.md §3.3 + POST_RELEASE.md); before PUBLIC launch, the gap is closed.

---

*This file is part of the v1.0.0 evidence package. Every row cites the milestone that would move it out of this file into `EVIDENCE.md` proper. Closing a row is a LAUNCH.md §6 amendment (ratification block + Gustavo signature).*
