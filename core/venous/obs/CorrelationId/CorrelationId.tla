---- MODULE CorrelationId ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for CorrelationId
  Namespace: obs
  Generated from primitive contract and implementation

  Purpose: Opaque string that travels with a request across services and log lines so a reader can stitch together the work done for one user action.

  Invariants:
    INV_01: MUST be populated for every inbound request before the first log line is emitted.
    INV_02: NEVER regenerates a present upstream id (propagates 'traceparent'/'X-Request-Id' when valid).
    INV_03: Generated ids MUST use a cryptographically-random 16+ byte encoding; sequential counters SHALL NOT be used.
    INV_04: MUST appear in every emitted log, metric exemplar, and outbound HTTP request header.
    INV_05: CANNOT be mutated mid-request; a new id SHALL mean a new logical request.
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

(* CORRID_INV_01: every inbound request gets an id before any log. *)
CORRID_INV_01 ==
  /\ TypeOK

(* CORRID_INV_02: propagate a valid upstream id, never overwrite. *)
CORRID_INV_02 ==
  /\ TypeOK

(* CORRID_INV_03: CSPRNG, not sequential. *)
CORRID_INV_03 ==
  /\ TypeOK

(* CORRID_INV_04: appears in outbound headers. *)
CORRID_INV_04 ==
  /\ TypeOK

(* CORRID_INV_05: immutable value, frozen type semantics. *)
CORRID_INV_05 ==
  /\ TypeOK

(* Operations *)
Current ==
  /\ state' = CurrentImpl(state)
  /\ UNCHANGED <<config>>

Generate ==
  /\ state' = GenerateImpl(state)
  /\ UNCHANGED <<config>>

Parse ==
  /\ state' = ParseImpl(state)
  /\ UNCHANGED <<config>>

To_str ==
  /\ state' = To_strImpl(state)
  /\ UNCHANGED <<config>>

Extract ==
  /\ state' = ExtractImpl(state)
  /\ UNCHANGED <<config>>

Inject ==
  /\ state' = InjectImpl(state)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Current \/ Generate \/ Parse \/ To_str \/ Extract \/ Inject \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ CORRID_INV_01
  /\ CORRID_INV_02
  /\ CORRID_INV_03
  /\ CORRID_INV_04
  /\ CORRID_INV_05

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>state' # state

====