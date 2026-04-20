---- MODULE ChangeDataCapture ----
EXTENDS Naturals, FiniteSets, Sequences

CONSTANTS Txids, MaxPos
VARIABLES log, pending, committed, aborted, nextPos, checkpoint

\* `log` is a sequence of positions that were assigned to committed events.
\* `pending[t]` = number of staged events inside open transaction t.
\* `committed` / `aborted` partition the terminal-state txids.
\* `nextPos` is the monotonic cursor assigning the next position.
\* `checkpoint` is the consumer's persisted resume point.

TypeOK ==
    /\ log \in Seq(1..MaxPos)
    /\ pending \in [Txids -> 0..MaxPos]
    /\ committed \subseteq Txids
    /\ aborted \subseteq Txids
    /\ nextPos \in 1..(MaxPos + 1)
    /\ checkpoint \in 0..MaxPos

Init ==
    /\ log = <<>>
    /\ pending = [t \in Txids |-> 0]
    /\ committed = {}
    /\ aborted = {}
    /\ nextPos = 1
    /\ checkpoint = 0

\* Open a fresh transaction (only a non-terminal one that is not already open).
Begin(t) ==
    /\ pending[t] = 0
    /\ t \notin committed
    /\ t \notin aborted
    /\ pending' = [pending EXCEPT ![t] = 1]   \* model: open marks pending >= 1
    /\ UNCHANGED <<log, committed, aborted, nextPos, checkpoint>>

\* Stage another change inside an open transaction (bounded by MaxPos).
Stage(t) ==
    /\ pending[t] >= 1
    /\ pending[t] < MaxPos
    /\ nextPos + pending[t] <= MaxPos + 1
    /\ pending' = [pending EXCEPT ![t] = pending[t] + 1]
    /\ UNCHANGED <<log, committed, aborted, nextPos, checkpoint>>

\* Atomically publish all staged changes to the log.
\* In one step we append `pending[t]` contiguous positions in order.
CommitOne(t) ==
    /\ pending[t] >= 1
    /\ t \notin committed
    /\ t \notin aborted
    /\ nextPos + pending[t] - 1 <= MaxPos
    /\ log' = log \o [ i \in 1..pending[t] |-> nextPos + i - 1 ]
    /\ nextPos' = nextPos + pending[t]
    /\ pending' = [pending EXCEPT ![t] = 0]
    /\ committed' = committed \cup {t}
    /\ UNCHANGED <<aborted, checkpoint>>

\* Rollback discards all staged events — nothing lands on the log.
Rollback(t) ==
    /\ t \notin committed
    /\ pending[t] >= 1
    /\ pending' = [pending EXCEPT ![t] = 0]
    /\ aborted' = aborted \cup {t}
    /\ UNCHANGED <<log, committed, nextPos, checkpoint>>

\* Advance the consumer checkpoint (monotonic). Modelled non-deterministically
\* as advancing to any position already committed.
Advance ==
    /\ \E p \in checkpoint..(nextPos - 1): checkpoint' = p
    /\ UNCHANGED <<log, pending, committed, aborted, nextPos>>

Next ==
    \/ \E t \in Txids: Begin(t)
    \/ \E t \in Txids: Stage(t)
    \/ \E t \in Txids: CommitOne(t)
    \/ \E t \in Txids: Rollback(t)
    \/ Advance

Spec == Init /\ [][Next]_<<log, pending, committed, aborted, nextPos, checkpoint>>

\* ---------- Safety invariants ----------

\* CDC-INV-02: positions in the log are strictly monotonic and equal to the
\* range 1..Len(log) when read in order. Because we assign nextPos on commit
\* and bump it by exactly pending[t], `log` should equal <<1,2,...,Len(log)>>.
LogIsMonotonic ==
    \A i \in 1..Len(log): log[i] = i

\* CDC-INV-02 (dual): nextPos always exceeds every committed position.
NextPosAheadOfLog ==
    \A i \in 1..Len(log): log[i] < nextPos

\* CDC-INV-02: checkpoint NEVER exceeds the committed head.
CheckpointBounded ==
    checkpoint <= nextPos - 1 /\ checkpoint >= 0

\* CDC-INV-01 / 03: committed and aborted never overlap — a tx cannot be both.
CommittedAbortedDisjoint == committed \cap aborted = {}

====
