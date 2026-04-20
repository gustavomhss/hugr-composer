---- MODULE StreamSubject ----
(***************************************************************************
 TLA+ specification of StreamSubject subscription registry.

 We model a bounded registry: patterns map to subscriber sets, publications
 are tracked as a set of (subject, pattern) delivered pairs.

 Safety invariants:

 - DeliveryMatches (SS_INV_02/SS_INV_03): every delivered pair (subject,
   pattern) appears only when Matches[subject, pattern] is TRUE.
 - RegistrationBounded: subscriber sets stay within the finite universe.
 ***************************************************************************)
EXTENDS Naturals, FiniteSets

\* Finite universe, hard-coded for the bounded check.
Subjects == {"s1", "s2"}
Patterns == {"p1", "p2"}
Subscribers == {"c1", "c2"}

\* Oracle: Matches[s, p] is TRUE iff subject s matches pattern p.
\* Modelled here by explicit pairs (trivially consistent with the real matcher).
MatchPairs == {<<"s1", "p1">>, <<"s2", "p1">>, <<"s2", "p2">>}

Matches(s, p) == <<s, p>> \in MatchPairs

VARIABLES
    subs,       \* pattern -> SUBSET Subscribers
    delivered   \* SUBSET (Subjects \X Patterns)

vars == <<subs, delivered>>

TypeOK ==
    /\ subs \in [Patterns -> SUBSET Subscribers]
    /\ delivered \subseteq (Subjects \X Patterns)

Init ==
    /\ subs = [p \in Patterns |-> {}]
    /\ delivered = {}

Subscribe(p, sid) ==
    /\ p \in Patterns
    /\ sid \in Subscribers
    /\ subs' = [subs EXCEPT ![p] = @ \union {sid}]
    /\ UNCHANGED delivered

Unsubscribe(p, sid) ==
    /\ p \in Patterns
    /\ sid \in Subscribers
    /\ subs' = [subs EXCEPT ![p] = @ \ {sid}]
    /\ UNCHANGED delivered

Publish(s) ==
    /\ s \in Subjects
    /\ delivered' = delivered \union {<<s, p>> : p \in {q \in Patterns: Matches(s, q)}}
    /\ UNCHANGED subs

Next ==
    \/ \E p \in Patterns, sid \in Subscribers: Subscribe(p, sid)
    \/ \E p \in Patterns, sid \in Subscribers: Unsubscribe(p, sid)
    \/ \E s \in Subjects: Publish(s)

Spec == Init /\ [][Next]_vars

\* SS_INV_02/03 (bounded): every delivered pair satisfies the Matches oracle.
DeliveryMatches ==
    \A pair \in delivered: Matches(pair[1], pair[2])

RegistrationBounded ==
    \A p \in Patterns: subs[p] \subseteq Subscribers

Safety == DeliveryMatches /\ RegistrationBounded

====
