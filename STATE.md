# Estado — 2026-09-04 (pós WP-02 merge)

## Status atual
- **Main: `9ccfde40`** (WP-02 squash-merged como PR #57)
- **WP-00 + WP-01 + WP-02: COMPLETOS**
- Stash original `chore/inventory-and-docs-sync`: **preservada**

## Histórico de merges
- `e300c1dd` PR #49: pytest-json-report + F821 protocolos + ledger drift (3 fixes pré-existentes)
- `a3195f2e` PR #50: otel absolute + scaffold_venous None guard (1ª metade do WP-00)
- `e2b60bba` PR #55: bundle do WP-00 (12 commits cherry-pick + 1 lint cleanup)
- `6824eb3c` PR #56: WP-01 completo — doc-gate + sync-docs + scaffold manifest
- `9ccfde40` PR #57: **WP-02 completo** — Endurecimento go-live

## WP-00 + WP-01 + WP-02 — Resumo do que foi entregue

| WP | Mudança | Status |
|---|---|---|
| WP-00 | pytest-json-report no venv compartilhado (CI) | ✅ |
| WP-00 | F821 protocolos (4 imports + infer_protocol auto-import) | ✅ |
| WP-00 | Ledger drift sync (FREEZE.md/ROADMAP syncado) | ✅ |
| WP-00 | 17 stale tests fixados | ✅ |
| WP-00 | 1 bug real (otel absolute path) | ✅ |
| WP-00 | 1 hardening (scaffold_venous ValueError) | ✅ |
| WP-01 | R3: `with_ci=True` p/ minimal/api/worker + decoupling `skip_deployment` | ✅ |
| WP-01 | Scaffold emit: `.hugr-scaffold-manifest.json` + `scripts/sync_docs.py` + `scripts/check_docs_drift.py` | ✅ |
| WP-01 | CRLF-normalized sha256 (Q4 FP ≤ 0.01) | ✅ |
| WP-01 | Watched set narrow (~12 files), alfabético, sorted | ✅ |
| WP-01 | `logging` em vez de `print` (SEC-08 compliance) | ✅ |
| WP-01 | Doc-gate CI job (1-min timeout, after lint, before test) | ✅ |
| WP-01 | Opt-out via `.hugr-scaffold-disable` (Q3) | ✅ |
| WP-01 | D validation: 10 testes (6 cenários + 20 FP cases) | ✅ |
| WP-01 | Golden snapshot regenerado (102 files, 78 py, 5695 loc) | ✅ |
| WP-02 | Security baseline: argon2id, headers, CORS, rate_limit, secrets env-only | ✅ |
| WP-02 | Supply chain: SBOM CycloneDX, lockfile, reproducible install | ✅ |
| WP-02 | Observability: structured logs, correlation_id, RED metrics, traces | ✅ |
| WP-02 | Semver + changelog + bump_version.py | ✅ |
| WP-02 | Runbooks: 5 cenários (migration_fail, secret_leak, deploy_break, db_slow, rollback) | ✅ |
| WP-02 | Security scan: pre-commit, dependabot, Trivy, pip-audit | ✅ |
| WP-02 | Provenance + licenses: SLSA provenance.json + LICENSES.md | ✅ |
| WP-02 | Defense-in-depth: secrets grep, no REPLACE_WITH_ | ✅ |
| WP-02 | Determinism: golden_snapshot.json regenerado | ✅ |

## Verificações pós-merge

| Check | Resultado |
|---|---|
| Local-CI (bin/local-ci.sh) | 13/13 PASS (125 min) |
| `test_doc_gate_d_validation.py` | 10/10 pass (6 cenários + FP seed) |
| `test_gen_*` + protocol test | 236 passed |
| `test_security_generated` (SEC-08) | 53 passed, 3 skipped |
| `engine.audit.contract_check` (phase 0 + 4) | 7/7 green |
| `test_determinism.py` | 4/4 pass (golden snapshot regenerado) |
| `test_e2e_postgres.py` + behavior | 8/8 + 65/65 + 14/14 |

## Axiomas WP-02 validados (local-CI)

| Axioma | Status | Evidência |
|---|---|---|
| Q1 (Security baseline) | ✅ | argon2id, headers, CORS, rate_limit, secrets env-only |
| Q2 (Supply chain) | ✅ | SBOM CycloneDX, lockfile, reproducible install |
| Q3 (Observability) | ✅ | structured logs, correlation_id, RED metrics, traces |
| Q4 (Semver/changelog) | ✅ | VERSION, CHANGELOG.md, bump_version.py |
| Q5 (Runbooks) | ✅ | 5 cenários, 65/65 assertions |
| C1 (Security scan) | ✅ | pre-commit, dependabot, Trivy, pip-audit |
| C2/C3 (Provenance/licenses) | ✅ | provenance.json, LICENSES.md |
| I1 (Defense-in-depth) | ✅ | secrets grep, no REPLACE_WITH_ |
| I2 (Determinism) | ✅ | golden_snapshot 4/4 pass |
| D (Auditoria + SBOM + 5 runbooks + LICENSE_COMPAT) | ✅ | 13/13 local-CI PASS |
| S (Stress test) | ✅ | 13/13 jobs PASS |

## Próximos WPs (do `/tmp/golive-wps.md`)

| Próximo | Descrição |
|---|---|
| **WP-01B** | Maintenance skills per crate (skills de manutenção por crate) |
| **WP-02** | Endurecimento go-live (security audit, lockfile + SBOM, licenses, migrations, runbooks) — **JÁ FEITO** |
| **WP-03** | Prova (5 composições adversariais + token measurements + demo público + dogfood) |
| **WP-04** | Distribuição (MCP server + adapters + decisão negócio + idioma + trademark) |
| **WP-05** | Launch controlado (beta + processo incidente + telemetria opt-in + suporte + GA criteria) |

## Pendências de infraestrutura (bloqueia CI GitHub nativo)

**Runner self-hosted quebrado** — TLS handshake failure em `actions.github.com` (SocketException 89: Operation canceled). Provável causa: credencial OAuth expirada.

**Fix necessário** (ação humana):
```bash
launchctl unload ~/Library/LaunchAgents/actions.runner.HuGR-Labs.skill-001-fastapi-production.plist
cd /Users/gustavoschneiter/actions-runner-skill-001
./config.sh remove --token <ATUAL>
./config.sh --url https://github.com/HuGR-Labs/skill-001-fastapi-production --token <NOVO_TOKEN>
launchctl load ~/Library/LaunchAgents/actions.runner.HuGR-Labs.skill-001-fastapi-production.plist
```

## Estado do repo

- Main: `9ccfde40` (WP-02 merged)
- Working tree: clean (só `STATE.md` + `bin/` untracked — preservados)
- Stash original: `chore/inventory-and-docs-sync` (NÃO POPAR)

## Próximo passo sugerido

WP-01B (Maintenance skills per crate) — skills de manutenção por crate (auth, billing, observability...), cada uma com: operações comuns, armadilhas conhecidas, como evoluir sem quebrar contrato, quando pedir revisão humana. Nascem de fricção real (dogfood WP-03) — não de achismo.