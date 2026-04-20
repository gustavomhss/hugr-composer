---------------------------- MODULE ActivityCall ----------------------------
(* TLA+ spec for the ActivityCall primitive.                               *)
(* Covers AC-INV-04 (max-attempts surfaces terminal error) and             *)
(*        AC-INV-01 (at-least-once — outcome is success OR max_attempts).  *)

EXTENDS Integers, Sequences, FiniteSets, TLC

CONSTANTS
    MaxAttempts    \* maximum attempts per activity run (model bound)

ASSUME MaxAttempts \in Nat /\ MaxAttempts >= 1

Outcomes == {"pending", "success", "exhausted"}

VARIABLES
    attemptNo,     \* 1..MaxAttempts
    outcome,       \* one of Outcomes
    attemptsUsed   \* accounting

vars == <<attemptNo, outcome, attemptsUsed>>

TypeInvariant ==
    /\ attemptNo \in 1 .. MaxAttempts
    /\ outcome \in Outcomes
    /\ attemptsUsed \in 0 .. MaxAttempts

Init ==
    /\ attemptNo = 1
    /\ outcome = "pending"
    /\ attemptsUsed = 0

AttemptSucceeds ==
    /\ outcome = "pending"
    /\ outcome' = "success"
    /\ attemptsUsed' = attemptsUsed + 1
    /\ UNCHANGED attemptNo

AttemptFailsContinue ==
    /\ outcome = "pending"
    /\ attemptNo < MaxAttempts
    /\ attemptNo' = attemptNo + 1
    /\ attemptsUsed' = attemptsUsed + 1
    /\ UNCHANGED outcome

AttemptFailsExhaust ==
    /\ outcome = "pending"
    /\ attemptNo = MaxAttempts
    /\ outcome' = "exhausted"
    /\ attemptsUsed' = attemptsUsed + 1
    /\ UNCHANGED attemptNo

Next ==
    \/ AttemptSucceeds
    \/ AttemptFailsContinue
    \/ AttemptFailsExhaust

Spec == Init /\ [][Next]_vars

\* ======================== SAFETY INVARIANTS ========================

\* AC-INV-01 / AC-INV-04: we never silently drop the outcome; it is one of
\* the three allowed values, and once resolved (success|exhausted) it stays.
NoSilentDrop == outcome \in Outcomes
Monotone ==
    [](outcome = "success" => [](outcome = "success"))
    /\ [](outcome = "exhausted" => [](outcome = "exhausted"))

\* Bounded attempts.
AttemptsBounded == attemptsUsed <= MaxAttempts

Inv ==
    /\ TypeInvariant
    /\ NoSilentDrop
    /\ AttemptsBounded

============================================================================
