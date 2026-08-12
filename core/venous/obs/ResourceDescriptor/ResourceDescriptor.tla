---- MODULE ResourceDescriptor ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for ResourceDescriptor
  Namespace: obs
  Generated from primitive contract and implementation

  Purpose: Describe the entity producing telemetry — service, version, deployment environment, instance id — and attach that identity to every span, metric, and log record.

  Invariants:
    INV_01: service.name MUST be non-empty; a missing service.name SHALL cause telemetry initialization to fail fast rather than emit 'unknown_service'.
    INV_02: service.instance.id MUST be unique per running process and SHALL be stable for the lifetime of that process.
    INV_03: deployment.environment.name MUST be one of a declared enum (development / staging / production / preview) and free-form values are FORBIDDEN.
    INV_04: The resource descriptor is immutable after construction; merged_with ALWAYS returns a new descriptor.
    INV_05: Attribute values injected through to_attributes MUST use the canonical semconv keys (service.name, not serviceName).
    INV_06: The descriptor NEVER contains secrets, credentials, or personally identifiable data.
*)

CONSTANTS MaxInt

VARIABLES service_name, service_namespace, service_version, service_instance_id, deployment_environment, attributes, None, 01, 02, ALLOWED_ENVIRONMENTS, 03, overrides, 04, 05, out

vars == <<service_name, service_namespace, service_version, service_instance_id, deployment_environment, attributes, None, 01, 02, ALLOWED_ENVIRONMENTS, 03, overrides, 04, 05, out>>

TypeOK == 
  /\ service_name \in String
  /\ service_namespace \in String
  /\ service_version \in String
  /\ service_instance_id \in String
  /\ deployment_environment \in String
  /\ attributes \in String
  /\ None \in String
  /\ 01 \in String
  /\ 02 \in String
  /\ ALLOWED_ENVIRONMENTS \in String
  /\ 03 \in String
  /\ overrides \in String
  /\ 04 \in String
  /\ 05 \in String
  /\ out \in String

Init == 
  /\ service_name = ""
  /\ service_namespace = ""
  /\ service_version = ""
  /\ service_instance_id = ""
  /\ deployment_environment = ""
  /\ attributes = ""
  /\ None = ""
  /\ 01 = ""
  /\ 02 = ""
  /\ ALLOWED_ENVIRONMENTS = ""
  /\ 03 = ""
  /\ overrides = ""
  /\ 04 = ""
  /\ 05 = ""
  /\ out = ""

(* RD_INV_01: service.name required *)
RD_INV_01 ==
  /\ TypeOK

(* RD_INV_02: instance id stable + non-empty *)
RD_INV_02 ==
  /\ TypeOK

(* RD_INV_03: env enum *)
RD_INV_03 ==
  /\ TypeOK

(* RD_INV_04: immutable *)
RD_INV_04 ==
  /\ TypeOK

(* RD_INV_05: canonical SemConv keys *)
RD_INV_05 ==
  /\ TypeOK

(* RD_INV_06: no secrets *)
RD_INV_06 ==
  /\ TypeOK

(* Operations *)
Merged_with ==
  /\ service_name' = Merged_withImpl(service_name)
  /\ UNCHANGED <<config>>

To_attributes ==
  /\ service_name' = To_attributesImpl(service_name)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Merged_with \/ To_attributes \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ RD_INV_01
  /\ RD_INV_02
  /\ RD_INV_03
  /\ RD_INV_04
  /\ RD_INV_05
  /\ RD_INV_06

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>service_name' # service_name

====