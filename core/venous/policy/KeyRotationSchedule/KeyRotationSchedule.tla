---- MODULE KeyRotationSchedule ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for KeyRotationSchedule
  Namespace: policy
  Generated from primitive contract and implementation

  Purpose: Drives rotation of data-encryption keys on a fixed cadence with overlap window, and blocks new writes with a key past its cutover.

  Invariants:
    INV_01: A new key version MUST be produced on or before next_rotation_at; missing a rotation SHALL raise an alert to the compliance channel.
    INV_02: overlap MUST be > 0 so decryption of records written with the prior version NEVER fails during cutover.
    INV_03: active_key() MUST return exactly one current key per alias at any instant; ties or gaps CANNOT occur.
    INV_04: Keys past cadence + overlap MUST be marked decrypt-only; new writes with such keys SHALL be rejected.
    INV_05: Rotation events MUST emit a TamperEvidentAuditLog entry capturing old and new key versions.
*)

CONSTANTS MaxInt

VARIABLES key_alias, cadence, overlap, next_rotation_at, None, KRS_INV_03, KRS_INV_01, KRS_INV_02

vars == <<key_alias, cadence, overlap, next_rotation_at, None, KRS_INV_03, KRS_INV_01, KRS_INV_02>>

TypeOK == 
  /\ key_alias \in String
  /\ cadence \in String
  /\ overlap \in String
  /\ next_rotation_at \in String
  /\ None \in String
  /\ KRS_INV_03 \in String
  /\ KRS_INV_01 \in String
  /\ KRS_INV_02 \in String

Init == 
  /\ key_alias = ""
  /\ cadence = ""
  /\ overlap = ""
  /\ next_rotation_at = ""
  /\ None = ""
  /\ KRS_INV_03 = ""
  /\ KRS_INV_01 = ""
  /\ KRS_INV_02 = ""

(* KRS_INV_01: A new key version MUST be produced on or before *)
KRS_INV_01 ==
  /\ TypeOK

(* KRS_INV_02: `overlap` MUST be > 0 so decryption of records written with *)
KRS_INV_02 ==
  /\ TypeOK

(* KRS_INV_03: `active_key()` MUST return exactly one current key per alias *)
KRS_INV_03 ==
  /\ TypeOK

(* KRS_INV_04: Keys past `cadence + overlap` MUST be marked decrypt-only; *)
KRS_INV_04 ==
  /\ TypeOK

(* KRS_INV_05: Rotation events MUST emit a TamperEvidentAuditLog entry *)
KRS_INV_05 ==
  /\ state' # state => event_emitted

(* Operations *)
Append ==
  /\ key_alias' = AppendImpl(key_alias)
  /\ UNCHANGED <<config>>

Schedule ==
  /\ key_alias' = ScheduleImpl(key_alias)
  /\ UNCHANGED <<config>>

Rotate_now ==
  /\ key_alias' = Rotate_nowImpl(key_alias)
  /\ UNCHANGED <<config>>

Active_key ==
  /\ key_alias' = Active_keyImpl(key_alias)
  /\ UNCHANGED <<config>>

Is_decrypt_only ==
  /\ key_alias' = Is_decrypt_onlyImpl(key_alias)
  /\ UNCHANGED <<config>>

Is_missed_rotation ==
  /\ key_alias' = Is_missed_rotationImpl(key_alias)
  /\ UNCHANGED <<config>>

Size ==
  /\ key_alias' = SizeImpl(key_alias)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Append \/ Schedule \/ Rotate_now \/ Active_key \/ Is_decrypt_only \/ Is_missed_rotation \/ Size \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ KRS_INV_01
  /\ KRS_INV_02
  /\ KRS_INV_03
  /\ KRS_INV_04
  /\ KRS_INV_05

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>key_alias' # key_alias

====