------------------------- MODULE PiiClassification -------------------------
(***************************************************************************)
(* TLA+ spec for PiiClassification state machine.                          *)
(*                                                                         *)
(* Variables:                                                              *)
(*   annotations: function from Fields -> Classes \cup {"unset"}           *)
(*   leaks:       integer count of leak-recordings (bounded)               *)
(*                                                                         *)
(* Safety invariants:                                                      *)
(*   PIC_INV_01 — annotations map is well-typed; every key has a class or  *)
(*                 the sentinel "unset".                                   *)
(*   PIC_INV_05 — leaks is monotonic and bounded.                          *)
(***************************************************************************)
EXTENDS Naturals, FiniteSets

CONSTANTS MaxLeaks

Fields == {"f1", "f2"}
Classes == {"public", "pii", "phi"}

VARIABLES annotations, leaks

vars == <<annotations, leaks>>

TypeOK ==
  /\ annotations \in [Fields -> Classes \union {"unset"}]
  /\ leaks \in 0..MaxLeaks

Init ==
  /\ annotations = [f \in Fields |-> "unset"]
  /\ leaks = 0

Register(f, c) ==
  /\ annotations' = [annotations EXCEPT ![f] = c]
  /\ leaks' = leaks

RecordLeak ==
  /\ leaks < MaxLeaks
  /\ annotations' = annotations
  /\ leaks' = leaks + 1

Next ==
  \/ \E f \in Fields, c \in Classes: Register(f, c)
  \/ RecordLeak

Safety_AnnotationsWellTyped ==
  \A f \in Fields: annotations[f] \in Classes \union {"unset"}

Safety_LeaksBounded == leaks \in 0..MaxLeaks

Spec == Init /\ [][Next]_vars

THEOREM Spec => [](TypeOK /\ Safety_AnnotationsWellTyped /\ Safety_LeaksBounded)
=============================================================================
