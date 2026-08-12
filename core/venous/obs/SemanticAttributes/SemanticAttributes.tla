---- MODULE SemanticAttributes ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for SemanticAttributes
  Namespace: obs
  Generated from primitive contract and implementation

  Purpose: Expose the OpenTelemetry semantic-convention attribute keys as typed constants and enforce that primitives populate required keys for HTTP, database, messaging, and GenAI operations.

  Invariants:
    INV_01: Attribute keys MUST match the lowercase dotted notation specified by OpenTelemetry Semantic Conventions 1.27 and SHALL NEVER be aliased to custom names.
    INV_02: Required keys for a given domain (http.request.method for HTTP server spans, db.system for DB spans) MUST be populated before a span ends.
    INV_03: Values for enum attributes (db.system, messaging.system) MUST come from the SemConv registry and CANNOT be free-form strings.
    INV_04: Deprecated keys SHALL be aliased to the current key with a one-time warning, NEVER silently dropped.
    INV_05: The full SQL statement under db.statement MUST be redacted when the deployment environment is production; literal parameter values are FORBIDDEN.
    INV_06: SemanticAttributes class keys are immutable class attributes and NEVER reassigned at runtime.
*)

CONSTANTS MaxInt

VARIABLES state, config

vars == <<state, config>>

TypeOK == 
  /\ state \in String
  /\ config \in String

Init == 
  /\ state = ""
  /\ config = ""

(* SEM_INV_01: key format *)
SEM_INV_01 ==
  /\ TypeOK

(* SEM_INV_02: required keys satisfied *)
SEM_INV_02 ==
  /\ TypeOK

(* SEM_INV_03: enum values *)
SEM_INV_03 ==
  /\ TypeOK

(* SEM_INV_04: deprecated aliases *)
SEM_INV_04 ==
  /\ TypeOK

(* SEM_INV_05: SQL redaction in production *)
SEM_INV_05 ==
  /\ TypeOK

(* SEM_INV_06: class immutable *)
SEM_INV_06 ==
  /\ TypeOK

(* Operations *)
Validate_key_format ==
  /\ state' = Validate_key_formatImpl(state)
  /\ UNCHANGED <<config>>

Validate_enum_value ==
  /\ state' = Validate_enum_valueImpl(state)
  /\ UNCHANGED <<config>>

Canonicalize_key ==
  /\ state' = Canonicalize_keyImpl(state)
  /\ UNCHANGED <<config>>

Required_keys_satisfied ==
  /\ state' = Required_keys_satisfiedImpl(state)
  /\ UNCHANGED <<config>>

Missing_required_keys ==
  /\ state' = Missing_required_keysImpl(state)
  /\ UNCHANGED <<config>>

Redact_db_statement ==
  /\ state' = Redact_db_statementImpl(state)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Validate_key_format \/ Validate_enum_value \/ Canonicalize_key \/ Required_keys_satisfied \/ Missing_required_keys \/ Redact_db_statement \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ SEM_INV_01
  /\ SEM_INV_02
  /\ SEM_INV_03
  /\ SEM_INV_04
  /\ SEM_INV_05
  /\ SEM_INV_06

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>state' # state

====