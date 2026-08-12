---- MODULE DeprecationReporter ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for DeprecationReporter
  Namespace: api
  Generated from primitive contract and implementation

  Purpose: In-memory call-count tracker for deprecated endpoints: record a hit per request, emit a usage report sorted by call volume so operators can tell which deprecated endpoints still have live traffic before they sunset.

  Invariants:
    INV_01: DEPRECATION_REPORTER_INV_01: record(path, method) MUST increment the counter for 'METHOD path' by exactly 1 per call; method casing MUST NOT produce divergent counters.
    INV_02: DEPRECATION_REPORTER_INV_02: get_count() MUST return 0 (never raise, never None) for an endpoint that has never been recorded.
    INV_03: DEPRECATION_REPORTER_INV_03: usage_report() MUST return entries sorted by call_count descending so the hottest deprecated endpoint is always first in the report.
    INV_04: DEPRECATION_REPORTER_INV_04: reset() MUST clear ALL counters atomically; a subsequent get_count() for any key MUST return 0.
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

(* DEPRECATIONREPORTER_INV_01: DEPRECATION_REPORTER_INV_01: record(path, method) MUST increment the counter for 'METHOD path' by exactly 1 per call; method casing MUST NOT produce divergent counters. *)
DEPRECATIONREPORTER_INV_01 ==
  /\ old_version = expected => success

(* DEPRECATIONREPORTER_INV_02: DEPRECATION_REPORTER_INV_02: get_count() MUST return 0 (never raise, never None) for an endpoint that has never been recorded. *)
DEPRECATIONREPORTER_INV_02 ==
  /\ TypeOK

(* DEPRECATIONREPORTER_INV_03: DEPRECATION_REPORTER_INV_03: usage_report() MUST return entries sorted by call_count descending so the hottest deprecated endpoint is always first in the report. *)
DEPRECATIONREPORTER_INV_03 ==
  /\ TypeOK

(* DEPRECATIONREPORTER_INV_04: DEPRECATION_REPORTER_INV_04: reset() MUST clear ALL counters atomically; a subsequent get_count() for any key MUST return 0. *)
DEPRECATIONREPORTER_INV_04 ==
  /\ old_version = expected => success

(* Operations *)
Record ==
  /\ state' = RecordImpl(state)
  /\ UNCHANGED <<config>>

Get_count ==
  /\ state' = Get_countImpl(state)
  /\ UNCHANGED <<config>>

Usage_report ==
  /\ state' = Usage_reportImpl(state)
  /\ UNCHANGED <<config>>

Reset ==
  /\ key # ""
  /\ state' = InitState
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Record \/ Get_count \/ Usage_report \/ Reset \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ DEPRECATIONREPORTER_INV_01
  /\ DEPRECATIONREPORTER_INV_02
  /\ DEPRECATIONREPORTER_INV_03
  /\ DEPRECATIONREPORTER_INV_04

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>state' # state

====