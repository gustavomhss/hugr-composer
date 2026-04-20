---- MODULE DomainEvent ----
EXTENDS Naturals, Sequences, FiniteSets

CONSTANTS Aggregates, MaxVersion

VARIABLES last_version, pending, published

\* One aggregate's stream state is a tuple per aggregate:
\*   last_version[a]: highest flushed version (starts 0)
\*   pending[a]: sequence of staged-but-not-flushed versions
\*   published[a]: sequence of flushed versions (monotonic 1..last_version)

TypeOK ==
    /\ last_version \in [Aggregates -> 0..MaxVersion]
    /\ pending \in [Aggregates -> Seq(1..MaxVersion)]
    /\ published \in [Aggregates -> Seq(1..MaxVersion)]

Init ==
    /\ last_version = [a \in Aggregates |-> 0]
    /\ pending = [a \in Aggregates |-> <<>>]
    /\ published = [a \in Aggregates |-> <<>>]

\* Stage the strict next version of aggregate a (DE-INV-04).
Stage(a) ==
    LET next_v == last_version[a] + Len(pending[a]) + 1 IN
    /\ next_v <= MaxVersion
    /\ pending' = [pending EXCEPT ![a] = Append(pending[a], next_v)]
    /\ UNCHANGED <<last_version, published>>

\* Flush publishes pending in order and advances last_version.
Flush(a) ==
    /\ Len(pending[a]) > 0
    /\ published' = [published EXCEPT ![a] = published[a] \o pending[a]]
    /\ last_version' = [last_version EXCEPT ![a] = last_version[a] + Len(pending[a])]
    /\ pending' = [pending EXCEPT ![a] = <<>>]

\* Discard drops pending without publishing (rollback).
Discard(a) ==
    /\ Len(pending[a]) > 0
    /\ pending' = [pending EXCEPT ![a] = <<>>]
    /\ UNCHANGED <<last_version, published>>

Next ==
    \/ \E a \in Aggregates: Stage(a)
    \/ \E a \in Aggregates: Flush(a)
    \/ \E a \in Aggregates: Discard(a)

Spec == Init /\ [][Next]_<<last_version, pending, published>>

\* Safety 1 (DE-INV-04): published versions per aggregate are 1, 2, 3, ...
PublishedIsContiguous ==
    \A a \in Aggregates:
        \A i \in 1..Len(published[a]):
            published[a][i] = i

\* Safety 2 (DE-INV-04): last_version equals Len(published) — the watermark never
\* drifts from the publish log.
WatermarkMatchesLog ==
    \A a \in Aggregates:
        last_version[a] = Len(published[a])

\* Safety 3 (DE-INV-02): within one aggregate's publish log, no version appears
\* twice — the versions are a strictly ascending prefix of Nat.
PublishedNoDuplicates ==
    \A a \in Aggregates:
        \A i, j \in 1..Len(published[a]):
            (i /= j) => (published[a][i] /= published[a][j])

\* Safety 4: pending extends the last_version contiguously too.
PendingContiguousAfterWatermark ==
    \A a \in Aggregates:
        \A i \in 1..Len(pending[a]):
            pending[a][i] = last_version[a] + i

====
