# ResourceDescriptor

## What it does (plain language)

ResourceDescriptor labels every piece of telemetry with "which service, which
version, which environment, which instance" so backends can aggregate across
thousands of processes without identity drift. Product impact: one canonical
service name per deployment, zero "three dashboards for the same service"
duplication.

## Purpose

Describe the entity producing telemetry — service, version, deployment
environment, instance id — and attach that identity to every span, metric,
and log record.

## When to use and when NOT to use

- USE: at telemetry bootstrap, once per process.
- DO NOT USE: for per-request identity — that is `CorrelationContext`.
- DO NOT USE: as a runtime configuration object — resource identity is pinned.

## Invariants

| ID | Rule |
|---|---|
| RD_INV_01 | service.name MUST be non-empty; missing SHALL fast-fail init. |
| RD_INV_02 | service.instance.id MUST be unique per process and stable for its lifetime. |
| RD_INV_03 | deployment.environment.name MUST be one of {development, staging, production, preview}. |
| RD_INV_04 | Descriptor is immutable; merged_with ALWAYS returns a new descriptor. |
| RD_INV_05 | to_attributes MUST use canonical semconv keys. |
| RD_INV_06 | The descriptor NEVER contains secrets, credentials, or PII. |

## Thread safety

Frozen dataclass; attributes are copied defensively. Safe across threads.

## Operational characteristics

- Construction cost: O(1) validation per attribute.
- Memory: a few hundred bytes per descriptor.
- Immutability: each `merged_with` returns a fresh descriptor; no in-place
  mutation exists.

## Security considerations

- Secret-like attribute values and keys are rejected at construction with a
  regex scan; a producer that attaches Authorization headers or api_key values
  fails fast.
- The enum constraint on `deployment.environment.name` prevents accidental
  "prod2" fan-out where alerts would miss a new environment name.

## Provenance

- Source agent: Agent #7 OBSERVABILITY.
- OpenTelemetry Semantic Conventions 1.27 — Resource.
- OpenTelemetry Specification 1.32 — Resource SDK.
- Google SRE Book chapter 6 section on per-instance identity.

## Alternatives considered and rejected

- Attaching service.name at each span call site — rejected: bloats instrumentation.
- Environment variables consumed ad hoc — rejected: typing, validation missing.
- Kubernetes downward API alone — rejected: non-K8s targets need distinct detectors.

## Extension contract

Platforms extend resource detection by registering a `ResourceDetector` plugin
(Kubernetes, ECS, Lambda) that contributes additional SemConv-compliant
attributes. The merge adapter resolves conflicts by giving explicit
configuration priority over auto-detected values.

## Usage

```python
def build_resource() -> ResourceDescriptor:
    desc = ResourceDescriptor(
        service_name="checkout",
        service_namespace="payments",
        service_version="2026.04.3",
        service_instance_id="pod-abc-123",
        deployment_environment="production",
        attributes={"cloud.provider": "aws", "cloud.region": "us-east-1"},
    )
    return desc
```

## Compose with:

- **Uniform telemetry identity** → `TelemetryExporter` + `SemanticAttributes`
  Every span, metric, and log carries the same resource attributes; dashboards filter by service.version without ad-hoc tagging.

- **Deployment correlation** → `LifecycleHook` + `StructuredLogger`
  Startup hooks stamp the descriptor into ready events; regressions line up with deploy boundaries in the log stream.

- **Probe-visible identity** → `HealthProbe` + `Tracer`
  Probes report the descriptor alongside health; on-call sees 'which instance of which version' at a glance.
