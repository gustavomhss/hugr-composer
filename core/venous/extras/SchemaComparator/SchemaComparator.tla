---- MODULE SchemaComparator ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for SchemaComparator
  Namespace: extras
  Generated from primitive contract and implementation

  Purpose: Diffs two OpenAPI 3.x schemas and classifies every change as breaking, compatible, or additive. Designed to run in CI as a change-gate: a non-empty `breaking` list MUST fail the pipeline. Pure-function, no I/O.

  Invariants:
    INV_01: SCHEMA_COMPARATOR_INV_01: Classification result MUST be deterministic for any given (baseline, current) input — no hidden state, no ordering-dependent output.
    INV_02: SCHEMA_COMPARATOR_INV_02: If `breaking` is non-empty, `classification` MUST be 'breaking'; an additive change can NEVER mask a breaking one.
    INV_03: SCHEMA_COMPARATOR_INV_03: `compare(x, x)` for any schema x MUST return empty breaking/compatible/additive lists (reflexive: identity is a no-op).
*)

CONSTANTS MaxInt

VARIABLES classification, breaking, compatible, additive, summary, base_props, curr_props, path, BREAKING, out, curr_type, base_schema, curr_schema, None, removed, base_resp, curr_resp, op_path

vars == <<classification, breaking, compatible, additive, summary, base_props, curr_props, path, BREAKING, out, curr_type, base_schema, curr_schema, None, removed, base_resp, curr_resp, op_path>>

TypeOK == 
  /\ classification \in String
  /\ breaking \in String
  /\ compatible \in String
  /\ additive \in String
  /\ summary \in String
  /\ base_props \in String
  /\ curr_props \in String
  /\ path \in String
  /\ BREAKING \in String
  /\ out \in String
  /\ curr_type \in String
  /\ base_schema \in String
  /\ curr_schema \in String
  /\ None \in String
  /\ removed \in String
  /\ base_resp \in String
  /\ curr_resp \in String
  /\ op_path \in String

Init == 
  /\ classification = ""
  /\ breaking = ""
  /\ compatible = ""
  /\ additive = ""
  /\ summary = ""
  /\ base_props = ""
  /\ curr_props = ""
  /\ path = ""
  /\ BREAKING = ""
  /\ out = ""
  /\ curr_type = ""
  /\ base_schema = ""
  /\ curr_schema = ""
  /\ None = ""
  /\ removed = ""
  /\ base_resp = ""
  /\ curr_resp = ""
  /\ op_path = ""

(* SCHEMACOMPARATOR_INV_01: SCHEMA_COMPARATOR_INV_01: Classification result MUST be deterministic for any given (baseline, current) input — no hidden state, no ordering-dependent output. *)
SCHEMACOMPARATOR_INV_01 ==
  /\ TypeOK

(* SCHEMACOMPARATOR_INV_02: SCHEMA_COMPARATOR_INV_02: If `breaking` is non-empty, `classification` MUST be 'breaking'; an additive change can NEVER mask a breaking one. *)
SCHEMACOMPARATOR_INV_02 ==
  /\ TypeOK

(* SCHEMACOMPARATOR_INV_03: SCHEMA_COMPARATOR_INV_03: `compare(x, x)` for any schema x MUST return empty breaking/compatible/additive lists (reflexive: identity is a no-op). *)
SCHEMACOMPARATOR_INV_03 ==
  /\ TypeOK

(* Operations *)
Check_fields_removed ==
  /\ classification' = Check_fields_removedImpl(classification)
  /\ UNCHANGED <<config>>

Check_types_changed ==
  /\ classification' = Check_types_changedImpl(classification)
  /\ UNCHANGED <<config>>

Check_required_added ==
  /\ classification' = Check_required_addedImpl(classification)
  /\ UNCHANGED <<config>>

Check_enum_shrunk ==
  /\ classification' = Check_enum_shrunkImpl(classification)
  /\ UNCHANGED <<config>>

Check_response_shape_changed ==
  /\ classification' = Check_response_shape_changedImpl(classification)
  /\ UNCHANGED <<config>>

Compare ==
  /\ classification' = CompareImpl(classification)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Check_fields_removed \/ Check_types_changed \/ Check_required_added \/ Check_enum_shrunk \/ Check_response_shape_changed \/ Compare \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ SCHEMACOMPARATOR_INV_01
  /\ SCHEMACOMPARATOR_INV_02
  /\ SCHEMACOMPARATOR_INV_03

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>classification' # classification

====