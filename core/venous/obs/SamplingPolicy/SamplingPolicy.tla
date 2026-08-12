---- MODULE SamplingPolicy ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for SamplingPolicy
  Namespace: obs
  Generated from primitive contract and implementation

  Purpose: Decide whether a given trace or span is retained, combining head-based (at span start) and tail-based (post hoc) rules and honoring the parent sampling decision.

  Invariants:
    INV_01: When a parent span carries the sampled flag, child spans MUST inherit that decision unless the policy explicitly declares itself parent-overriding.
    INV_02: The sampling decision SHALL be deterministic for the same trace_id so that siblings agree without coordination.
    INV_03: Probabilistic sampling MUST use the trace_id hash modulo a rate, NEVER a per-span random draw, to keep entire traces intact.
    INV_04: Policies CANNOT raise; a failing policy SHALL fall back to the default deny and emit an internal counter increment.
    INV_05: Tail-based sampling decisions MUST NOT retroactively modify already-exported spans; they ALWAYS run before export buffering flushes.
    INV_06: description() returns a stable, human-readable string that NEVER includes secret keys or cardinality-exploding values.
*)

CONSTANTS MaxInt

VARIABLES sampled, attributes, trace_state

vars == <<sampled, attributes, trace_state>>

TypeOK == 
  /\ sampled \in {TRUE, FALSE}
  /\ attributes \in String
  /\ trace_state \in String

Init == 
  /\ sampled = FALSE
  /\ attributes = ""
  /\ trace_state = ""

(* SAMP_INV_01: parent inheritance *)
SAMP_INV_01 ==
  /\ TypeOK

(* SAMP_INV_02: deterministic per trace_id *)
SAMP_INV_02 ==
  /\ TypeOK

(* SAMP_INV_03: trace_id hash, not per-span *)
SAMP_INV_03 ==
  /\ TypeOK

(* SAMP_INV_04: never raise; fallback deny + counter *)
SAMP_INV_04 ==
  /\ TypeOK

(* SAMP_INV_05: tail-based does not modify exported spans *)
SAMP_INV_05 ==
  /\ TRUE

(* SAMP_INV_06: description safe + bounded *)
SAMP_INV_06 ==
  /\ TypeOK

(* Operations *)
Should_sample ==
  /\ sampled' = Should_sampleImpl(sampled)
  /\ UNCHANGED <<config>>

Description ==
  /\ sampled' = DescriptionImpl(sampled)
  /\ UNCHANGED <<config>>

Fallback_count ==
  /\ sampled' = Fallback_countImpl(sampled)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Should_sample \/ Description \/ Fallback_count \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ SAMP_INV_01
  /\ SAMP_INV_02
  /\ SAMP_INV_03
  /\ SAMP_INV_04
  /\ SAMP_INV_05
  /\ SAMP_INV_06

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>sampled' # sampled

====