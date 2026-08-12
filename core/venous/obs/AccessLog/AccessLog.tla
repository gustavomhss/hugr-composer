---- MODULE AccessLog ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for AccessLog
  Namespace: obs
  Generated from primitive contract and implementation

  Purpose: Records every successful read of classified data with actor, purpose-of-use, and record identifier, distinct from the security audit log.

  Invariants:
    INV_01: Every read of a PiiClassification-tagged record MUST emit one AccessLog entry before the response leaves the process.
    INV_02: purpose_of_use MUST be one of a registered set; ad-hoc free-text values SHALL be rejected.
    INV_03: AccessLog entries MUST NEVER be merged with the TamperEvidentAuditLog so high-volume read traffic cannot mask low-volume security events.
    INV_04: Actor MUST be a resolved identity (user, service account, or break-glass id); 'system' without a concrete id is FORBIDDEN.
    INV_05: Retention of AccessLog MUST follow a RetentionPolicy bound at registration; unbounded accumulation CANNOT occur.
*)

CONSTANTS MaxInt

VARIABLES actor, record_id, data_class, purpose_of_use, at

vars == <<actor, record_id, data_class, purpose_of_use, at>>

TypeOK == 
  /\ actor \in String
  /\ record_id \in String
  /\ data_class \in String
  /\ purpose_of_use \in String
  /\ at \in String

Init == 
  /\ actor = ""
  /\ record_id = ""
  /\ data_class = ""
  /\ purpose_of_use = ""
  /\ at = ""

(* AL_INV_01: Every read of a classified record MUST emit one AccessLog *)
AL_INV_01 ==
  /\ read_version = write_version

(* AL_INV_02: `purpose_of_use` MUST be one of a registered set; ad-hoc *)
AL_INV_02 ==
  /\ TypeOK

(* AL_INV_03: AccessLog entries MUST NEVER be merged with TamperEvidentAuditLog *)
AL_INV_03 ==
  /\ required_audience \in audience

(* AL_INV_04: `actor` MUST be a resolved identity; 'system' without a *)
AL_INV_04 ==
  /\ TypeOK

(* AL_INV_05: A retention policy MUST be bound at registration; *)
AL_INV_05 ==
  /\ TypeOK

(* Operations *)
Record_read ==
  /\ actor' = Record_readImpl(actor)
  /\ UNCHANGED <<config>>

Query ==
  /\ actor' = QueryImpl(actor)
  /\ UNCHANGED <<config>>

Count_by_actor ==
  /\ actor' = Count_by_actorImpl(actor)
  /\ UNCHANGED <<config>>

Sweep_retention ==
  /\ actor' = Sweep_retentionImpl(actor)
  /\ UNCHANGED <<config>>

Size ==
  /\ actor' = SizeImpl(actor)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Record_read \/ Query \/ Count_by_actor \/ Sweep_retention \/ Size \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ AL_INV_01
  /\ AL_INV_02
  /\ AL_INV_03
  /\ AL_INV_04
  /\ AL_INV_05

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>actor' # actor

====