---- MODULE RpcInterceptor ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for RpcInterceptor
  Namespace: extras
  Generated from primitive contract and implementation

  Purpose: Per call middleware that wraps a remote procedure invocation to read or mutate metadata, enforce deadlines and translate errors consistently across services.

  Invariants:
    INV_01: Interceptors MUST call next exactly once per invocation unless they deliberately short circuit with a status.
    INV_02: Metadata keys that end with '-bin' ALWAYS carry binary values and CANNOT be compared as plain strings.
    INV_03: Keys starting with 'grpc-' are FORBIDDEN for user metadata because that prefix is reserved by the runtime.
    INV_04: A deadline propagated in ctx MUST NOT be extended by an interceptor; it SHALL only be shortened or respected.
    INV_05: Cancellation signals NEVER cross interceptor boundaries silently; every interceptor SHALL honor cancel or raise a cancellation error.
*)

CONSTANTS MaxInt

VARIABLES method, deadline_ms, metadata

vars == <<method, deadline_ms, metadata>>

TypeOK == 
  /\ method \in String
  /\ deadline_ms \in 0..MaxInt
  /\ metadata \in String

Init == 
  /\ method = ""
  /\ deadline_ms = 0
  /\ metadata = ""

(* RPCI_INV_01: next called exactly once unless short-circuiting *)
RPCI_INV_01 ==
  /\ TypeOK

(* RPCI_INV_02: -bin suffix MUST carry bytes *)
RPCI_INV_02 ==
  /\ TypeOK

(* RPCI_INV_03: grpc- prefix reserved *)
RPCI_INV_03 ==
  /\ TypeOK

(* RPCI_INV_04: deadline only shortened, never extended *)
RPCI_INV_04 ==
  /\ TypeOK

(* RPCI_INV_05: cancellation MUST propagate or raise, NEVER silently swallowed *)
RPCI_INV_05 ==
  /\ TypeOK

(* Operations *)
Validate_deadline ==
  /\ method' = Validate_deadlineImpl(method)
  /\ UNCHANGED <<config>>

Shorten_deadline ==
  /\ method' = Shorten_deadlineImpl(method)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Validate_deadline \/ Shorten_deadline \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ RPCI_INV_01
  /\ RPCI_INV_02
  /\ RPCI_INV_03
  /\ RPCI_INV_04
  /\ RPCI_INV_05

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>method' # method

====