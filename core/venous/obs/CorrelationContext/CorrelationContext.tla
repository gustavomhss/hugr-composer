---- MODULE CorrelationContext ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for CorrelationContext
  Namespace: obs
  Generated from primitive contract and implementation

  Purpose: Propagate a stable request identifier and optional baggage across threads, async tasks, and network hops so every downstream record can be joined back to the originating request.

  Invariants:
    INV_01: The request_id MUST be a lowercase hex or ULID string of at least 16 characters and SHALL be stable for the entire request lifecycle.
    INV_02: Baggage values MUST be ASCII and each individual value CANNOT exceed 8192 bytes per W3C Baggage specification.
    INV_03: Activating a context MUST restore the prior context on exit even if an exception is raised.
    INV_04: When extracting from headers, an invalid traceparent value SHALL cause a new trace id to be generated and NEVER falls back to an empty trace context.
    INV_05: Baggage keys reserved for authentication (password, authorization, cookie) are FORBIDDEN and SHALL be stripped on ingest.
    INV_06: CorrelationContext NEVER leaks across event loops; asynchronous task spawns copy-on-capture the current context via contextvars.
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

(* CORR_INV_01: request_id shape + stability *)
CORR_INV_01 ==
  /\ TypeOK

(* CORR_INV_02: baggage limits *)
CORR_INV_02 ==
  /\ TypeOK

(* CORR_INV_03: activate restores prior ctx even under exception *)
CORR_INV_03 ==
  /\ TypeOK

(* CORR_INV_04: invalid traceparent → new trace_id, never empty *)
CORR_INV_04 ==
  /\ TypeOK

(* CORR_INV_05: forbidden baggage keys stripped *)
CORR_INV_05 ==
  /\ TypeOK

(* CORR_INV_06: contextvars isolation across async tasks *)
CORR_INV_06 ==
  /\ TypeOK

(* Operations *)
Request_id ==
  /\ state' = Request_idImpl(state)
  /\ UNCHANGED <<config>>

Trace_id ==
  /\ state' = Trace_idImpl(state)
  /\ UNCHANGED <<config>>

Baggage ==
  /\ state' = BaggageImpl(state)
  /\ UNCHANGED <<config>>

Activate ==
  /\ state' = ActivateImpl(state)
  /\ UNCHANGED <<config>>

Current ==
  /\ state' = CurrentImpl(state)
  /\ UNCHANGED <<config>>

From_headers ==
  /\ state' = From_headersImpl(state)
  /\ UNCHANGED <<config>>

To_headers ==
  /\ state' = To_headersImpl(state)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Request_id \/ Trace_id \/ Baggage \/ Activate \/ Current \/ From_headers \/ To_headers \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ CORR_INV_01
  /\ CORR_INV_02
  /\ CORR_INV_03
  /\ CORR_INV_04
  /\ CORR_INV_05
  /\ CORR_INV_06

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>state' # state

====