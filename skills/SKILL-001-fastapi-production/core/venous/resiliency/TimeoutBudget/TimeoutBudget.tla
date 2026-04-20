---- MODULE TimeoutBudget ----
EXTENDS Naturals

CONSTANTS MaxHops, RootBudget

VARIABLES clock, deadlines, hop

\* deadlines[i] is the absolute-deadline of hop i (0 = root).
\* hop is the index of the current deepest hop (0..MaxHops).

TypeOK ==
    /\ clock \in 0..(RootBudget + MaxHops)
    /\ hop \in 0..MaxHops
    /\ deadlines \in [0..MaxHops -> 0..(RootBudget + MaxHops)]

Init ==
    /\ clock = 0
    /\ hop = 0
    /\ deadlines = [i \in 0..MaxHops |-> IF i = 0 THEN RootBudget ELSE 0]

\* Tick the monotonic clock forward by one unit.
Tick ==
    /\ clock < RootBudget + MaxHops
    /\ clock' = clock + 1
    /\ UNCHANGED <<deadlines, hop>>

\* Derive a new child hop. The child deadline MUST be <= its parent's deadline
\* (TB-INV-04: monotonic decrease, never renewed).
Derive(req) ==
    /\ hop < MaxHops
    /\ req \in 1..RootBudget
    /\ LET proposed == clock + req
           parent == deadlines[hop]
           child == IF proposed < parent THEN proposed ELSE parent
       IN  /\ child <= parent
           /\ deadlines' = [deadlines EXCEPT ![hop + 1] = child]
           /\ hop' = hop + 1
    /\ UNCHANGED clock

\* Stay-put step to bound state graph.
Stutter == UNCHANGED <<clock, deadlines, hop>>

Next ==
    \/ Tick
    \/ \E r \in 1..RootBudget: Derive(r)
    \/ Stutter

Spec == Init /\ [][Next]_<<clock, deadlines, hop>>

\* Safety: every active hop's deadline is <= its parent's deadline (TB-INV-04).
ChildLEParent ==
    \A i \in 1..MaxHops:
        (i <= hop) => deadlines[i] <= deadlines[i - 1]

\* Safety: no deadline ever exceeds the root deadline (TB-INV-04 — monotonic).
AllHopsBoundedByRoot ==
    \A i \in 0..MaxHops:
        (i <= hop) => deadlines[i] <= deadlines[0]

\* Safety: the clock only moves forward; it never resets (TB-INV-02).
ClockBounded ==
    clock <= RootBudget + MaxHops

====
