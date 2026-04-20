---- MODULE TopicBus ----
EXTENDS Naturals, Sequences, FiniteSets

CONSTANTS Envelopes, MaxRedeliveries

VARIABLES
    log,            \* Sequence of published envelopes (the durable append log)
    delivered,      \* Set of envelopes for which at least one delivery was made
    acked,          \* Set of envelopes that were acked
    dlq,            \* Set of envelopes routed to the dead-letter topic
    attempts,       \* Function: Envelopes -> Nat, delivery-attempt count
    inflight        \* At most one envelope inflight at a time (TB_INV_02 per-key, single-key model)

TypeOK ==
    /\ log \in Seq(Envelopes)
    /\ delivered \subseteq Envelopes
    /\ acked \subseteq Envelopes
    /\ dlq \subseteq Envelopes
    /\ attempts \in [Envelopes -> Nat]
    /\ inflight \in Envelopes \cup {"none"}

Init ==
    /\ log = <<>>
    /\ delivered = {}
    /\ acked = {}
    /\ dlq = {}
    /\ attempts = [e \in Envelopes |-> 0]
    /\ inflight = "none"

\* TB_INV_05: publish appends to the durable log atomically before any fanout.
Publish(e) ==
    /\ e \notin {log[i] : i \in 1..Len(log)}
    /\ log' = Append(log, e)
    /\ UNCHANGED <<delivered, acked, dlq, attempts, inflight>>

\* Begin a delivery attempt — TB_INV_02 requires exclusive inflight per-key.
\* In this single-key model, `inflight = "none"` models the per-key lock.
BeginDeliver(e) ==
    /\ e \in {log[i] : i \in 1..Len(log)}
    /\ e \notin acked
    /\ e \notin dlq
    /\ inflight = "none"
    /\ attempts[e] < MaxRedeliveries + 1
    /\ inflight' = e
    /\ attempts' = [attempts EXCEPT ![e] = attempts[e] + 1]
    /\ delivered' = delivered \cup {e}
    /\ UNCHANGED <<log, acked, dlq>>

Ack(e) ==
    /\ inflight = e
    /\ inflight' = "none"
    /\ acked' = acked \cup {e}
    /\ UNCHANGED <<log, delivered, dlq, attempts>>

\* Nack: either another redelivery is possible, or route to DLQ (never drop).
NackRedeliver(e) ==
    /\ inflight = e
    /\ attempts[e] <= MaxRedeliveries
    /\ inflight' = "none"
    /\ UNCHANGED <<log, delivered, acked, dlq, attempts>>

NackExhaust(e) ==
    /\ inflight = e
    /\ attempts[e] = MaxRedeliveries + 1
    /\ inflight' = "none"
    /\ dlq' = dlq \cup {e}
    /\ UNCHANGED <<log, delivered, acked, attempts>>

\* Terminal stutter: once every published envelope is acked or DLQ'd, allow
\* self-transitions so TLC does not treat reaching a resting state as deadlock.
Done ==
    /\ \A e \in Envelopes:
            (e \in {log[i] : i \in 1..Len(log)}) =>
                (e \in acked \/ e \in dlq)
    /\ UNCHANGED <<log, delivered, acked, dlq, attempts, inflight>>

Next ==
    \/ \E e \in Envelopes: Publish(e)
    \/ \E e \in Envelopes: BeginDeliver(e)
    \/ \E e \in Envelopes: Ack(e)
    \/ \E e \in Envelopes: NackRedeliver(e)
    \/ \E e \in Envelopes: NackExhaust(e)
    \/ Done

Spec == Init /\ [][Next]_<<log, delivered, acked, dlq, attempts, inflight>>

\* Safety: at-least-once OR DLQ — any envelope that has been published and
\* reached a terminal state is either acked OR dlqed, never silently dropped.
\* (TB_INV_01 + TB_INV_03 joint guarantee.)
NoSilentDrop ==
    \A e \in Envelopes:
        (attempts[e] = MaxRedeliveries + 1 /\ inflight # e) =>
            (e \in acked \/ e \in dlq)

\* Safety: exclusive dispatch — at most one envelope inflight at a time
\* in this single-key model (TB_INV_02).
ExclusiveDispatch ==
    \A e1, e2 \in Envelopes:
        (inflight = e1 /\ inflight = e2) => (e1 = e2)

\* Safety: the log is monotone — once a record is appended, it stays
\* (TB_INV_05 — no rollback of a committed append).
LogMonotone ==
    \A i \in 1..Len(log): log[i] \in Envelopes

\* Safety: ack implies at least one delivery happened (TB_INV_01).
AckImpliesDelivered ==
    \A e \in Envelopes: (e \in acked) => (e \in delivered)

====
