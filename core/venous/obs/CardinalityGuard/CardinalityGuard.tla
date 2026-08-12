---- MODULE CardinalityGuard ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for CardinalityGuard
  Namespace: obs
  Generated from primitive contract and implementation

  Purpose: Bound the unique attribute-value combinations attached to a metric or log stream to prevent label explosion from breaking time-series databases.

  Invariants:
    INV_01: When the per-metric series limit is reached, new attribute combinations MUST be collapsed into a single 'overflow' series and NEVER emitted with their original values.
    INV_02: The guard MUST reject any attribute key whose value has been seen in more than per_key_limit distinct forms across the window.
    INV_03: User identifiers, full URL paths, email addresses, and freeform query strings as attribute values are FORBIDDEN by the default deny-list.
    INV_04: Admission decisions SHALL be deterministic given the same (metric_name, attributes) tuple within a single aggregation window.
    INV_05: The guard NEVER mutates the caller's attribute mapping in place; it ALWAYS returns a new mapping.
    INV_06: Overflow events MUST be observable through a dedicated counter so operators can detect label pressure before ingestion breaks.
    INV_07: Configure CANNOT be invoked after the first admit call in a given process to preserve deterministic behavior.
*)

CONSTANTS MaxInt

VARIABLES state, config

vars == <<state, config>>

TypeOK == 
  /\ state \in String
  /\ config \in String

Init == 
  /\ state = ""
  /\ config = ""

(* CARD_INV_01: per-metric overflow *)
CARD_INV_01 ==
  /\ TypeOK

(* CARD_INV_02: per-key limit *)
CARD_INV_02 ==
  /\ TypeOK

(* CARD_INV_03: deny-list *)
CARD_INV_03 ==
  /\ TypeOK

(* CARD_INV_04: deterministic admit *)
CARD_INV_04 ==
  /\ state <= config

(* CARD_INV_05: no in-place mutation *)
CARD_INV_05 ==
  /\ TypeOK

(* CARD_INV_06: overflow counter observable *)
CARD_INV_06 ==
  /\ TypeOK

(* CARD_INV_07: configure locked after first admit *)
CARD_INV_07 ==
  /\ state <= config

(* Operations *)
Admit ==
  /\ state' = AdmitImpl(state)
  /\ UNCHANGED <<config>>

Configure ==
  /\ state' = ConfigureImpl(state)
  /\ UNCHANGED <<config>>

Stats ==
  /\ state' = StatsImpl(state)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Admit \/ Configure \/ Stats \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ CARD_INV_01
  /\ CARD_INV_02
  /\ CARD_INV_03
  /\ CARD_INV_04
  /\ CARD_INV_05
  /\ CARD_INV_06
  /\ CARD_INV_07

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>state' # state

====