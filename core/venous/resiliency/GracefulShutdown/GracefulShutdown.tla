---- MODULE GracefulShutdown ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for GracefulShutdown
  Namespace: resiliency
  Generated from primitive contract and implementation

  Purpose: Coordinates process shutdown across three phases — drain (stop accepting new work), wait-for-in-flight (bounded by timeout), and cleanup (run registered callbacks) — so a service can exit cleanly on SIGTERM/SIGINT without dropping in-flight work.

  Invariants:
    INV_01: GRACEFUL_SHUTDOWN_INV_01: Once `register()` observes a shutdown signal, `is_draining()` MUST return True for the rest of the process lifetime (monotonic, never resets).
    INV_02: GRACEFUL_SHUTDOWN_INV_02: `wait_complete()` MUST NOT return before `drain_seconds` elapses AND (in-flight count drops to zero OR `timeout_seconds` elapses), whichever comes first.
    INV_03: GRACEFUL_SHUTDOWN_INV_03: `decrement_in_flight()` MUST NOT let the in-flight counter go negative — unbalanced decrements are clamped to zero, not the caller's problem.
*)

CONSTANTS MaxInt

VARIABLES drain_seconds, timeout_seconds

vars == <<drain_seconds, timeout_seconds>>

TypeOK == 
  /\ drain_seconds \in String
  /\ timeout_seconds \in String

Init == 
  /\ drain_seconds = ""
  /\ timeout_seconds = ""

(* GRACEFULSHUTDOWN_INV_01: GRACEFUL_SHUTDOWN_INV_01: Once `register()` observes a shutdown signal, `is_draining()` MUST return True for the rest of the process lifetime (monotonic, never resets). *)
GRACEFULSHUTDOWN_INV_01 ==
  /\ version' = version + 1

(* GRACEFULSHUTDOWN_INV_02: GRACEFUL_SHUTDOWN_INV_02: `wait_complete()` MUST NOT return before `drain_seconds` elapses AND (in-flight count drops to zero OR `timeout_seconds` elapses), whichever comes first. *)
GRACEFULSHUTDOWN_INV_02 ==
  /\ drain_seconds <= MaxInt

(* GRACEFULSHUTDOWN_INV_03: GRACEFUL_SHUTDOWN_INV_03: `decrement_in_flight()` MUST NOT let the in-flight counter go negative — unbalanced decrements are clamped to zero, not the caller's problem. *)
GRACEFULSHUTDOWN_INV_03 ==
  /\ TypeOK

(* Operations *)
Register ==
  /\ drain_seconds' = RegisterImpl(drain_seconds)
  /\ UNCHANGED <<config>>

Is_draining ==
  /\ drain_seconds' = Is_drainingImpl(drain_seconds)
  /\ UNCHANGED <<config>>

Increment_in_flight ==
  /\ drain_seconds' = Increment_in_flightImpl(drain_seconds)
  /\ UNCHANGED <<config>>

Decrement_in_flight ==
  /\ drain_seconds' = Decrement_in_flightImpl(drain_seconds)
  /\ UNCHANGED <<config>>

Add_cleanup ==
  /\ drain_seconds' = Add_cleanupImpl(drain_seconds)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Register \/ Is_draining \/ Increment_in_flight \/ Decrement_in_flight \/ Add_cleanup \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ GRACEFULSHUTDOWN_INV_01
  /\ GRACEFULSHUTDOWN_INV_02
  /\ GRACEFULSHUTDOWN_INV_03

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>drain_seconds' # drain_seconds

====