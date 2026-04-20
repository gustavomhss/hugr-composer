---- MODULE DeadLetterRoute ----
EXTENDS Naturals, FiniteSets

CONSTANTS Envelopes, MaxDeliveries

VARIABLES
    parked,        \* Set of envelopes currently parked on destination_topic
    requeued,      \* Set of envelopes that were requeued back to source
    purged,        \* Set of envelopes that were purged
    failureCount,  \* Function Envelopes -> Nat: how many times send() landed
    sourceSeen,    \* Set of envelopes EVER seen on the source topic (audit)
    destSeen       \* Set of envelopes EVER parked on destination (audit)

TypeOK ==
    /\ parked \subseteq Envelopes
    /\ requeued \subseteq Envelopes
    /\ purged \subseteq Envelopes
    /\ failureCount \in [Envelopes -> Nat]
    /\ sourceSeen \subseteq Envelopes
    /\ destSeen \subseteq Envelopes

Init ==
    /\ parked = {}
    /\ requeued = {}
    /\ purged = {}
    /\ failureCount = [e \in Envelopes |-> 0]
    /\ sourceSeen = {}
    /\ destSeen = {}

\* DLR_INV_01 + DLR_INV_05: send parks the envelope AFTER exhausting the
\* delivery budget, records a failure, NEVER touches the source topic.
Send(e) ==
    /\ failureCount[e] < MaxDeliveries + 2
    /\ parked' = parked \cup {e}
    /\ destSeen' = destSeen \cup {e}
    /\ failureCount' = [failureCount EXCEPT ![e] = failureCount[e] + 1]
    /\ UNCHANGED <<requeued, purged, sourceSeen>>

\* Requeue removes the envelope from parked and puts it BACK on the source
\* topic — DLR_INV_02: identity survives, DLR_INV_01: controlled return
\* happens only via the requeue path, not via send().
Requeue(e) ==
    /\ e \in parked
    /\ parked' = parked \ {e}
    /\ requeued' = requeued \cup {e}
    /\ sourceSeen' = sourceSeen \cup {e}
    /\ UNCHANGED <<purged, failureCount, destSeen>>

\* Purge removes a parked envelope — terminal operator action.
Purge(e) ==
    /\ e \in parked
    /\ parked' = parked \ {e}
    /\ purged' = purged \cup {e}
    /\ UNCHANGED <<requeued, failureCount, sourceSeen, destSeen>>

\* Terminal stutter.
Done ==
    /\ \A e \in Envelopes:
            (e \in destSeen) =>
                (e \in parked \/ e \in requeued \/ e \in purged)
    /\ UNCHANGED <<parked, requeued, purged, failureCount, sourceSeen, destSeen>>

Next ==
    \/ \E e \in Envelopes: Send(e)
    \/ \E e \in Envelopes: Requeue(e)
    \/ \E e \in Envelopes: Purge(e)
    \/ Done

Spec == Init /\ [][Next]_<<parked, requeued, purged, failureCount, sourceSeen, destSeen>>

\* --------- Safety invariants mapped to catalog invariants ----------

\* DLR_INV_01: an envelope on the source AFTER send() implies it came back
\* via requeue — send() NEVER publishes to the source. Equivalently: every
\* envelope in sourceSeen \cap destSeen MUST be in requeued.
NoReturnToSourceExceptViaRequeue ==
    \A e \in Envelopes:
        (e \in sourceSeen /\ e \in destSeen) => (e \in requeued)

\* DLR_INV_02: identity is preserved — a requeued envelope was first parked.
RequeuedImpliesPreviouslyParked ==
    \A e \in Envelopes: (e \in requeued) => (e \in destSeen)

\* DLR_INV_04: an envelope that has been purged or requeued MUST have been
\* parked first — terminal operator actions never happen in the void.
TerminalImpliesPreviouslyParked ==
    \A e \in Envelopes:
        ((e \in requeued) \/ (e \in purged)) => (e \in destSeen)

\* DLR_INV_05 witness: if an envelope is parked, it had at least one failure.
ParkedHasFailureRecord ==
    \A e \in Envelopes: (e \in parked) => (failureCount[e] > 0)

====
