# Security Tools Specification

> 15 production-grade security tools that make AppSec engineers and CISOs
> say "this comes BUILT-IN?"
> Researched against OWASP API Top 10 2023, PCI DSS 4.0, HIPAA, SOC2,
> and what Stripe/Cloudflare/GitHub built internally.

---

## Rank 1: add_request_signing

**Attack prevented:** Request tampering, replay, MITM body modification.

HMAC request signing (Stripe/AWS Sig V4 pattern). Canonical string construction
(method + path + sorted query + selected headers + SHA-256 body hash),
HMAC-SHA256, timestamp window (5 min default), nonce-based replay prevention.
Includes idempotency key support.

**Who built this internally:** Stripe, AWS (Sig V4), Twilio.

---

## Rank 2: add_dlp_shield

**Attack prevented:** Data exfiltration, accidental PII leakage, OWASP API3:2023.

Response middleware scanning outgoing JSON for PII/PHI/PCI. Two-tier:
decorator-based explicit (`@sensitive(level="pci")`) + regex/pattern detection
(Luhn, SSN, email, IBAN). Redaction modes: full mask, partial (last 4),
tokenization, field removal. Per-role visibility.

**Who built this internally:** Cloudflare (AI Gateway DLP), Stripe (PCI field-level).

---

## Rank 3: add_canary_tokens

**Attack prevented:** Credential theft, insider threats, lateral movement. Detects breaches in minutes vs 204-day industry average.

Three types: (1) Honeypot endpoints (`/api/v1/internal/config`) that alert on
access, (2) Fake credentials (AWS keys, DB strings) that trigger when used,
(3) Decoy DB records (fake admin users) that fire when queried. Each canary
has unique fingerprint for attribution.

**Who built this internally:** Grafana Labs (detected April 2025 breach in minutes via canary AWS key), Thinkst Canary.

---

## Rank 4: add_sbom_guardian

**Attack prevented:** Supply chain attacks, dependency confusion, typosquatting. 28.6M secrets leaked in 2025 (GitGuardian).

Four layers: CycloneDX SBOM generation with crypto signing, lockfile integrity
verification, dependency confusion detection (internal vs PyPI namespace),
known vulnerability scanning (OSV/NVD). PCI DSS 4.0 Req 6.3 compliant.

**Who built this internally:** Google (SLSA), Microsoft (SBOM mandate since 2022).

---

## Rank 5: add_runtime_sentinel

**Attack prevented:** SQL/command/SSRF injection at RUNTIME with full app context (beyond WAF).

AST-aware middleware. SQL injection: parses query structure, detects tautology/UNION/stacked/comment injection. SSRF: allow-list of outbound hosts, blocks internal networks + cloud metadata. Command injection: detects shell metacharacters reaching subprocess. Learning mode profiles normal behavior 24-48h, then alerts on deviations.

**Who built this internally:** Imperva (RASP), Sqreen (acquired by Datadog), Contrast Security.

---

## Rank 6: add_compliance_evidence

**Attack prevented:** Audit log tampering, failed audits, regulatory fines.

Append-only, cryptographically chained audit events (each hash includes
previous hash = tamper-evident). Auto-maps to compliance control IDs
(SOC2 CC6.1, HIPAA 164.312, PCI DSS 10.2.x). Generates auditor-ready
evidence packages. Retention enforcement (7yr PCI, 6yr HIPAA).

**Who built this internally:** Stripe, every SOC2 Type II / PCI Level 1 company.

---

## Rank 7: add_adaptive_throttle

**Attack prevented:** DDoS, credential stuffing, scraping, OWASP API4/API6.

Beyond static rate limiting: (1) Cost-based — expensive endpoints consume
more quota, (2) Behavioral fingerprinting — TLS fingerprint + header order +
timing patterns detect IP rotation, (3) Adaptive thresholds — learns normal
per-tenant patterns, tightens on anomaly, (4) Cascading penalties — repeated
violations = exponential cooldown (1min→5min→30min→24hr).

**Who built this internally:** Cloudflare, Akamai, GitHub.

---

## Rank 8: add_security_headers_advanced

**Attack prevented:** XSS, clickjacking, protocol downgrade, MIME sniffing.

CSP policy BUILDER that analyzes actual resource loading and generates tightest
possible policy. HSTS with includeSubDomains + preload. Permissions-Policy
denying camera/mic/geo/payment. Server header removal. Self-test scanner
validating against SecurityHeaders.com criteria, CI fails below A+.

**Who built this internally:** Mozilla (created Observatory because even their own properties had inconsistent headers).

---

## Rank 9: add_secret_rotation

**Attack prevented:** Credential compromise, secrets in code, stale API keys.

