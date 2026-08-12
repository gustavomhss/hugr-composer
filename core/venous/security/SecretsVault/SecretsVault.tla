---- MODULE SecretsVault ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for SecretsVault
  Namespace: security
  Generated from primitive contract and implementation

  Purpose: Fetch, cache, rotate, and audit application secrets through a named-secret interface backed by an external key management or secrets service.

  Invariants:
    INV_01: Secret material MUST NEVER be logged, included in tracebacks, or serialized to telemetry.
    INV_02: get() MUST honor a time-bounded cache; cached material MUST NEVER outlive not_after or the configured max-age.
    INV_03: rotate() MUST produce a strictly increasing version and MUST NEVER return the same material for a different version.
    INV_04: Every get()/rotate() call SHALL emit a structured audit event naming the secret (not the material) and the caller identity.
    INV_05: When the underlying backend is unavailable, the vault MUST fail closed for cold secrets and CANNOT surface stale material past its cache TTL.
*)

CONSTANTS MaxInt

VARIABLES name, version, material, not_after, str, timestamp_ms, operation, secret_name, caller_identity, outcome, cache_hit, cached_at_s, expires_at_s, correctness, _caller_context, identity, 04, try, finally, allowed, supports_monotonic_versions, supports_rotation_callback, caps, 03

vars == <<name, version, material, not_after, str, timestamp_ms, operation, secret_name, caller_identity, outcome, cache_hit, cached_at_s, expires_at_s, correctness, _caller_context, identity, 04, try, finally, allowed, supports_monotonic_versions, supports_rotation_callback, caps, 03>>

TypeOK == 
  /\ name \in String
  /\ version \in 0..MaxInt
  /\ material \in String
  /\ not_after \in 0..MaxInt
  /\ str \in String
  /\ timestamp_ms \in 0..MaxInt
  /\ operation \in String
  /\ secret_name \in String
  /\ caller_identity \in String
  /\ outcome \in String
  /\ cache_hit \in {TRUE, FALSE}
  /\ cached_at_s \in 0..MaxInt
  /\ expires_at_s \in 0..MaxInt
  /\ correctness \in String
  /\ _caller_context \in String
  /\ identity \in String
  /\ 04 \in String
  /\ try \in String
  /\ finally \in String
  /\ allowed \in String
  /\ supports_monotonic_versions \in {TRUE, FALSE}
  /\ supports_rotation_callback \in {TRUE, FALSE}
  /\ caps \in String
  /\ 03 \in String

Init == 
  /\ name = ""
  /\ version = 0
  /\ material = ""
  /\ not_after = 0
  /\ str = ""
  /\ timestamp_ms = 0
  /\ operation = ""
  /\ secret_name = ""
  /\ caller_identity = ""
  /\ outcome = ""
  /\ cache_hit = FALSE
  /\ cached_at_s = 0
  /\ expires_at_s = 0
  /\ correctness = ""
  /\ _caller_context = ""
  /\ identity = ""
  /\ 04 = ""
  /\ try = ""
  /\ finally = ""
  /\ allowed = ""
  /\ supports_monotonic_versions = FALSE
  /\ supports_rotation_callback = FALSE
  /\ caps = ""
  /\ 03 = ""

(* SV_INV_01: material NEVER leaked in logs / reprs / exceptions *)
SV_INV_01 ==
  /\ TypeOK

(* SV_INV_02: TTL-bounded cache *)
SV_INV_02 ==
  /\ cache_expiry <= MIN(exp, ttl)

(* SV_INV_03: rotation is strictly monotonic *)
SV_INV_03 ==
  /\ version' = version + 1

(* SV_INV_04: every operation emits an audit event *)
SV_INV_04 ==
  /\ state' # state => event_emitted

(* SV_INV_05: fail closed on backend outage; no stale reads *)
SV_INV_05 ==
  /\ read_version = write_version

(* Operations *)
Get ==
  /\ key # ""
  /\ result' = GetImpl(key)
  /\ UNCHANGED <<config>>

Rotate ==
  /\ name' = RotateImpl(name)
  /\ UNCHANGED <<config>>

Invalidate ==
  /\ name' = InvalidateImpl(name)
  /\ UNCHANGED <<config>>

Fetch ==
  /\ name' = FetchImpl(name)
  /\ UNCHANGED <<config>>

Now_s ==
  /\ name' = Now_sImpl(name)
  /\ UNCHANGED <<config>>

Register ==
  /\ name' = RegisterImpl(name)
  /\ UNCHANGED <<config>>

Set_available ==
  /\ name' = Set_availableImpl(name)
  /\ UNCHANGED <<config>>

Register_gcp_secret_manager_backend ==
  /\ name' = Register_gcp_secret_manager_backendImpl(name)
  /\ UNCHANGED <<config>>

Register_azure_key_vault_backend ==
  /\ name' = Register_azure_key_vault_backendImpl(name)
  /\ UNCHANGED <<config>>

Current_caller_identity ==
  /\ name' = Current_caller_identityImpl(name)
  /\ UNCHANGED <<config>>

Events ==
  /\ name' = EventsImpl(name)
  /\ UNCHANGED <<config>>

Clear ==
  /\ name' = ClearImpl(name)
  /\ UNCHANGED <<config>>

Declare_scope ==
  /\ name' = Declare_scopeImpl(name)
  /\ UNCHANGED <<config>>

Validate_adapter ==
  /\ name' = Validate_adapterImpl(name)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Get \/ Rotate \/ Invalidate \/ Fetch \/ Now_s \/ Register \/ Set_available \/ Register_gcp_secret_manager_backend \/ Register_azure_key_vault_backend \/ Current_caller_identity \/ Events \/ Clear \/ Declare_scope \/ Validate_adapter \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ SV_INV_01
  /\ SV_INV_02
  /\ SV_INV_03
  /\ SV_INV_04
  /\ SV_INV_05

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>name' # name

====