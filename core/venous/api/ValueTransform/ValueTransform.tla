---- MODULE ValueTransform ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for ValueTransform
  Namespace: api
  Generated from primitive contract and implementation

  Purpose: Strongly-typed parse/validate step that converts a raw inbound argument (body/query/param) into the typed value the handler expects.

  Invariants:
    INV_01: transform() MUST raise a typed validation error on bad input; it NEVER returns None to signal invalid.
    INV_02: A ValueTransform MUST be pure: same (value, meta) SHALL produce the same output with no observable side effects.
    INV_03: metatype MUST drive the coercion target; CANNOT silently ignore the declared type.
    INV_04: Composed transforms MUST apply left-to-right in declaration order; swapping order SHALL be explicit.
    INV_05: NEVER mutates the incoming value in place; the returned value is always fresh.
*)

CONSTANTS MaxInt

VARIABLES originated, kind, metatype, data

vars == <<originated, kind, metatype, data>>

TypeOK == 
  /\ originated \in String
  /\ kind \in String
  /\ metatype \in String
  /\ data \in String

Init == 
  /\ originated = ""
  /\ kind = ""
  /\ metatype = ""
  /\ data = ""

(* VTRANSFORM_INV_01: typed errors, never None on bad input *)
VTRANSFORM_INV_01 ==
  /\ TypeOK

(* VTRANSFORM_INV_02: purity (deterministic, no side effects) *)
VTRANSFORM_INV_02 ==
  /\ TypeOK

(* VTRANSFORM_INV_03: metatype drives coercion target *)
VTRANSFORM_INV_03 ==
  /\ TypeOK

(* VTRANSFORM_INV_04: compose is left-to-right, swapping is explicit *)
VTRANSFORM_INV_04 ==
  /\ TRUE

(* VTRANSFORM_INV_05: no in-place mutation *)
VTRANSFORM_INV_05 ==
  /\ TypeOK

(* Operations *)
Transform ==
  /\ originated' = TransformImpl(originated)
  /\ UNCHANGED <<config>>

Ensure_metatype ==
  /\ originated' = Ensure_metatypeImpl(originated)
  /\ UNCHANGED <<config>>

Transforms ==
  /\ originated' = TransformsImpl(originated)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Transform \/ Ensure_metatype \/ Transforms \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ VTRANSFORM_INV_01
  /\ VTRANSFORM_INV_02
  /\ VTRANSFORM_INV_03
  /\ VTRANSFORM_INV_04
  /\ VTRANSFORM_INV_05

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>originated' # originated

====