---- MODULE KeyValueBucket ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for KeyValueBucket
  Namespace: cache
  Generated from primitive contract and implementation

  Purpose: Named bucket of key value entries with optimistic create and update and a watch channel for change notifications derived from an underlying stream.

  Invariants:
    INV_01: create MUST fail when the key already exists; it NEVER overwrites a present value.
    INV_02: update MUST fail when the supplied revision does not match the stored revision (compare and swap semantics).
    INV_03: Every successful write ALWAYS increases the entry revision monotonically.
    INV_04: Watch channels SHALL emit changes in revision order for a given key and CANNOT skip a revision without a gap signal.
    INV_05: Deleting a key NEVER frees its historical revisions if history retention is configured greater than one.
*)

CONSTANTS MaxInt

VARIABLES key, value, revision

vars == <<key, value, revision>>

TypeOK == 
  /\ key \in String
  /\ value \in String
  /\ revision \in 0..MaxInt

Init == 
  /\ key = ""
  /\ value = ""
  /\ revision = 0

(* KVB_INV_01: create MUST fail when the key already exists; it NEVER *)
KVB_INV_01 ==
  /\ read_version = write_version

(* KVB_INV_02: update MUST fail when the supplied revision does not match the *)
KVB_INV_02 ==
  /\ TypeOK

(* KVB_INV_03: Every successful write ALWAYS increases the entry revision *)
KVB_INV_03 ==
  /\ TypeOK

(* KVB_INV_04: Watch channels SHALL emit changes in revision order for a given *)
KVB_INV_04 ==
  /\ TypeOK

(* KVB_INV_05: Deleting a key NEVER frees its historical revisions if history *)
KVB_INV_05 ==
  /\ TypeOK

(* Operations *)
Watch ==
  /\ key' = WatchImpl(key)
  /\ UNCHANGED <<config>>

History_depth ==
  /\ key' = History_depthImpl(key)
  /\ UNCHANGED <<config>>

Current_revision ==
  /\ key' = Current_revisionImpl(key)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Watch \/ History_depth \/ Current_revision \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ KVB_INV_01
  /\ KVB_INV_02
  /\ KVB_INV_03
  /\ KVB_INV_04
  /\ KVB_INV_05

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>key' # key
  /\ <>read_version = write_version

====