---- MODULE SagaOrchestrator ----
EXTENDS Naturals, Sequences, FiniteSets

CONSTANTS Steps, \* Ordered set of step names (total order enforced via StepOrder)
          MaxSagas

VARIABLES
    state,          \* "pending" | "running" | "compensating" | "completed" | "failed"
    completed,      \* Seq(Steps): step names whose forward action completed, in order
    compensated,    \* Seq(Steps): step names that have been compensated, in order
    journalLen      \* number of journal records appended (one per state transition + command)

States == {"pending", "running", "compensating", "completed", "failed"}
Terminal == {"completed", "failed"}

\* A total order on Steps, modelled as a sequence capturing step index.
StepOrder == CHOOSE seq \in [1..Cardinality(Steps) -> Steps]:
                /\ {seq[i] : i \in 1..Cardinality(Steps)} = Steps
                /\ \A i, j \in 1..Cardinality(Steps): i /= j => seq[i] /= seq[j]

NumSteps == Cardinality(Steps)

TypeOK ==
    /\ state \in States
    /\ completed \in Seq(Steps)
    /\ compensated \in Seq(Steps)
    /\ journalLen \in Nat
    /\ Len(completed) <= NumSteps
    /\ Len(compensated) <= NumSteps

Init ==
    /\ state = "pending"
    /\ completed = <<>>
    /\ compensated = <<>>
    /\ journalLen = 0

\* Begin saga: pending -> running, append journal record.
Start ==
    /\ state = "pending"
    /\ state' = "running"
    /\ journalLen' = journalLen + 1
    /\ UNCHANGED <<completed, compensated>>

\* Complete the next forward step in declared order.
\* SAGA-INV-01: only registered steps can be completed (enforced by CHOOSE).
\* SAGA-INV-03: state + journal move in one atomic action.
CompleteNextStep ==
    /\ state = "running"
    /\ Len(completed) < NumSteps
    /\ LET next == StepOrder[Len(completed) + 1]
       IN  completed' = Append(completed, next)
    /\ journalLen' = journalLen + 1
    /\ IF Len(completed) + 1 = NumSteps
         THEN state' = "completed"
         ELSE state' = "running"
    /\ UNCHANGED compensated

\* A participant reports failure on the current in-flight step → begin compensating.
FailStep ==
    /\ state = "running"
    /\ state' = "compensating"
    /\ journalLen' = journalLen + 1
    /\ UNCHANGED <<completed, compensated>>

\* Compensate the tail of `completed` — SAGA-INV-02: reverse order only.
CompensateStep ==
    /\ state = "compensating"
    /\ Len(completed) > 0
    /\ LET tail == completed[Len(completed)]
       IN  /\ compensated' = Append(compensated, tail)
           /\ completed' = SubSeq(completed, 1, Len(completed) - 1)
    /\ journalLen' = journalLen + 1
    /\ state' = "compensating"

\* When every completed step has been compensated, the saga is FAILED.
FinishCompensation ==
    /\ state = "compensating"
    /\ Len(completed) = 0
    /\ state' = "failed"
    /\ journalLen' = journalLen + 1
    /\ UNCHANGED <<completed, compensated>>

\* Stutter once terminal.
StutterTerminal ==
    /\ state \in Terminal
    /\ UNCHANGED <<state, completed, compensated, journalLen>>

Next ==
    \/ Start
    \/ CompleteNextStep
    \/ FailStep
    \/ CompensateStep
    \/ FinishCompensation
    \/ StutterTerminal

Spec == Init /\ [][Next]_<<state, completed, compensated, journalLen>>

\* ---------- Safety invariants ----------

\* SAGA-INV-02 — compensated sequence is the REVERSE of a prefix of the
\* completed sequence at the time FailStep fired. Encoded as: for every i in
\* 1..Len(compensated), the compensated[i] equals the step that was at position
\* (originalCompletedLen - i + 1) in the completed sequence. Since `completed`
\* shrinks as we compensate, we express this via the step index on StepOrder.
ReverseCompensationOrder ==
    \A i, j \in 1..Len(compensated):
        i < j =>
            LET si == CHOOSE k \in 1..NumSteps: StepOrder[k] = compensated[i]
                sj == CHOOSE k \in 1..NumSteps: StepOrder[k] = compensated[j]
            IN  si > sj

\* SAGA-INV-01 — every entry in `completed` and `compensated` is a registered step.
OnlyRegisteredSteps ==
    /\ \A i \in 1..Len(completed): completed[i] \in Steps
    /\ \A i \in 1..Len(compensated): compensated[i] \in Steps

\* SAGA-INV-03 — journal length is at least the number of state transitions we
\* observed. Each action above increments journalLen by 1, so this invariant
\* guards against any future edit that would skip a journal append on a state
\* change.
JournalMonotonic ==
    journalLen >= Len(completed) + Len(compensated)

\* State space is bounded to the declared set — no mystery states.
StateBounded == state \in States

====
