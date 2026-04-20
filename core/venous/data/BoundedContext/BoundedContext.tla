---- MODULE BoundedContext ----
EXTENDS Naturals, FiniteSets, TLC

CONSTANTS Contexts, Aggregates, RelKinds
VARIABLES owner, language, edges

\* Distinguished "unowned" marker so owner : Aggregates -> Contexts \cup {NONE}.
NONE == "NONE"

TypeOK ==
    /\ owner \in [Aggregates -> Contexts \cup {NONE}]
    /\ language \in [Contexts -> SUBSET STRING]
    /\ edges \in SUBSET (Contexts \X Contexts \X RelKinds)

Init ==
    /\ owner = [a \in Aggregates |-> NONE]
    /\ language = [c \in Contexts |-> {}]
    /\ edges = {}

\* Claim an aggregate for a context — succeeds only if currently unowned or
\* already owned by the same context (BC-INV-01).
Claim(c, a) ==
    /\ owner[a] \in {NONE, c}
    /\ owner' = [owner EXCEPT ![a] = c]
    /\ UNCHANGED <<language, edges>>

\* Reject claim when a different context already owns the aggregate.
ClaimReject(c, a) ==
    /\ owner[a] # NONE
    /\ owner[a] # c
    /\ UNCHANGED <<owner, language, edges>>

\* Define a term inside a context — locally consistent because once added to
\* the set for that context the value CANNOT be redefined (our abstraction
\* treats term identity as the string itself — BC-INV-03).
DefineTerm(c, term) ==
    /\ term \notin language[c]
    /\ language' = [language EXCEPT ![c] = language[c] \cup {term}]
    /\ UNCHANGED <<owner, edges>>

\* Publish an integration on the context map.
PublishEdge(u, d, k) ==
    /\ u # d
    /\ edges' = edges \cup {<<u, d, k>>}
    /\ UNCHANGED <<owner, language>>

Next ==
    \/ \E c \in Contexts, a \in Aggregates: Claim(c, a)
    \/ \E c \in Contexts, a \in Aggregates: ClaimReject(c, a)
    \/ \E c \in Contexts, t \in {"t1", "t2"}: DefineTerm(c, t)
    \/ \E u \in Contexts, d \in Contexts, k \in RelKinds: PublishEdge(u, d, k)

Spec == Init /\ [][Next]_<<owner, language, edges>>

\* Safety: an aggregate is NEVER simultaneously owned by two contexts
\* (BC-INV-01). Because owner is a function, any reachable state trivially
\* maps each aggregate to at most one context; we also assert the only
\* non-NONE value is from Contexts.
SingleOwnership ==
    \A a \in Aggregates: owner[a] \in Contexts \cup {NONE}

\* Safety: there are no self-loops on the context map (BC-INV-04).
NoSelfLoops ==
    \A e \in edges: e[1] # e[2]

\* Safety: every edge kind is canonical (BC-INV-04).
CanonicalEdges ==
    \A e \in edges: e[3] \in RelKinds

====
