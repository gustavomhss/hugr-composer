---- MODULE EventStream ----
EXTENDS Naturals, FiniteSets, Sequences

CONSTANTS Partitions, MaxSeq
VARIABLES log, nextSeq, truncated

\* `log[p]` is the sequence of seqs assigned to events in partition p. It is
\*   built by appending nextSeq[p] on each Append(p) step.
\* `nextSeq[p]` is the monotonic cursor — next Append returns this value.
\* `truncated[p]` is the per-partition truncation cursor; it may only advance.

TypeOK ==
    /\ log \in [Partitions -> Seq(1..MaxSeq)]
    /\ nextSeq \in [Partitions -> 1..(MaxSeq + 1)]
    /\ truncated \in [Partitions -> 0..MaxSeq]

Init ==
    /\ log = [p \in Partitions |-> <<>>]
    /\ nextSeq = [p \in Partitions |-> 1]
    /\ truncated = [p \in Partitions |-> 0]

\* Append the current nextSeq[p] to log[p] and bump the counter.
AppendEvent(p) ==
    /\ nextSeq[p] <= MaxSeq
    /\ log' = [log EXCEPT ![p] = Append(log[p], nextSeq[p])]
    /\ nextSeq' = [nextSeq EXCEPT ![p] = nextSeq[p] + 1]
    /\ UNCHANGED truncated

\* Advance the truncation cursor on partition p.
\* The cursor is bounded by nextSeq[p] (cannot ask the stream to forget
\* events that do not yet exist) and may only advance (never rewind).
Truncate(p) ==
    /\ \E new \in truncated[p]..(nextSeq[p] - 1):
        /\ new >= truncated[p]
        /\ truncated' = [truncated EXCEPT ![p] = new]
        /\ \* Events with seq < new are dropped from the log.
           log' = [log EXCEPT ![p] =
               SelectSeq(log[p], LAMBDA s: s >= new)]
    /\ UNCHANGED nextSeq

Next ==
    \/ \E p \in Partitions: AppendEvent(p)
    \/ \E p \in Partitions: Truncate(p)

Spec == Init /\ [][Next]_<<log, nextSeq, truncated>>

\* ---------- Safety invariants ----------

\* ES-INV-01 — per-partition strict monotonicity.
\* Within each partition the sequence is strictly increasing.
PerPartitionStrictlyMonotonic ==
    \A p \in Partitions:
        \A i, j \in 1..Len(log[p]):
            i < j => log[p][i] < log[p][j]

\* ES-INV-01 — seqs assigned come from the nextSeq counter, so every stored
\* seq is strictly less than nextSeq[p].
NextSeqAheadOfLog ==
    \A p \in Partitions:
        \A i \in 1..Len(log[p]): log[p][i] < nextSeq[p]

\* ES-INV-04 — truncation cursor never exceeds tail.
TruncationBounded ==
    \A p \in Partitions:
        truncated[p] >= 0 /\ truncated[p] <= nextSeq[p] - 1

\* ES-INV-04 — every stored event has seq >= truncated[p].
RetentionRespected ==
    \A p \in Partitions:
        \A i \in 1..Len(log[p]): log[p][i] >= truncated[p]

====
