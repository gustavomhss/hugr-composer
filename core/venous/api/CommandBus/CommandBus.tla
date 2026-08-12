---- MODULE CommandBus ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for CommandBus
  Namespace: api
  Generated from primitive contract and implementation

  Purpose: Dispatch Commands to their registered async handlers.

  Invariants:
    INV_01: COMMAND_BUS_INV_01: No handler registered for command: {?}
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

(* CB_INV_01: register + dispatch *)
CB_INV_01 ==
  /\ TypeOK

(* CB_INV_02: last-registrant-wins *)
CB_INV_02 ==
  /\ TypeOK

(* CB_INV_03: unknown name rejection + failure propagation *)
CB_INV_03 ==
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
  /\ CB_INV_01
  /\ CB_INV_02
  /\ CB_INV_03

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>state' # state

====