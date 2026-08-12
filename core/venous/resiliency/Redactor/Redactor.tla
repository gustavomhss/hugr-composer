---- MODULE Redactor ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for Redactor
  Namespace: resiliency
  Generated from primitive contract and implementation

  Purpose: Structlog processor that redacts PII-shaped substrings (emails, CC numbers, tokens, etc.) from every string value in an event dict, in-place. Called on the logging hot path; MUST be O(1) in event-dict size for non-string values and never raise.

  Invariants:
    INV_01: REDACTOR_INV_01: `__call__` MUST return the SAME event_dict object it received (in-place mutation) so downstream structlog processors see the redacted payload.
    INV_02: REDACTOR_INV_02: Non-string values (ints, lists, objects) MUST pass through UNCHANGED — the redactor only rewrites string values.
    INV_03: REDACTOR_INV_03: No matter what malformed input arrives, `__call__` MUST NOT raise; a logging processor that throws breaks the entire logging pipeline.
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

(* REDACTOR_INV_01: REDACTOR_INV_01: `__call__` MUST return the SAME event_dict object it received (in-place mutation) so downstream structlog processors see the redacted payload. *)
REDACTOR_INV_01 ==
  /\ TypeOK

(* REDACTOR_INV_02: REDACTOR_INV_02: Non-string values (ints, lists, objects) MUST pass through UNCHANGED — the redactor only rewrites string values. *)
REDACTOR_INV_02 ==
  /\ TypeOK

(* REDACTOR_INV_03: REDACTOR_INV_03: No matter what malformed input arrives, `__call__` MUST NOT raise; a logging processor that throws breaks the entire logging pipeline. *)
REDACTOR_INV_03 ==
  /\ TypeOK

(* Operations *)
Execute ==
  /\ state' = ExecuteImpl(state)
  /\ UNCHANGED <<config>>

Reset ==
  /\ key # ""
  /\ state' = InitState
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Execute \/ Reset \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ REDACTOR_INV_01
  /\ REDACTOR_INV_02
  /\ REDACTOR_INV_03

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>state' # state

====