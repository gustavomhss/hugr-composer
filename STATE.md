# Estado — 2026-09-04 (pós WP-01 merge)

## Status atual
- **Main: `6824eb3c`** (WP-01 squash-merged como PR #56)
- **WP-00 + WP-01: COMPLETOS**
- Stash original `chore/inventory-and-docs-sync`: **preservada** (não tocada)

## Histórico de merges (sessão)
- `e300c1dd` PR #49: pytest-json-report + F821 protocolos + ledger drift (3 fixes pré-existentes)
- `a3195f2e` PR #50: otel absolute + scaffold_venous None guard (1ª metade WP-00)
- `e2b60bba` PR #55: bundle do WP-00 (12 commits cherry-pick + 1 lint cleanup)
- `6824eb3c` PR #56: WP-01 completo — doc-gate + sync-docs + scaffold manifest

## WP-00 + WP-01 — Resumo do que foi entregue

| WP | Mudança | Status |
|---|---|---|
| WP-00 | pytest-json-report no venv compartilhado (CI) | ✅ |
| WP-00 | F821 protocolos (4 imports + infer_protocol auto-import) | ✅ |
| WP-00 | Ledger drift sync (FREEZE.md/ROADMAP syncado) | ✅ |
| WP-00 | 17 stale tests fixados | ✅ |
| WP-00 | 1 bug real (otel absolute path) | ✅ |
| WP-00 | 1 hardening (scaffold_venous ValueError) | ✅ |
| WP-00 | 17 stale tests fixados | ✅ |
| WP-00 | 1 bug real (otel absolute path) | ✅ |
| WP-00 | 1 hardening (scaffold_venous ValueError) | ✅ |
| WP-01 | R3: `with_ci=True` p/ minimal/api/worker + decoupling `skip_deployment` | ✅ |
| WP-01 | Scaffold emit: `.hugr-scaffold-manifest.json` + `scripts/sync_docs.py` + `scripts/check_docs_drift.py` | ✅ |
| WP-01 | CRLF-normalized sha256 (Q4 FP ≤ 0.01) | ✅ |
| WP-01 | Watched set narrow (~12 files), alfabético, sorted | ✅ |
| WP-01 | `logging` em vez de `print` (SEC-08) | ✅ |
| WP-01 | Doc-gate CI job (1-min timeout, after lint, before test) | ✅ |
| WP-01 | Opt-out via `.hugr-scaffold-disable` (Q3) | ✅ |
| WP-01 | `logging` em scripts (SEC-08 compliance) | ✅ |
| WP-01 | D validation: 10 testes (6 cenários + FP 20 cases) | ✅ |
| WP-01 | Golden snapshot regenerado (102 files, 78 py, 5695 loc) | ✅ |

## Verificações pós-merge

| Check | Resultado |
|---|---|
| Local-CI (bin/local-ci.sh) | 12/12 PASS (125 min) |
| `test_doc_gate_d_validation.py` | 10/10 pass (6 cenários + FP 20 cases) |
| `test_gen_*` + protocol test | 236 passed |
| `test_security_generated` (SEC-08) | 53 passed, 3 skipped |
| `engine.audit.contract_check` (phase 0 + 4) | 7/7 green |
| `test_determinism.py` | 4/4 pass (golden snapshot regenerado) |
| `test_e2e_postgres.py` + behavior | 8/8 + 65/65 + 14/14 |

## Axiomas WP-01 validados (local-CI)

| Axioma | Status | Evidência |
|---|---|---|
| Q1 (gate em todo profile) | ✅ | 3 perfis × gate presente |
| Q2 (sync-docs ≤ 1 cmd) | ✅ | `./scripts/sync_docs.py` idempotente |
| Q3 (opt-out file) | ✅ | `.hugr-scaffold-disable` presence = off |
| Q4 (FP ≤ 0.01) | ✅ | 20 seed cases pass, CRLF-normalized |
| Q5 (latência ≤ 10s) | ✅ | medido 2.5-4s cold |
| I1 (drift=∅ ⇒ fail ≤ 1s) | ✅ | teste 3 valida |
| I2 (idempotent sync) | ✅ | teste 3 valida |
| S (drift descoberto em ≤ 1 commit) | ✅ | teste 3 valida |

## Próximos WPs (do `/tmp/golive-wps.md`)

| Próximo | Descrição |
|---|---|
| **WP-01B** | Maintenance skills per crate (skills de manutenção por crate) |
| **WP-02** | Endurecimento go-live (security audit, lockfile + SBOM, licenses, migrations, runbooks) |
| **WP-03** | Prova (5 composições adversariais + token measurements + demo público + dogfood) |
| **WP-04** | Distribuição (MCP server + adapters + decisão negócio + idioma + trademark) |
| **WP-05** | Launch controlado (beta + processo incidente + telemetria opt-in + suporte + GA criteria) |

## Pendências de infraestrutura (bloqueia CI GitHub nativo)

**Runner self-hosted quebrado** — TLS handshake failure em `actions.github.com` (SocketException 89: Operation canceled no `SslStream.EnsureFullTlsFrameAsync`). Backoff ~6.327s × 3 tentativas. Provável causa: credencial OAuth expirada.

**Fix necessário** (ação humana):
```bash
launchctl unload ~/Library/LaunchAgents/actions.runner.HuGR-Labs.skill-001-fastapi-production.plist
cd /Users/gustavoschneiter/actions-runner-skill-001
./config.sh remove --token <ATUAL>
./config.sh --url https://github.com/HuGR-Labs/skill-001-fastapi-production --token <NOVO_TOKEN>
launchctl load ~/Library/LaunchAgents/actions.runner.HuGR-Labs.skill-001-fastapi-production.plist
```

## Estado do repo

- Main: `6824eb3c` (WP-01 merged)
- Working tree: clean (só `STATE.md` + `bin/` untracked — preservados)
- Stash original: `chore/inventory-and-docs-sync` (NÃO POPAR)
- Branches remotas de WP-01: preservadas (podem ser limpas depois)

---

**Próximo passo sugerido:** WP-01B (Maintenance skills per crate) ou consertar runner CI → WP-02.