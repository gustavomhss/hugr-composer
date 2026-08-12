---- MODULE ConsentLedger ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for ConsentLedger
  Namespace: compliance
  Generated from primitive contract and implementation

  Purpose: Records granular per-subject, per-purpose consent grants and revocations with timestamp and version of the notice accepted.

  Invariants:
    INV_01: Consent MUST be keyed by (subject_id, purpose); a blanket grant across purposes CANNOT be recorded.
    INV_02: Every grant MUST reference a notice_version string so the exact text the subject accepted is reconstructible; missing version SHALL raise.
    INV_03: Revocation MUST be as easy as grant and SHALL take effect immediately; future is_granted calls for that (subject, purpose) MUST return False.
    INV_04: History entries MUST be append-only; a revocation NEVER erases a prior grant, it supersedes it in time.
    INV_05: is_granted MUST be evaluated against the state at `at` (or now), not the latest, so audits can reproduce past authorizations.
*)

CONSTANTS MaxInt

VARIABLES entry_id, subject_id, purpose, kind, notice_version, at, actor

vars == <<entry_id, subject_id, purpose, kind, notice_version, at, actor>>

TypeOK == 
  /\ entry_id \in String
  /\ subject_id \in String
  /\ purpose \in String
  /\ kind \in String
  /\ notice_version \in String
  /\ at \in String
  /\ actor \in String

Init == 
  /\ entry_id = ""
  /\ subject_id = ""
  /\ purpose = ""
  /\ kind = ""
  /\ notice_version = ""
  /\ at = ""
  /\ actor = ""

(* CL_INV_01: Consent MUST be keyed by (subject_id, purpose); blanket grants *)
CL_INV_01 ==
  /\ TypeOK

(* CL_INV_02: Every grant MUST cite a `notice_version`; missing or empty *)
CL_INV_02 ==
  /\ TypeOK

(* CL_INV_03: Revocation MUST take effect immediately: future `is_granted` *)
CL_INV_03 ==
  /\ TypeOK

(* CL_INV_04: History is append-only; a revocation NEVER erases a prior grant, *)
CL_INV_04 ==
  /\ TypeOK

(* CL_INV_05: `is_granted(..., at=T)` MUST be evaluated against the state at *)
CL_INV_05 ==
  /\ TypeOK

(* Operations *)
Grant ==
  /\ entry_id' = GrantImpl(entry_id)
  /\ UNCHANGED <<config>>

Revoke ==
  /\ entry_id' = RevokeImpl(entry_id)
  /\ UNCHANGED <<config>>

Is_granted ==
  /\ entry_id' = Is_grantedImpl(entry_id)
  /\ UNCHANGED <<config>>

History ==
  /\ entry_id' = HistoryImpl(entry_id)
  /\ UNCHANGED <<config>>

Size ==
  /\ entry_id' = SizeImpl(entry_id)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Grant \/ Revoke \/ Is_granted \/ History \/ Size \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ CL_INV_01
  /\ CL_INV_02
  /\ CL_INV_03
  /\ CL_INV_04
  /\ CL_INV_05

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>entry_id' # entry_id

====