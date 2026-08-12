---- MODULE QueryBus ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for QueryBus
  Namespace: api
  Generated from primitive contract and implementation

  Purpose: Dispatch Queries to their registered async handlers.

  Invariants:
    INV_01: QUERY_BUS_INV_01: No handler registered for query: {?}
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

(* QUERYBUS_INV_01: QUERY_BUS_INV_01: No handler registered for query: {?} *)
QUERYBUS_INV_01 ==
  /\ TypeOK

(* Operations *)
Register ==
  /\ state' = RegisterImpl(state)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Register \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ QUERYBUS_INV_01

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>state' # state

====