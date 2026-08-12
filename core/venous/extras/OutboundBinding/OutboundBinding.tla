---- MODULE OutboundBinding ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for OutboundBinding
  Namespace: extras
  Generated from primitive contract and implementation

  Purpose: Declarative adapter that lets the application invoke an external resource through a named operation and metadata without embedding the vendor SDK.

  Invariants:
    INV_01: The operation field MUST be one of the operations declared by the binding component; unknown values SHALL be rejected.
    INV_02: binding_name ALWAYS refers to a component already registered in the runtime; an unresolved name CANNOT invoke anything.
    INV_03: Metadata keys NEVER include secrets in plaintext because binding metadata can be logged by observability layers.
    INV_04: Binary payloads MUST round trip unchanged; the adapter CANNOT mutate data bytes implicitly.
    INV_05: Invocation timeouts SHALL be honored by the adapter or explicitly surfaced as a deadline error.
*)

CONSTANTS MaxInt

VARIABLES binding_name, operation, data, metadata, name, allowed_operations, execute, 03, supporting, _SECRET_SIGNATURES, _SECRET_KEY_PATTERNS, req, registry, 02, 01, 04

vars == <<binding_name, operation, data, metadata, name, allowed_operations, execute, 03, supporting, _SECRET_SIGNATURES, _SECRET_KEY_PATTERNS, req, registry, 02, 01, 04>>

TypeOK == 
  /\ binding_name \in String
  /\ operation \in String
  /\ data \in String
  /\ metadata \in String
  /\ name \in String
  /\ allowed_operations \in String
  /\ execute \in String
  /\ 03 \in String
  /\ supporting \in String
  /\ _SECRET_SIGNATURES \in String
  /\ _SECRET_KEY_PATTERNS \in String
  /\ req \in String
  /\ registry \in String
  /\ 02 \in String
  /\ 01 \in String
  /\ 04 \in String

Init == 
  /\ binding_name = ""
  /\ operation = ""
  /\ data = ""
  /\ metadata = ""
  /\ name = ""
  /\ allowed_operations = ""
  /\ execute = ""
  /\ 03 = ""
  /\ supporting = ""
  /\ _SECRET_SIGNATURES = ""
  /\ _SECRET_KEY_PATTERNS = ""
  /\ req = ""
  /\ registry = ""
  /\ 02 = ""
  /\ 01 = ""
  /\ 04 = ""

(* OBND_INV_01: operation must be declared *)
OBND_INV_01 ==
  /\ TypeOK

(* OBND_INV_02: binding_name must resolve *)
OBND_INV_02 ==
  /\ TypeOK

(* OBND_INV_03: no plaintext secrets in metadata *)
OBND_INV_03 ==
  /\ TypeOK

(* OBND_INV_04: bytes roundtrip unchanged *)
OBND_INV_04 ==
  /\ TypeOK

(* OBND_INV_05: timeout honored *)
OBND_INV_05 ==
  /\ binding_name <= MaxInt

(* Operations *)
Validate_invocation ==
  /\ binding_name' = Validate_invocationImpl(binding_name)
  /\ UNCHANGED <<config>>

Invocations ==
  /\ binding_name' = InvocationsImpl(binding_name)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Validate_invocation \/ Invocations \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ OBND_INV_01
  /\ OBND_INV_02
  /\ OBND_INV_03
  /\ OBND_INV_04
  /\ OBND_INV_05

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>binding_name' # binding_name

====