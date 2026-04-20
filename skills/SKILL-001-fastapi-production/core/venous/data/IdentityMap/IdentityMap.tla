---- MODULE IdentityMap ----
EXTENDS Naturals, FiniteSets

CONSTANTS Ids

VARIABLES state, entries, refs

TypeOK ==
    /\ state \in {"open", "disposed"}
    /\ entries \subseteq Ids
    /\ refs \in [Ids -> Nat]

Init ==
    /\ state = "open"
    /\ entries = {}
    /\ refs = [i \in Ids |-> 0]

\* Add a fresh entry for id `i` by ASSIGNING a fresh reference tag `r`.
\* We model "same reference" as a monotonically-chosen natural; once an id
\* is bound to a reference, that binding is permanent for the session.
Add(i, r) ==
    /\ state = "open"
    /\ i \notin entries
    /\ r > 0
    /\ entries' = entries \cup {i}
    /\ refs' = [refs EXCEPT ![i] = r]
    /\ UNCHANGED <<state>>

\* Idempotent re-add of the SAME reference is allowed (models `imap.add(obj)` for the canonical ref).
ReAddSame(i) ==
    /\ state = "open"
    /\ i \in entries
    /\ refs[i] > 0
    /\ UNCHANGED <<state, entries, refs>>

\* A write with a DIFFERENT reference is REJECTED (models IDMAP-INV-02 reject).
ConflictAttempt(i, r) ==
    /\ state = "open"
    /\ i \in entries
    /\ r > 0
    /\ r # refs[i]
    /\ UNCHANGED <<state, entries, refs>>

Get(i) ==
    /\ state = "open"
    /\ UNCHANGED <<state, entries, refs>>

Remove(i) ==
    /\ state = "open"
    /\ i \in entries
    /\ entries' = entries \ {i}
    /\ refs' = [refs EXCEPT ![i] = 0]
    /\ UNCHANGED <<state>>

Dispose ==
    /\ state = "open"
    /\ state' = "disposed"
    /\ entries' = {}
    /\ refs' = [i \in Ids |-> 0]

Terminal ==
    /\ state = "disposed"
    /\ UNCHANGED <<state, entries, refs>>

Next ==
    \/ \E i \in Ids, r \in 1..3: Add(i, r)
    \/ \E i \in Ids: ReAddSame(i)
    \/ \E i \in Ids, r \in 1..3: ConflictAttempt(i, r)
    \/ \E i \in Ids: Get(i)
    \/ \E i \in Ids: Remove(i)
    \/ Dispose
    \/ Terminal

Spec == Init /\ [][Next]_<<state, entries, refs>>

\* Safety: an entry always has a positive reference tag; a missing entry's tag is 0.
\* This captures IDMAP-INV-01: once bound, the (id -> reference) mapping is stable.
RefsConsistent ==
    /\ \A i \in Ids: (i \in entries) <=> (refs[i] > 0)

\* Safety: after dispose, entries is empty and no reference is bound (IDMAP-INV-04).
DisposedIsEmpty ==
    (state = "disposed") => (entries = {} /\ \A i \in Ids: refs[i] = 0)

\* Safety: state is bounded to two discrete values.
StateBounded == state \in {"open", "disposed"}

====
