---- MODULE Bulkhead ----
EXTENDS Naturals, FiniteSets

CONSTANTS Capacity, Callers
(* Capacity = max_concurrent_calls per partition;
   Callers  = set of distinct caller identities. *)

ASSUME Capacity \in Nat /\ Capacity >= 1
ASSUME IsFiniteSet(Callers)

VARIABLES in_flight, admitted, rejected, holding

TypeOK ==
    /\ in_flight \in 0..Capacity
    /\ admitted \subseteq Callers
    /\ rejected \subseteq Callers
    /\ holding \subseteq Callers

Init ==
    /\ in_flight = 0
    /\ admitted = {}
    /\ rejected = {}
    /\ holding = {}

(* A caller c acquires a permit when capacity is not yet saturated. *)
Acquire(c) ==
    /\ c \in Callers
    /\ c \notin holding
    /\ c \notin rejected
    /\ in_flight < Capacity
    /\ in_flight' = in_flight + 1
    /\ holding' = holding \cup {c}
    /\ admitted' = admitted \cup {c}
    /\ UNCHANGED <<rejected>>

(* A caller c is rejected when capacity is saturated. *)
Reject(c) ==
    /\ c \in Callers
    /\ c \notin holding
    /\ c \notin admitted
    /\ c \notin rejected
    /\ in_flight = Capacity
    /\ rejected' = rejected \cup {c}
    /\ UNCHANGED <<in_flight, admitted, holding>>

(* A caller c releases its permit on completion / failure. *)
Release(c) ==
    /\ c \in holding
    /\ in_flight > 0
    /\ in_flight' = in_flight - 1
    /\ holding' = holding \ {c}
    /\ UNCHANGED <<admitted, rejected>>

Stutter ==
    UNCHANGED <<in_flight, admitted, rejected, holding>>

Next ==
    \/ \E c \in Callers: Acquire(c)
    \/ \E c \in Callers: Reject(c)
    \/ \E c \in Callers: Release(c)
    \/ Stutter

Spec == Init /\ [][Next]_<<in_flight, admitted, rejected, holding>>

(* --------------------------------------------------------------- *)
(* SAFETY INVARIANTS                                                *)
(* --------------------------------------------------------------- *)

(* BH_INV_01: in_flight NEVER exceeds capacity at any observable step. *)
CapacityCeiling ==
    /\ in_flight >= 0
    /\ in_flight <= Capacity

(* BH_INV_01 (alt): the number of holders equals in_flight. *)
HoldingEqualsInFlight ==
    Cardinality(holding) = in_flight

(* BH_INV_02: a caller rejected for lack of a permit is NOT admitted. *)
RejectionStaysRejected ==
    rejected \cap admitted = {}

(* BH_INV_03: a rejected caller NEVER becomes a holder. *)
RejectionNeverHolds ==
    rejected \cap holding = {}

====
