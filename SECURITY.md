# Security Policy

## Reporting a vulnerability

HuGR Smith generates production backend code. A bug in a generator
or a primitive can propagate to every project scaffolded from it, so we
treat security reports seriously.

**Do NOT open a public GitHub issue for security bugs.** Send a private
report instead:

- **Email:** `security@humangr.com`
- **PGP:** key fingerprint published at `https://humangr.com/.well-known/pgp-security.asc`
  (optional — plain email is accepted).
- **Subject line:** `SECURITY: <short summary>`

Include in your report:

1. A clear description of the issue and the affected component
   (tool name, primitive name, generator file).
2. Steps to reproduce — preferably a minimal MCP session transcript
   or a `pytest` case that triggers the bug.
3. An assessment of the impact if you have one (auth bypass, injection,
   DoS, etc.).
4. Your preferred attribution if the report leads to a fix (or
   "anonymous").

## Response SLA

| Severity | First ACK | Mitigation plan |
|---|---|---|
| Critical (generated code ships a shell-injection / auth bypass / data leak) | ≤ 24 hours | within 72 hours |
| High (generated code ships a known-bad crypto default, unsafe default) | ≤ 48 hours | within 7 days |
| Medium (generator bug that affects edge cases, non-default paths) | ≤ 5 business days | within 30 days |
| Low (documentation bug, cosmetic, non-exploitable) | ≤ 10 business days | next MINOR release |

We publish fixes as PATCH releases (semver) and reference the report
(with permission) in the CHANGELOG under the release's `### Security`
header.

## Scope

In-scope:

- The skill itself: tools, primitives, generators, adapters, and the
  MCP server in `skills/SKILL-001-fastapi-production/`.
- Code emitted by any tool / generator in a generated project
  (i.e. if the generator emits vulnerable code).
- Install path (`install.sh`, `Dockerfile`) — supply-chain concerns.

Out-of-scope:

- Vulnerabilities in third-party dependencies unless we pin the
  affected version (then it's our fix to bump the pin; report is
  in-scope).
- Issues in Forge (the host editor) or Maestro (the agent
  orchestrator) — please file those with their respective teams.
- Social-engineering, physical access, or DoS-via-resource-exhaustion
  against the user's own machine.

## Safe-harbor

We will not pursue legal action or file a complaint for security
research conducted in good faith against this repository, provided
the researcher:

- Does not intentionally degrade service for other users.
- Does not exfiltrate more data than necessary to demonstrate the issue.
- Gives us a reasonable window (coordinated disclosure) before public
  discussion.

Thank you for helping keep HuGR Smith safe.
