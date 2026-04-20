---- MODULE Repository ----
EXTENDS Naturals, FiniteSets

CONSTANTS Ids

VARIABLES store, tombstones, enlisted_new, enlisted_removed

TypeOK ==
    /\ store \subseteq Ids
    /\ tombstones \subseteq Ids
    /\ enlisted_new \subseteq Ids
    /\ enlisted_removed \subseteq Ids

Init ==
    /\ store = {}
    /\ tombstones = {}
    /\ enlisted_new = {}
    /\ enlisted_removed = {}

Add(i) ==
    /\ i \notin store
    /\ store' = store \cup {i}
    /\ tombstones' = tombstones \ {i}
    /\ enlisted_new' = enlisted_new \cup {i}
    /\ UNCHANGED <<enlisted_removed>>

Remove(i) ==
    /\ i \in store
    /\ store' = store \ {i}
    /\ tombstones' = tombstones \cup {i}
    /\ enlisted_removed' = enlisted_removed \cup {i}
    /\ UNCHANGED <<enlisted_new>>

Get(i) ==
    /\ UNCHANGED <<store, tombstones, enlisted_new, enlisted_removed>>

Next ==
    \/ \E i \in Ids: Add(i)
    \/ \E i \in Ids: Remove(i)
    \/ \E i \in Ids: Get(i)

Spec == Init /\ [][Next]_<<store, tombstones, enlisted_new, enlisted_removed>>

\* Safety: tombstones and live store are disjoint (REPO-INV-01 structural).
StoreTombstoneDisjoint == store \cap tombstones = {}

\* Safety: every live id was enlisted as new at some point (REPO-INV-04).
EnlistmentCoversStore == store \subseteq enlisted_new

\* Safety: every removed id was enlisted for removal (REPO-INV-04).
RemovalEnlistment == tombstones \subseteq enlisted_removed

====
