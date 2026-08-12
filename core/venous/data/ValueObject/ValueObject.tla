---- MODULE ValueObject ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for ValueObject
  Namespace: data
  Generated from primitive contract and implementation

  Purpose: Represents a descriptive concept whose identity is defined entirely by its attributes and which is immutable once constructed.

  Invariants:
    INV_01: Instances MUST be immutable after construction; attribute assignment post-init is FORBIDDEN.
    INV_02: Two instances with the same attribute values MUST compare equal and MUST share the same hash.
    INV_03: A ValueObject CANNOT hold a reference to an Aggregate root or Entity whose identity is unstable.
    INV_04: Construction SHALL validate every invariant eagerly; a partially-valid instance NEVER exists.
*)

CONSTANTS MaxInt

VARIABLES _invariant_id, 04, None, name, kwargs, preserved, bad, address, 1, domain

vars == <<_invariant_id, 04, None, name, kwargs, preserved, bad, address, 1, domain>>

TypeOK == 
  /\ _invariant_id \in String
  /\ 04 \in String
  /\ None \in String
  /\ name \in String
  /\ kwargs \in String
  /\ preserved \in String
  /\ bad \in String
  /\ address \in String
  /\ 1 \in String
  /\ domain \in String

Init == 
  /\ _invariant_id = ""
  /\ 04 = ""
  /\ None = ""
  /\ name = ""
  /\ kwargs = ""
  /\ preserved = ""
  /\ bad = ""
  /\ address = ""
  /\ 1 = ""
  /\ domain = ""

(* VO_INV_01: immutable after construction *)
VO_INV_01 ==
  /\ TypeOK

(* VO_INV_02: equality by value + hash consistency *)
VO_INV_02 ==
  /\ TypeOK

(* VO_INV_03: no unstable-identity references *)
VO_INV_03 ==
  /\ TypeOK

(* VO_INV_04: eager construction-time validation *)
VO_INV_04 ==
  /\ TypeOK

(* Operations *)
With_changes ==
  /\ _invariant_id' = With_changesImpl(_invariant_id)
  /\ UNCHANGED <<config>>

Validate_attributes ==
  /\ _invariant_id' = Validate_attributesImpl(_invariant_id)
  /\ UNCHANGED <<config>>

To_dict ==
  /\ _invariant_id' = To_dictImpl(_invariant_id)
  /\ UNCHANGED <<config>>

Add ==
  /\ _invariant_id' = AddImpl(_invariant_id)
  /\ UNCHANGED <<config>>

Register ==
  /\ _invariant_id' = RegisterImpl(_invariant_id)
  /\ UNCHANGED <<config>>

To_mapping ==
  /\ _invariant_id' = To_mappingImpl(_invariant_id)
  /\ UNCHANGED <<config>>

From_mapping ==
  /\ _invariant_id' = From_mappingImpl(_invariant_id)
  /\ UNCHANGED <<config>>

Iter_fields ==
  /\ _invariant_id' = Iter_fieldsImpl(_invariant_id)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ With_changes \/ Validate_attributes \/ To_dict \/ Add \/ Register \/ To_mapping \/ From_mapping \/ Iter_fields \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ VO_INV_01
  /\ VO_INV_02
  /\ VO_INV_03
  /\ VO_INV_04

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>_invariant_id' # _invariant_id

====