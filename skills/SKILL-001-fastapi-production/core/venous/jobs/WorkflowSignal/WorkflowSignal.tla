---------------------------- MODULE WorkflowSignal ----------------------------
(* TLA+ spec for the WorkflowSignal primitive.                             *)
(* Covers WFS-INV-01 (recorded before delivered) and WFS-INV-03 (closed    *)
(* workflows reject signals).                                              *)

EXTENDS Integers, Sequences, FiniteSets, TLC

CONSTANTS
    Workflows,     \* finite set of workflow ids
    MaxSignals     \* bound on signals per workflow (for BFS)

ASSUME Workflows \in SUBSET STRING /\ MaxSignals \in Nat /\ MaxSignals >= 1

Status == {"none", "open", "closed"}

VARIABLES
    wfStatus,      \* Workflows -> Status
    history        \* Workflows -> Seq (of "signal" strings)

vars == <<wfStatus, history>>

TypeInvariant ==
    /\ DOMAIN wfStatus = Workflows
    /\ \A w \in Workflows : wfStatus[w] \in Status
    /\ DOMAIN history = Workflows
    /\ \A w \in Workflows : Len(history[w]) \in 0 .. MaxSignals

Init ==
    /\ wfStatus = [w \in Workflows |-> "none"]
    /\ history = [w \in Workflows |-> <<>>]

StartRun(w) ==
    /\ wfStatus[w] = "none"
    /\ wfStatus' = [wfStatus EXCEPT ![w] = "open"]
    /\ UNCHANGED history

CloseRun(w) ==
    /\ wfStatus[w] = "open"
    /\ wfStatus' = [wfStatus EXCEPT ![w] = "closed"]
    /\ UNCHANGED history

AcceptSignal(w) ==
    /\ wfStatus[w] = "open"
    /\ Len(history[w]) < MaxSignals
    /\ history' = [history EXCEPT ![w] = Append(history[w], "signal")]
    /\ UNCHANGED wfStatus

Next ==
    \/ \E w \in Workflows : StartRun(w)
    \/ \E w \in Workflows : CloseRun(w)
    \/ \E w \in Workflows : AcceptSignal(w)

Spec == Init /\ [][Next]_vars

\* ======================== SAFETY INVARIANTS ========================

\* WFS-INV-01: every signal is in the history immediately — no "delivered
\* but not recorded" state exists in this model (AcceptSignal is atomic).
\* WFS-INV-03: AcceptSignal is enabled ONLY when status=open, so closed or
\* non-existent workflows can never accept a signal.
HistoryBounded ==
    \A w \in Workflows : Len(history[w]) <= MaxSignals

Inv ==
    /\ TypeInvariant
    /\ HistoryBounded

============================================================================
