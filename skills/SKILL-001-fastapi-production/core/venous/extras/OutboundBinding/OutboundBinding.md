# OutboundBinding

## What it does (plain language)

An OutboundBinding is a declarative adapter that lets the application invoke
an external system (SendGrid, S3, SMTP, Twilio) by name and operation instead
of wiring the vendor SDK directly. The application names a binding, picks an
operation the binding has declared, sends bytes, and receives bytes — the
vendor SDK churn stays behind the adapter, never in the application.

## Purpose

Keep every external integration behind one declarative adapter that exposes a
typed-operation surface and a metadata map; the adapter CANNOT mutate payload
bytes, CANNOT accept unregistered binding names, and CANNOT accept metadata
that matches credential patterns.

## When to use and when NOT to use

- USE: outbound HTTP webhook, outbound email, outbound cloud-queue publish,
  outbound storage upload.
- DO NOT USE: inbound ingestion (that is a different primitive).
- DO NOT USE: in-process calls — the overhead is not justified for local code.

## API surface

See `OutboundBinding.contract.json` for the verbatim catalog Protocol. The
implementation `OutboundBinding.py` provides `InMemoryOutboundBinding` as a
reference runtime keyed on a registry of `BindingComponent`. Each component
declares the allowed operation set and an async `execute` callable.

## Invariants

| ID | Rule |
|---|---|
| OBND_INV_01 | The `operation` field MUST be one of the operations declared by the binding component; unknown values SHALL be rejected. |
| OBND_INV_02 | `binding_name` ALWAYS refers to a component already registered; an unresolved name CANNOT invoke anything. |
| OBND_INV_03 | Metadata keys NEVER include secrets in plaintext because binding metadata can be logged by observability layers. |
| OBND_INV_04 | Binary payloads MUST round-trip unchanged; the adapter CANNOT mutate data bytes implicitly. |
| OBND_INV_05 | Invocation timeouts SHALL be honored by the adapter or explicitly surfaced as a deadline error. |

## Invariant -> test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the authoritative binding.

## Thread and async safety

- `InMemoryOutboundBinding.invoke` is async and thread-neutral; the registry
  is frozen at construction. Under concurrent callers the adapter may be
  serialized or parallelized depending on the underlying execute.
- `validate_invocation` and `validate_metadata_secrets` are pure — safe to
  call from any context.

## Operational characteristics (for SRE)

- `binding.invoke.calls` counter with labels `binding_name`, `operation`,
  `outcome`. Sustained `outcome=deadline_exceeded` means the adapter is
  upstream-bound; sustained `outcome=rejected` means caller metadata violates
  OBND-INV-03.
- `binding.invoke.duration` histogram (ms) — p99 per binding is the primary
  latency metric.
- Payload size histogram `binding.invoke.payload_size` (bytes) exposes
  saturation risk on the adapter transport.

## Security considerations

- OBND-INV-03 enforces a heuristic secret filter over metadata values and
  key names (`password`, `secret`, `api_key`, common bearer token shapes).
  Applications MUST carry credentials through an auth context, never via
  binding metadata that the observability layer can serialize.
- OBND-INV-01 bounds the operation surface, preventing an attacker who
  influences the `operation` string from invoking adapter features outside
  the declared set.
- The adapter MUST preserve bytes (OBND-INV-04); silent re-encoding (UTF-8
  normalization, line ending rewrites) is forbidden.

## Provenance

- Source agent: Agent #2 DISTRIBUTED
  (`docs/research/outputs/AGENT_2_DISTRIBUTED.json`).
- Primary source: Dapr 1.14 Bindings building-block overview — Output
  bindings, operation field, metadata sections.

## Alternatives considered and rejected

- Direct vendor SDK calls inside each tool — rejected because it couples
  deployments to SDK release cadence and scatters credentials.
- HTTP-only facade — rejected because it loses the operation taxonomy and
  typed metadata.

## Extension contract

Add a new external system by implementing the `BindingComponent` execute
callable (HTTP, S3, SMTP, Twilio) and registering the component under a
stable binding name at runtime construction. Applications extend by composing
decorators around `invoke` for retry, circuit breaking, or quota enforcement.
The Protocol surface is v1; additive operations are allowed without breaking
callers.

## Schema of `OutboundBinding.contract.json`

Verbatim copy of the `PrimitiveSpec` dict from the research catalog. See
`docs/research/CONTRACT_STANDARDS.md` section 2 (PrimitiveSpec).

## Usage

```python
async def email(binding: OutboundBinding, to: str, body: bytes) -> None:
    inv = BindingInvocation(
        binding_name="sendgrid",
        operation="create",
        data=body,
        metadata={"emailTo": to},
    )
    await binding.invoke(inv)
```

## Compose with:

- **Typed SDK facade** → `AntiCorruptionLayer` + `SecretsVault`
  Callers see typed operations; the adapter loads credentials from the vault and translates SDK types — no vendor import leaks into business code.

- **Resilient egress** → `CircuitBreaker` + `RetryPolicy`
  Every outbound call is wrapped in a breaker + retry policy; a flaky vendor does not cascade into the primary transaction.

- **Swap-in-place** → `DiContainer` + `FeatureToggle`
  Adapters are DI-registered; a toggle switches between vendors at runtime without redeploy — vendor lock-in becomes a configuration decision.
