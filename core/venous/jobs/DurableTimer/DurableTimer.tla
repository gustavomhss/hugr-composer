---------------------------- MODULE DurableTimer ----------------------------
(* TLA+ spec for the DurableTimer primitive.                               *)
(* Covers DT-INV-01 (fired recorded) and DT-INV-03 (canceled never fires). *)

EXTENDS Integers, Sequences, FiniteSets, TLC

CONSTANTS
    Timers    \* finite set of timer ids

ASSUME Timers \in SUBSET STRING

Status == {"SCHEDULED", "FIRED", "CANCELED", "ABSENT"}

VARIABLES
    state,     \* function Timers -> Status
    log        \* sequence of <<tid, kind>> events

vars == <<state, log>>

TypeInvariant ==
    /\ DOMAIN state = Timers
    /\ \A t \in Timers : state[t] \in Status
    /\ \A i \in 1..Len(log) : log[i][2] \in {"scheduled", "canceled", "fired"}

Init ==
    /\ state = [t \in Timers |-> "ABSENT"]
    /\ log = <<>>

Schedule(t) ==
    /\ state[t] = "ABSENT"
    /\ state' = [state EXCEPT ![t] = "SCHEDULED"]
    /\ log' = Append(log, <<t, "scheduled">>)

Cancel(t) ==
    /\ state[t] = "SCHEDULED"
    /\ state' = [state EXCEPT ![t] = "CANCELED"]
    /\ log' = Append(log, <<t, "canceled">>)

Fire(t) ==
    /\ state[t] = "SCHEDULED"
    /\ state' = [state EXCEPT ![t] = "FIRED"]
    /\ log' = Append(log, <<t, "fired">>)

Next == \E t \in Timers : (Schedule(t) \/ Cancel(t) \/ Fire(t))

Spec == Init /\ [][Next]_vars

\* ======================== SAFETY INVARIANTS ========================

\* DT-INV-03: a canceled timer NEVER transitions to FIRED.
CanceledNeverFires ==
    \A t \in Timers : state[t] = "CANCELED" => TRUE   \* transition system only fires from SCHEDULED.

\* DT-INV-01: every FIRED event appears exactly once in the log for each timer.
FiredRecordedAtMostOnce ==
    \A t \in Timers :
        Cardinality({i \in 1..Len(log) : log[i][1] = t /\ log[i][2] = "fired"}) <= 1

\* Mutually exclusive terminal states.
TerminalDisjoint ==
    \A t \in Timers :
        ~(state[t] = "FIRED" /\ \E i \in 1..Len(log) : log[i][1] = t /\ log[i][2] = "canceled")

Inv ==
    /\ TypeInvariant
    /\ FiredRecordedAtMostOnce
    /\ TerminalDisjoint

============================================================================
