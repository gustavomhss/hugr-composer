----------------------------- MODULE LegalHold -----------------------------
(***************************************************************************)
(* TLA+ spec for LegalHold registry.                                        *)
(*                                                                         *)
(* Holds: set of currently-open hold ids.                                   *)
(* Released: set of released hold ids (monotonically grows).                *)
(*                                                                         *)
(* Safety:                                                                  *)
(*   LH_INV_01 — Released ⊆ Holds (cannot release a hold that never existed)*)
(*   LH_INV_03 — Holds \ Released is the set of active holds; once released,*)
(*               a hold stays released (no silent revival).                 *)
(***************************************************************************)
EXTENDS Naturals, FiniteSets

CONSTANTS HoldIds

VARIABLES Holds, Released

vars == <<Holds, Released>>

TypeOK ==
  /\ Holds \subseteq HoldIds
  /\ Released \subseteq HoldIds

Init ==
  /\ Holds = {}
  /\ Released = {}

Open(h) ==
  /\ h \in HoldIds
  /\ h \notin Holds \ Released
  /\ Holds' = Holds \union {h}
  /\ Released' = Released

Release(h) ==
  /\ h \in Holds
  /\ h \notin Released
  /\ Released' = Released \union {h}
  /\ Holds' = Holds

Next ==
  \/ \E h \in HoldIds: Open(h)
  \/ \E h \in HoldIds: Release(h)

Safety_ReleasedWithinHolds == Released \subseteq Holds

(* Once released, a hold stays released (Released grows monotonically). *)
Safety_ReleasedMonotonic == Released \subseteq Released'

Spec == Init /\ [][Next]_vars

THEOREM Spec => [](TypeOK /\ Safety_ReleasedWithinHolds)
=============================================================================
