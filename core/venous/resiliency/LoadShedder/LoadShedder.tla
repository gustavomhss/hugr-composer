---- MODULE LoadShedder ----
EXTENDS Naturals, FiniteSets

CONSTANTS MaxTicks
(* MaxTicks bounds the clock to keep the state space finite. *)

ASSUME MaxTicks \in Nat /\ MaxTicks >= 2

(* Priority classes, ordered by rank (0 = most critical). *)
Priorities == {"critical", "normal", "sheddable_plus", "sheddable"}

Rank(p) ==
    IF p = "critical" THEN 0
    ELSE IF p = "normal" THEN 1
    ELSE IF p = "sheddable_plus" THEN 2
    ELSE 3

(* Pressure regimes — discrete abstraction of the continuous signal. *)
PressureRegimes == {"healthy", "warm", "heavy", "extreme"}

DesiredCutoff(reg) ==
    IF reg = "extreme" THEN "critical"
    ELSE IF reg = "heavy" THEN "normal"
    ELSE IF reg = "warm" THEN "sheddable_plus"
    ELSE "sheddable"

Decisions == {"none", "admit", "reject"}

VARIABLES cutoff, regime, clock, last_change, last_priority, last_decision

TypeOK ==
    /\ cutoff \in Priorities
    /\ regime \in PressureRegimes
    /\ clock \in 0..MaxTicks
    /\ last_change \in 0..MaxTicks
    /\ last_priority \in Priorities \cup {"none"}
    /\ last_decision \in Decisions

Init ==
    /\ cutoff = "sheddable"
    /\ regime = "healthy"
    /\ clock = 0
    /\ last_change = 0
    /\ last_priority = "none"
    /\ last_decision = "none"

(* Observe one request at priority p against the current cutoff. *)
Observe(p) ==
    /\ clock < MaxTicks
    /\ clock' = clock + 1
    /\ last_priority' = p
    /\ IF Rank(p) <= Rank(cutoff)
           THEN last_decision' = "admit"
           ELSE last_decision' = "reject"
    /\ UNCHANGED <<cutoff, regime, last_change>>

(* Non-deterministic environment shift. Resets last_decision so the safety
   invariant PriorityOrder is evaluated only against the current cutoff. *)
ShiftRegime(r) ==
    /\ r \in PressureRegimes
    /\ regime' = r
    /\ last_priority' = "none"
    /\ last_decision' = "none"
    /\ UNCHANGED <<cutoff, clock, last_change>>

(* Apply the desired cutoff IF the control interval has elapsed (>= 1 tick).
   Models LSH-INV-03: cutoff changes at most once per control interval.
   Resets last_decision because the decision was made under the previous cutoff. *)
ApplyCutoff ==
    /\ cutoff # DesiredCutoff(regime)
    /\ clock - last_change >= 1
    /\ cutoff' = DesiredCutoff(regime)
    /\ last_change' = clock
    /\ last_priority' = "none"
    /\ last_decision' = "none"
    /\ UNCHANGED <<regime, clock>>

Next ==
    \/ \E p \in Priorities: Observe(p)
    \/ \E r \in PressureRegimes: ShiftRegime(r)
    \/ ApplyCutoff

Spec == Init /\ [][Next]_<<cutoff, regime, clock, last_change, last_priority, last_decision>>

(* ------------------------------------------------------------------- *)
(* SAFETY INVARIANTS                                                    *)
(* ------------------------------------------------------------------- *)

(* LSH-INV-01: priority ordering — whenever a request was admitted, its rank
   is <= the cutoff at the time of decision; symmetrically, a rejected
   request has rank strictly greater than the cutoff. *)
PriorityOrder ==
    /\ (last_decision = "admit" /\ last_priority # "none")
        => Rank(last_priority) <= Rank(cutoff)
    /\ (last_decision = "reject" /\ last_priority # "none")
        => Rank(last_priority) > Rank(cutoff)

(* LSH-INV-03: hysteresis bookkeeping is never ahead of the clock. *)
ChangeTimeBounded ==
    last_change <= clock

(* LSH-INV-05: cutoff is always a well-defined published priority. *)
CutoffBounded ==
    cutoff \in Priorities

====
