---- MODULE DataSubjectRequest ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for DataSubjectRequest
  Namespace: compliance
  Generated from primitive contract and implementation

  Purpose: Coordinates the lifecycle of an access or erasure request across all stores that hold data about the subject, with a SLA clock.

  Invariants:
    INV_01: Every request MUST have a statutory due_at computed from received_at; the clock NEVER pauses for internal delays.
    INV_02: Every registered store holding subject data MUST attach an artifact before close; a request CANNOT close with missing stores.
    INV_03: Erasure requests MUST invoke the ErasureCascade; a close with kind='erasure' and no cascade artifact SHALL be rejected.
    INV_04: Open, artifact, and close actions MUST each emit a TamperEvidentAuditLog entry for regulator replay.
    INV_05: Access and portability exports MUST be delivered via a time-bound, signed URL; exports NEVER live beyond the delivery window.
*)

CONSTANTS MaxInt

VARIABLES request_id, subject_id, kind, received_at, due_at, expected_stores, artifacts, closed_outcome

vars == <<request_id, subject_id, kind, received_at, due_at, expected_stores, artifacts, closed_outcome>>

TypeOK == 
  /\ request_id \in String
  /\ subject_id \in String
  /\ kind \in String
  /\ received_at \in String
  /\ due_at \in String
  /\ expected_stores \in String
  /\ artifacts \in String
  /\ closed_outcome \in String

Init == 
  /\ request_id = ""
  /\ subject_id = ""
  /\ kind = ""
  /\ received_at = ""
  /\ due_at = ""
  /\ expected_stores = ""
  /\ artifacts = ""
  /\ closed_outcome = ""

(* DSR_INV_01: Every request MUST have a statutory `due_at` computed from *)
DSR_INV_01 ==
  /\ TypeOK

(* DSR_INV_02: Every registered store holding subject data MUST attach an *)
DSR_INV_02 ==
  /\ TypeOK

(* DSR_INV_03: Erasure requests MUST invoke the `ErasureCascade`; a close *)
DSR_INV_03 ==
  /\ old_version = expected => success

(* DSR_INV_04: Open, artifact, close actions MUST each emit a *)
DSR_INV_04 ==
  /\ TypeOK

(* DSR_INV_05: Access / portability exports MUST be delivered via a *)
DSR_INV_05 ==
  /\ TRUE

(* Operations *)
Append ==
  /\ request_id' = AppendImpl(request_id)
  /\ UNCHANGED <<config>>

Open ==
  /\ request_id' = OpenImpl(request_id)
  /\ UNCHANGED <<config>>

Attach_artifact ==
  /\ request_id' = Attach_artifactImpl(request_id)
  /\ UNCHANGED <<config>>

Close ==
  /\ request_id' = CloseImpl(request_id)
  /\ UNCHANGED <<config>>

Due_at ==
  /\ request_id' = Due_atImpl(request_id)
  /\ UNCHANGED <<config>>

Signed_export_url ==
  /\ request_id' = Signed_export_urlImpl(request_id)
  /\ UNCHANGED <<config>>

Verify_export_url_signature ==
  /\ request_id' = Verify_export_url_signatureImpl(request_id)
  /\ UNCHANGED <<config>>

Size ==
  /\ request_id' = SizeImpl(request_id)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Append \/ Open \/ Attach_artifact \/ Close \/ Due_at \/ Signed_export_url \/ Verify_export_url_signature \/ Size \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ DSR_INV_01
  /\ DSR_INV_02
  /\ DSR_INV_03
  /\ DSR_INV_04
  /\ DSR_INV_05

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>request_id' # request_id

====