Provider abstraction (Vault/AWS SM/Infisical/Azure KV/env). Auto-rotation with
zero-downtime dual-key windows (old key valid N min after new issued). Leak
detection scanning logs/errors/stack traces before they leave the process.
Startup validation refusing to boot with missing/default secrets.

**Who built this internally:** HashiCorp (Vault is the business), Stripe (auto key rotation).

---

## Rank 10: add_schema_enforcer

**Attack prevented:** Shadow APIs, mass assignment, OWASP API1 (BOLA).

Three modes: (1) Enforcement — validates every req/resp against OpenAPI spec,
rejects non-conforming, (2) Drift detection — compares routes vs docs, alerts
shadow/zombie APIs, (3) Fuzz test generation — Schemathesis-style property
tests from schema. Blocks releases with undocumented endpoints.

**Who built this internally:** 42Crunch, Salt Security.

---

## Rank 11: add_dpop_tokens

**Attack prevented:** Token theft/replay — the #1 risk with bearer tokens.

RFC 9449 DPoP (Demonstrating Proof of Possession). Each request needs DPoP
proof JWT signed with client private key, binding token to specific client.
Proof includes method + URL. Server-side nonce support. Security of mTLS
with simplicity of bearer tokens. Mandatory for FAPI 2.0 (Open Banking).

**Who built this internally:** Every EU/UK Open Banking provider (PSD2 mandate).

---

## Rank 12: add_crypto_agility

**Attack prevented:** "Harvest now, decrypt later" quantum attacks, algorithm obsolescence.

NIST 2025 guidance. Algorithm registry for all crypto ops (no direct hashlib).
Hybrid mode: classical + post-quantum in parallel during migration. Key
derivation abstraction (HKDF/Argon2id/scrypt/PBKDF2). Post-quantum readiness
scanner auditing hardcoded algorithms and short key lengths.

**Who built this internally:** AWS, Google (hybrid PQ in Chrome), Signal (PQXDH).

---

## Rank 13: add_bola_guard

**Attack prevented:** OWASP API1 (BOLA/IDOR) — the #1 API vulnerability (34% of breaches).

Object-level authorization (not just role-level). Ownership verification
dependency: `@require_ownership(model=Order, field="user_id")`. Multi-tenant
query isolation (auto-inject tenant_id). Resource delegation support.
Auto-generates BOLA test cases: two users, verify cross-access blocked.

**Who built this internally:** Uber (after 2016 BOLA exploit), every multi-tenant SaaS.

---

## Rank 14: add_siem_bridge

**Attack prevented:** Blind spots in monitoring, delayed detection, CWE-778.

Emits in CEF (Splunk/ArcSight) + LEEF (QRadar) + JSON (Elastic/Datadog)
simultaneously. Events tagged with MITRE ATT&CK technique IDs. Pre-built
detection rules: brute force (5 fails/10min), impossible travel, credential
sharing (2 IPs in 60s). OTEL security spans separate from perf traces.

**Who built this internally:** GitHub (Advanced Security SIEM, 2025), Elastic.

---

## Rank 15: add_response_armor

**Attack prevented:** Info leakage, timing attacks, BREACH, cache poisoning.

Five layers: (1) Error sanitization — generic messages to clients, full details
to logs, (2) Constant-time auth comparisons via hmac.compare_digest,
(3) BREACH mitigation — random padding in compressed responses,
(4) Cache-Control enforcement on sensitive responses, (5) CRLF injection
protection in all header values.

**Who built this internally:** Cloudflare (BREACH edge mitigations), GitHub (error sanitization).

---

## Impact Summary

| Rank | Tool | OWASP/Risk | Build time saved |
|------|------|-----------|-----------------|
| 1 | request_signing | Tampering/Replay | 1-2 weeks |
| 2 | dlp_shield | API3 PII leak | 2-3 weeks |
| 3 | canary_tokens | Breach detection | 1-2 weeks |
| 4 | sbom_guardian | Supply chain | 1 week |
| 5 | runtime_sentinel | Injection (all) | 3-4 weeks |
| 6 | compliance_evidence | SOC2/HIPAA/PCI | 4-8 weeks |
| 7 | adaptive_throttle | API4/API6 abuse | 2-3 weeks |
| 8 | security_headers_adv | XSS/clickjack | 1 week |
| 9 | secret_rotation | Credential leak | 2-3 weeks |
| 10 | schema_enforcer | Shadow APIs | 2 weeks |
| 11 | dpop_tokens | Token theft | 1-2 weeks |
| 12 | crypto_agility | Quantum harvest | 2-3 weeks |
| 13 | bola_guard | BOLA/IDOR (#1 vuln) | 1-2 weeks |
| 14 | siem_bridge | Monitoring gaps | 2-3 weeks |
| 15 | response_armor | Info leakage | 1 week |
