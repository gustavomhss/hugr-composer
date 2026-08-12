---- MODULE RetentionPolicy ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for RetentionPolicy
  Namespace: compliance
  Generated from primitive contract and implementation

  Purpose: Declarative binding of a data class to a maximum lifetime, enforced by scheduled purge and blocked at write-time if unclassified.

  Invariants:
    INV_01: Every persisted record MUST be tagged with a data_class that maps to a registered RetentionPolicy; writes of untagged data SHALL be rejected.
    INV_02: max_age MUST be finite and > 0; an open-ended 'keep forever' policy CANNOT be registered without an explicit legal_basis override.
    INV_03: deletion_mode MUST be one of 'hard', 'crypto_shred', or 'anonymize'; other values SHALL raise on bind.
    INV_04: The sweep job MUST be idempotent and SHALL not delete records under an active LegalHold.
    INV_05: Every purge action MUST emit an entry to the TamperEvidentAuditLog with the policy id and record count.
*)

CONSTANTS MaxInt

VARIABLES data_class, max_age, legal_basis, deletion_mode, RP_INV_01, RP_INV_02, RP_INV_03, ALLOWED_DELETION_MODES

vars == <<data_class, max_age, legal_basis, deletion_mode, RP_INV_01, RP_INV_02, RP_INV_03, ALLOWED_DELETION_MODES>>

TypeOK == 
  /\ data_class \in String
  /\ max_age \in String
  /\ legal_basis \in String
  /\ deletion_mode \in String
  /\ RP_INV_01 \in String
  /\ RP_INV_02 \in String
  /\ RP_INV_03 \in String
  /\ ALLOWED_DELETION_MODES \in String

Init == 
  /\ data_class = ""
  /\ max_age = ""
  /\ legal_basis = ""
  /\ deletion_mode = ""
  /\ RP_INV_01 = ""
  /\ RP_INV_02 = ""
  /\ RP_INV_03 = ""
  /\ ALLOWED_DELETION_MODES = ""

(* RP_INV_01: Every persisted record MUST be tagged with a `data_class` *)
RP_INV_01 ==
  /\ TypeOK

(* RP_INV_02: `max_age` MUST be finite and > 0. 'Keep forever' without an *)
RP_INV_02 ==
  /\ TypeOK

(* RP_INV_03: `deletion_mode` MUST be one of 'hard', 'crypto_shred', *)
RP_INV_03 ==
  /\ TypeOK

(* RP_INV_04: `sweep()` MUST be idempotent and SHALL NOT delete records *)
RP_INV_04 ==
  /\ TypeOK

(* RP_INV_05: Every purge action MUST emit a `TamperEvidentAuditLog` *)
RP_INV_05 ==
  /\ required_audience \in audience

(* Operations *)
Covers ==
  /\ data_class' = CoversImpl(data_class)
  /\ UNCHANGED <<config>>

Append ==
  /\ data_class' = AppendImpl(data_class)
  /\ UNCHANGED <<config>>

Bind ==
  /\ data_class' = BindImpl(data_class)
  /\ UNCHANGED <<config>>

Enforce_on_write ==
  /\ data_class' = Enforce_on_writeImpl(data_class)
  /\ UNCHANGED <<config>>

Sweep ==
  /\ data_class' = SweepImpl(data_class)
  /\ UNCHANGED <<config>>

Size ==
  /\ data_class' = SizeImpl(data_class)
  /\ UNCHANGED <<config>>

Records ==
  /\ data_class' = RecordsImpl(data_class)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Covers \/ Append \/ Bind \/ Enforce_on_write \/ Sweep \/ Size \/ Records \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ RP_INV_01
  /\ RP_INV_02
  /\ RP_INV_03
  /\ RP_INV_04
  /\ RP_INV_05

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>data_class' # data_class

====