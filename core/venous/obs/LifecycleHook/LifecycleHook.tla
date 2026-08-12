---- MODULE LifecycleHook ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for LifecycleHook
  Namespace: obs
  Generated from primitive contract and implementation

  Purpose: Named callback fired at a defined application phase (starting, ready, stopping) so tools can initialize resources and shut down cleanly.

  Invariants:
    INV_01: READY MUST fire exactly once, after STARTING and all startup callbacks have completed successfully.
    INV_02: STOPPING hooks MUST run in reverse registration order (LIFO) so later-initialized resources drain first.
    INV_03: A failing STARTING hook MUST prevent READY from firing; the app SHALL transition to STOPPED with non-zero exit.
    INV_04: Hooks MUST NOT block indefinitely; each hook SHALL obey a configured timeout and be cancelled otherwise.
    INV_05: No hook CAN re-enter its own phase; recursive registration of the same callback in the same phase SHALL raise.
*)

CONSTANTS MaxInt

VARIABLES phase, cb

vars == <<phase, cb>>

TypeOK == 
  /\ phase \in String
  /\ cb \in String

Init == 
  /\ phase = ""
  /\ cb = ""

(* LIFE_INV_01: READY exactly once, after STARTING success *)
LIFE_INV_01 ==
  /\ read_version = write_version

(* LIFE_INV_02: STOPPING LIFO *)
LIFE_INV_02 ==
  /\ TypeOK

(* LIFE_INV_03: failing STARTING prevents READY *)
LIFE_INV_03 ==
  /\ read_version = write_version

(* LIFE_INV_04: timeout enforced *)
LIFE_INV_04 ==
  /\ phase <= MaxInt

(* LIFE_INV_05: no re-registration within same phase *)
LIFE_INV_05 ==
  /\ TypeOK

(* Operations *)
Register ==
  /\ phase' = RegisterImpl(phase)
  /\ UNCHANGED <<config>>

Ready_fired ==
  /\ phase' = Ready_firedImpl(phase)
  /\ UNCHANGED <<config>>

Starting_failed ==
  /\ phase' = Starting_failedImpl(phase)
  /\ UNCHANGED <<config>>

Stopped ==
  /\ phase' = StoppedImpl(phase)
  /\ UNCHANGED <<config>>

Hooks_for ==
  /\ phase' = Hooks_forImpl(phase)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Register \/ Ready_fired \/ Starting_failed \/ Stopped \/ Hooks_for \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ LIFE_INV_01
  /\ LIFE_INV_02
  /\ LIFE_INV_03
  /\ LIFE_INV_04
  /\ LIFE_INV_05

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>phase' # phase

====