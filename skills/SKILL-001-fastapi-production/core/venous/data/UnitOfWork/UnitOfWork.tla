---- MODULE UnitOfWork ----
EXTENDS Naturals, FiniteSets

CONSTANTS Objects
VARIABLES state, new, dirty, removed

TypeOK ==
    /\ state \in {"open", "committed", "rolled_back"}
    /\ new \subseteq Objects
    /\ dirty \subseteq Objects
    /\ removed \subseteq Objects

Init ==
    /\ state = "open"
    /\ new = {}
    /\ dirty = {}
    /\ removed = {}

RegisterNew(o) ==
    /\ state = "open"
    /\ o \notin (new \cup dirty \cup removed)
    /\ new' = new \cup {o}
    /\ UNCHANGED <<state, dirty, removed>>

RegisterDirty(o) ==
    /\ state = "open"
    /\ o \notin (new \cup dirty \cup removed)
    /\ dirty' = dirty \cup {o}
    /\ UNCHANGED <<state, new, removed>>

RegisterRemoved(o) ==
    /\ state = "open"
    /\ o \notin (new \cup dirty \cup removed)
    /\ removed' = removed \cup {o}
    /\ UNCHANGED <<state, new, dirty>>

Commit ==
    /\ state = "open"
    /\ state' = "committed"
    /\ UNCHANGED <<new, dirty, removed>>

Rollback ==
    /\ state = "open"
    /\ state' = "rolled_back"
    /\ new' = {}
    /\ dirty' = {}
    /\ removed' = {}

Terminal ==
    /\ state \in {"committed", "rolled_back"}
    /\ UNCHANGED <<state, new, dirty, removed>>

Next ==
    \/ \E o \in Objects: RegisterNew(o)
    \/ \E o \in Objects: RegisterDirty(o)
    \/ \E o \in Objects: RegisterRemoved(o)
    \/ Commit
    \/ Rollback
    \/ Terminal

Spec == Init /\ [][Next]_<<state, new, dirty, removed>>

\* Safety: buckets are always disjoint (UOW-INV-02).
BucketsDisjoint ==
    /\ new \cap dirty = {}
    /\ new \cap removed = {}
    /\ dirty \cap removed = {}

\* Safety: after rollback the buckets are empty (UOW-INV-01).
RolledBackIsEmpty ==
    (state = "rolled_back") => (new = {} /\ dirty = {} /\ removed = {})

\* Safety: state is bounded (UOW-INV-03 — three discrete states, no others).
StateBounded == state \in {"open", "committed", "rolled_back"}

====
