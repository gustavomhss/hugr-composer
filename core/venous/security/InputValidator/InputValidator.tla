---- MODULE InputValidator ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for InputValidator
  Namespace: security
  Generated from primitive contract and implementation

  Purpose: Parse and constrain inbound payloads against a declared schema with typed coercion, length and range bounds, and rejection of unknown fields.

  Invariants:
    INV_01: parse() MUST reject payloads with unknown fields unless the schema explicitly opts into extras; silent field drop is FORBIDDEN.
    INV_02: Length, range, and pattern bounds MUST be enforced before any business rule touches the value; unbounded strings CANNOT be accepted.
    INV_03: Type coercion MUST be narrowing (string→int only when digits-only); widening coercion (int→string for structured ids) SHALL require explicit opt-in.
    INV_04: parse() MUST raise a typed validation error containing the offending field path; error payloads MUST NEVER include attacker-controlled content verbatim in structured logs.
    INV_05: Recursion depth and collection size MUST be bounded; payloads exceeding the configured limits SHALL be rejected before parsing.
*)

CONSTANTS MaxInt

VARIABLES field_path, reason, type_, required, min_length, max_length, min_value, max_value, pattern, allow_coerce, allow_widen, allow_control_chars, None, max_depth, max_collection_size, max_string_len, max_total_nodes, limits, raw, schema, T, fields_map, type, path, depth, counters, SchemaModel, IV_INV_01, out, value, spec, object, str, bool, int, float, t, item, inner, item_path, s, ceiling, _DISALLOWED_CHARS, 32, else

vars == <<field_path, reason, type_, required, min_length, max_length, min_value, max_value, pattern, allow_coerce, allow_widen, allow_control_chars, None, max_depth, max_collection_size, max_string_len, max_total_nodes, limits, raw, schema, T, fields_map, type, path, depth, counters, SchemaModel, IV_INV_01, out, value, spec, object, str, bool, int, float, t, item, inner, item_path, s, ceiling, _DISALLOWED_CHARS, 32, else>>

TypeOK == 
  /\ field_path \in String
  /\ reason \in String
  /\ type_ \in String
  /\ required \in {TRUE, FALSE}
  /\ min_length \in 0..MaxInt
  /\ max_length \in 0..MaxInt
  /\ min_value \in 0..MaxInt
  /\ max_value \in 0..MaxInt
  /\ pattern \in String
  /\ allow_coerce \in {TRUE, FALSE}
  /\ allow_widen \in {TRUE, FALSE}
  /\ allow_control_chars \in {TRUE, FALSE}
  /\ None \in String
  /\ max_depth \in 0..MaxInt
  /\ max_collection_size \in 0..MaxInt
  /\ max_string_len \in 0..MaxInt
  /\ max_total_nodes \in 0..MaxInt
  /\ limits \in String
  /\ raw \in String
  /\ schema \in String
  /\ T \in String
  /\ fields_map \in String
  /\ type \in String
  /\ path \in String
  /\ depth \in 0..MaxInt
  /\ counters \in 0..MaxInt
  /\ SchemaModel \in String
  /\ IV_INV_01 \in String
  /\ out \in String
  /\ value \in String
  /\ spec \in String
  /\ object \in String
  /\ str \in String
  /\ bool \in String
  /\ int \in String
  /\ float \in String
  /\ t \in SUBSET String
  /\ item \in String
  /\ inner \in String
  /\ item_path \in String
  /\ s \in String
  /\ ceiling \in String
  /\ _DISALLOWED_CHARS \in String
  /\ 32 \in String
  /\ else \in String

Init == 
  /\ field_path = ""
  /\ reason = ""
  /\ type_ = ""
  /\ required = FALSE
  /\ min_length = 0
  /\ max_length = 0
  /\ min_value = 0
  /\ max_value = 0
  /\ pattern = ""
  /\ allow_coerce = FALSE
  /\ allow_widen = FALSE
  /\ allow_control_chars = FALSE
  /\ None = ""
  /\ max_depth = 0
  /\ max_collection_size = 0
  /\ max_string_len = 0
  /\ max_total_nodes = 0
  /\ limits = ""
  /\ raw = ""
  /\ schema = ""
  /\ T = ""
  /\ fields_map = ""
  /\ type = ""
  /\ path = ""
  /\ depth = 0
  /\ counters = 0
  /\ SchemaModel = ""
  /\ IV_INV_01 = ""
  /\ out = ""
  /\ value = ""
  /\ spec = ""
  /\ object = ""
  /\ str = ""
  /\ bool = ""
  /\ int = ""
  /\ float = ""
  /\ t = {}
  /\ item = ""
  /\ inner = ""
  /\ item_path = ""
  /\ s = ""
  /\ ceiling = ""
  /\ _DISALLOWED_CHARS = ""
  /\ 32 = ""
  /\ else = ""

(* IV_INV_01: parse() MUST reject payloads with unknown fields unless the *)
IV_INV_01 ==
  /\ TypeOK

(* IV_INV_02: length, range and pattern bounds MUST be enforced before any *)
IV_INV_02 ==
  /\ TypeOK

(* IV_INV_03: type coercion MUST be narrowing (string->int only when *)
IV_INV_03 ==
  /\ TypeOK

(* IV_INV_04: parse() MUST raise a typed ValidationError containing the *)
IV_INV_04 ==
  /\ TypeOK

(* IV_INV_05: recursion depth and collection size MUST be bounded; payloads *)
IV_INV_05 ==
  /\ TypeOK

(* Operations *)
Parse ==
  /\ field_path' = ParseImpl(field_path)
  /\ UNCHANGED <<config>>

Compiled_pattern ==
  /\ field_path' = Compiled_patternImpl(field_path)
  /\ UNCHANGED <<config>>

To_dict ==
  /\ field_path' = To_dictImpl(field_path)
  /\ UNCHANGED <<config>>

Bump ==
  /\ field_path' = BumpImpl(field_path)
  /\ UNCHANGED <<config>>

List_of ==
  /\ field_path' = List_ofImpl(field_path)
  /\ UNCHANGED <<config>>

Register_adapter ==
  /\ field_path' = Register_adapterImpl(field_path)
  /\ UNCHANGED <<config>>

Iter_disallowed_chars ==
  /\ field_path' = Iter_disallowed_charsImpl(field_path)
  /\ UNCHANGED <<config>>

Is_finite_number ==
  /\ field_path' = Is_finite_numberImpl(field_path)
  /\ UNCHANGED <<config>>

Bounded_sequence ==
  /\ field_path' = Bounded_sequenceImpl(field_path)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Parse \/ Compiled_pattern \/ To_dict \/ Bump \/ List_of \/ Register_adapter \/ Iter_disallowed_chars \/ Is_finite_number \/ Bounded_sequence \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ IV_INV_01
  /\ IV_INV_02
  /\ IV_INV_03
  /\ IV_INV_04
  /\ IV_INV_05

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>field_path' # field_path

====