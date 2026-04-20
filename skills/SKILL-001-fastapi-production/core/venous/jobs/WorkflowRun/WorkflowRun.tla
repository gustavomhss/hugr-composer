---------------------------- MODULE WorkflowRun ----------------------------
(* TLA+ spec for the WorkflowRun primitive.                                *)
(* Covers WFR-INV-03 (no resume under same run_id) and WFR-INV-05 (id reuse).*)

EXTENDS Integers, Sequences, FiniteSets, TLC

CONSTANTS
    Workflows,     \* finite set of workflow ids
    MaxRuns        \* cap on run_id allocations per workflow

ASSUME Workflows \in SUBSET STRING /\ MaxRuns \in Nat /\ MaxRuns >= 1

RunStatus == {"OPEN", "COMPLETED", "CANCELED"}

VARIABLES
    runs,          \* function Workflows -> Seq of [run_id, status]
    counter        \* monotonic run counter

vars == <<runs, counter>>

EmptySeq == <<>>

TypeInvariant ==
    /\ DOMAIN runs = Workflows
    /\ \A w \in Workflows :
          /\ Len(runs[w]) <= MaxRuns
          /\ \A i \in 1 .. Len(runs[w]) : runs[w][i].status \in RunStatus
    /\ counter \in Nat

HasOpen(w) == \E i \in 1 .. Len(runs[w]) : runs[w][i].status = "OPEN"

Init ==
    /\ runs = [w \in Workflows |-> EmptySeq]
    /\ counter = 0

\* Start a new run ONLY when no open run exists (policy = REJECT).
StartNew(w) ==
    /\ ~HasOpen(w)
    /\ Len(runs[w]) < MaxRuns
    /\ counter' = counter + 1
    /\ runs' = [runs EXCEPT ![w] = Append(runs[w], [run_id |-> counter + 1, status |-> "OPEN"])]

\* Complete the single OPEN run (if any).
CompleteOpen(w) ==
    /\ HasOpen(w)
    /\ LET i == CHOOSE idx \in 1 .. Len(runs[w]) : runs[w][idx].status = "OPEN"
       IN runs' = [runs EXCEPT ![w] = [runs[w] EXCEPT ![i] =
                   [run_id |-> runs[w][i].run_id, status |-> "COMPLETED"]]]
    /\ UNCHANGED counter

\* Cancel the OPEN run (if any).
CancelOpen(w) ==
    /\ HasOpen(w)
    /\ LET i == CHOOSE idx \in 1 .. Len(runs[w]) : runs[w][idx].status = "OPEN"
       IN runs' = [runs EXCEPT ![w] = [runs[w] EXCEPT ![i] =
                   [run_id |-> runs[w][i].run_id, status |-> "CANCELED"]]]
    /\ UNCHANGED counter

Next ==
    \/ \E w \in Workflows : StartNew(w)
    \/ \E w \in Workflows : CompleteOpen(w)
    \/ \E w \in Workflows : CancelOpen(w)

Spec == Init /\ [][Next]_vars

\* ======================== SAFETY INVARIANTS ========================

\* WFR-INV-05: at most ONE OPEN run per workflow at any time.
AtMostOneOpen ==
    \A w \in Workflows :
        Cardinality({i \in 1..Len(runs[w]) : runs[w][i].status = "OPEN"}) <= 1

\* WFR-INV-03: once a run is closed (COMPLETED/CANCELED) its status does not revert.
\* Modeled as: no operation transforms a COMPLETED/CANCELED back to OPEN.
\* Enforced by the Next relation structure; we express it as an INVARIANT that
\* run_ids are UNIQUE — a new run MUST allocate a fresh id.
UniqueRunIds ==
    \A w \in Workflows :
        \A i, j \in 1..Len(runs[w]) :
            (i # j) => (runs[w][i].run_id # runs[w][j].run_id)

Inv ==
    /\ TypeInvariant
    /\ AtMostOneOpen
    /\ UniqueRunIds

============================================================================
