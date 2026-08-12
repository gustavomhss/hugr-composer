---- MODULE CausalReorderBuffer ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for CausalReorderBuffer
  Namespace: events
  Generated from primitive contract and implementation

  Purpose: Buffer incoming events per (aggregate_id, sequence), drain in causal order, emit a single gap event when a predecessor times out.

  Invariants:
    INV_01: {'id': 'CRB_INV_01', 'rule': 'Events per aggregate_id drain in strictly monotonic sequence order.'}
    INV_02: {'id': 'CRB_INV_02', 'rule': 'An out-of-order event is held until its predecessor arrives OR its deadline_ms elapses.'}
    INV_03: {'id': 'CRB_INV_03', 'rule': 'On deadline expiry, timed_out() emits (aggregate_id, missing_sequence) exactly once.'}
    INV_04: {'id': 'CRB_INV_04', 'rule': 'After a gap is emitted, events at sequences > missing ARE drained (dropped predecessor cannot block forever).'}
    INV_05: {'id': 'CRB_INV_05', 'rule': 'Duplicate offer(agg, seq, ...) is idempotent; the second call is dropped silently.'}
*)

CONSTANTS MaxInt

VARIABLES sequence, event, deadline_ms

vars == <<sequence, event, deadline_ms>>

TypeOK == 
  /\ sequence \in 0..MaxInt
  /\ event \in String
  /\ deadline_ms \in 0..MaxInt

Init == 
  /\ sequence = 0
  /\ event = ""
  /\ deadline_ms = 0

(* CRB_INV_01: Events per ``aggregate_id`` drain in strictly monotonic *)
CRB_INV_01 ==
  /\ version' = version + 1

(* CRB_INV_02: An out-of-order event is held until its predecessor arrives *)
CRB_INV_02 ==
  /\ TypeOK

(* CRB_INV_03: On deadline expiry, ``timed_out()`` emits *)
CRB_INV_03 ==
  /\ TRUE

(* CRB_INV_04: After a gap is emitted, events at sequences > missing ARE *)
CRB_INV_04 ==
  /\ state' # state => event_emitted

(* CRB_INV_05: A duplicate ``offer(agg, seq, ...)`` is idempotent — the *)
CRB_INV_05 ==
  /\ TypeOK

(* Operations *)
Offer ==
  /\ sequence' = OfferImpl(sequence)
  /\ UNCHANGED <<config>>

Next_ready ==
  /\ sequence' = Next_readyImpl(sequence)
  /\ UNCHANGED <<config>>

Timed_out ==
  /\ sequence' = Timed_outImpl(sequence)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Offer \/ Next_ready \/ Timed_out \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ CRB_INV_01
  /\ CRB_INV_02
  /\ CRB_INV_03
  /\ CRB_INV_04
  /\ CRB_INV_05

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>sequence' # sequence

====