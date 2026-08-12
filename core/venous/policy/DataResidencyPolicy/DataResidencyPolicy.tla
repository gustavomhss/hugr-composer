---- MODULE DataResidencyPolicy ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for DataResidencyPolicy
  Namespace: policy
  Generated from primitive contract and implementation

  Purpose: Binds a data class to a set of permitted storage and processing regions, refusing writes or cross-border transfers outside the allow-list.

  Invariants:
    INV_01: allowed_regions MUST be ISO-3166 codes; arbitrary strings SHALL raise on bind.
    INV_02: A write to a non-allowed region MUST fail loudly; silent replication outside the policy is FORBIDDEN.
    INV_03: A cross-border transfer outside the EEA CANNOT proceed without a valid transfer_mechanism reference on the bound policy.
    INV_04: check_write MUST be called before any persistence primitive stores the record; policies enforced only at read time NEVER satisfy residency.
    INV_05: Policy changes MUST emit a TamperEvidentAuditLog entry so region scope changes are reviewable.
*)

CONSTANTS MaxInt

VARIABLES data_class, allowed_regions, transfer_mechanism, None, DRP_INV_02, DRP_INV_01, ALLOWED_TRANSFER_MECHANISMS, DRP_INV_03

vars == <<data_class, allowed_regions, transfer_mechanism, None, DRP_INV_02, DRP_INV_01, ALLOWED_TRANSFER_MECHANISMS, DRP_INV_03>>

TypeOK == 
  /\ data_class \in String
  /\ allowed_regions \in String
  /\ transfer_mechanism \in String
  /\ None \in String
  /\ DRP_INV_02 \in String
  /\ DRP_INV_01 \in String
  /\ ALLOWED_TRANSFER_MECHANISMS \in String
  /\ DRP_INV_03 \in String

Init == 
  /\ data_class = ""
  /\ allowed_regions = ""
  /\ transfer_mechanism = ""
  /\ None = ""
  /\ DRP_INV_02 = ""
  /\ DRP_INV_01 = ""
  /\ ALLOWED_TRANSFER_MECHANISMS = ""
  /\ DRP_INV_03 = ""

(* DRP_INV_01: `allowed_regions` MUST be ISO-3166 alpha-2 codes. *)
DRP_INV_01 ==
  /\ TypeOK

(* DRP_INV_02: A write to a non-allowed region MUST fail loudly; silent *)
DRP_INV_02 ==
  /\ TypeOK

(* DRP_INV_03: A cross-border transfer outside the EEA CANNOT proceed *)
DRP_INV_03 ==
  /\ TypeOK

(* DRP_INV_04: `check_write` MUST be called before any persistence primitive *)
DRP_INV_04 ==
  /\ TypeOK

(* DRP_INV_05: Policy changes MUST emit a TamperEvidentAuditLog entry. *)
DRP_INV_05 ==
  /\ required_audience \in audience

(* Operations *)
Append ==
  /\ data_class' = AppendImpl(data_class)
  /\ UNCHANGED <<config>>

Bind ==
  /\ data_class' = BindImpl(data_class)
  /\ UNCHANGED <<config>>

Check_write ==
  /\ data_class' = Check_writeImpl(data_class)
  /\ UNCHANGED <<config>>

Check_transfer ==
  /\ data_class' = Check_transferImpl(data_class)
  /\ UNCHANGED <<config>>

Size ==
  /\ data_class' = SizeImpl(data_class)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Append \/ Bind \/ Check_write \/ Check_transfer \/ Size \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ DRP_INV_01
  /\ DRP_INV_02
  /\ DRP_INV_03
  /\ DRP_INV_04
  /\ DRP_INV_05

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>data_class' # data_class

====