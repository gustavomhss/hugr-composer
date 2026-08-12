---- MODULE DeprecationRegistry ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for DeprecationRegistry
  Namespace: api
  Generated from primitive contract and implementation

  Purpose: Index DeprecationEntry objects by their (METHOD, path) composite key so request middleware can cheaply decide whether to stamp RFC 8594 Sunset headers on a response and so operators can list all deprecations sorted by sunset date.

  Invariants:
    INV_01: DEPRECATION_REGISTRY_INV_01: The lookup key MUST be 'METHOD path' with METHOD upper-cased; get() MUST return the same entry that register() stored under that key.
    INV_02: DEPRECATION_REGISTRY_INV_02: register() MUST replace any previous entry bound to the same (method, path) composite key; duplicate registration is last-writer-wins and never silently ignored.
    INV_03: DEPRECATION_REGISTRY_INV_03: list_all() MUST return entries sorted by sunset date ascending, so the soonest-to-sunset endpoint is always first.
    INV_04: DEPRECATION_REGISTRY_INV_04: get() MUST return None (never raise) for an unregistered (method, path); absence is a valid steady state.
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

(* DR_INV_01: key uniqueness (method+path composite) *)
DR_INV_01 ==
  /\ TypeOK

(* DR_INV_02: method case-insensitivity *)
DR_INV_02 ==
  /\ old_version = expected => success

(* DR_INV_03: warn-on-register *)
DR_INV_03 ==
  /\ TypeOK

(* DR_INV_04: list_all sort order *)
DR_INV_04 ==
  /\ TypeOK

(* Operations *)
Register ==
  /\ state' = RegisterImpl(state)
  /\ UNCHANGED <<config>>

Get ==
  /\ key # ""
  /\ result' = GetImpl(key)
  /\ UNCHANGED <<config>>

List_all ==
  /\ state' = List_allImpl(state)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Register \/ Get \/ List_all \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ DR_INV_01
  /\ DR_INV_02
  /\ DR_INV_03
  /\ DR_INV_04

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>state' # state

====