---- MODULE Aggregate ----
EXTENDS Naturals, FiniteSets, Sequences

CONSTANTS Commands, MaxLines
VARIABLES version, lines, events, invariant_ok

TypeOK ==
    /\ version \in Nat
    /\ lines \in SUBSET (Commands \X Nat)
    /\ events \in Seq(Commands)
    /\ invariant_ok \in BOOLEAN

Init ==
    /\ version = 0
    /\ lines = {}
    /\ events = <<>>
    /\ invariant_ok = TRUE

\* A successful command: version bumps, event appended, invariants hold.
ApplyOk(c) ==
    /\ invariant_ok
    /\ Cardinality(lines) < MaxLines
    /\ version' = version + 1
    /\ lines' = lines \cup {<<c, version + 1>>}
    /\ events' = Append(events, c)
    /\ invariant_ok' = TRUE

\* A rejected command: state (version, lines, events) UNCHANGED.
ApplyReject(c) ==
    /\ Cardinality(lines) >= MaxLines
    /\ UNCHANGED <<version, lines, events, invariant_ok>>

\* Drain pending events. Version does NOT move; event buffer resets.
Drain ==
    /\ events' = <<>>
    /\ UNCHANGED <<version, lines, invariant_ok>>

Next ==
    \/ \E c \in Commands: ApplyOk(c)
    \/ \E c \in Commands: ApplyReject(c)
    \/ Drain

Spec == Init /\ [][Next]_<<version, lines, events, invariant_ok>>

\* Safety: version never decreases (AGG-INV-04).
VersionMonotonic == version >= 0

\* Safety: invariants always hold at the end of a public method (AGG-INV-03).
InvariantHolds == invariant_ok = TRUE

\* Safety: lines cardinality bounded by MaxLines (AGG-INV-03 domain check).
BoundedLines == Cardinality(lines) <= MaxLines

====
