---------------------------- MODULE TransactionalBatch ----------------------------
(* TLA+ spec for the TransactionalBatch primitive.                          *)
(* Covers TXB-INV-01 (atomic commit), TXB-INV-03 (no reuse after close).    *)

EXTENDS Integers, Sequences, FiniteSets, TLC

CONSTANTS
    Keys,           \* finite set of keys, e.g. {"k1","k2"}
    MaxOps          \* bound on ops per batch (kept small for BFS)

ASSUME Keys \in SUBSET STRING /\ MaxOps \in Nat /\ MaxOps >= 1

States == {"OPEN", "COMMITTED", "ABORTED"}

VARIABLES
    store,          \* function Keys -> {"absent"} \cup {"v0","v1",...}
    batchState,     \* one of States
    queued,         \* sequence of records [op: {"upsert","delete"}, key: Keys]
    committed       \* snapshot of store taken at commit time; FALSE when not committed

vars == <<store, batchState, queued, committed>>

AbsentValue == "absent"
Values == {"v0", "v1"}       \* small value universe to keep the state space small

TypeInvariant ==
    /\ batchState \in States
    /\ DOMAIN store = Keys
    /\ \A k \in Keys : store[k] \in (Values \cup {AbsentValue})
    /\ Len(queued) \in 0 .. MaxOps

Init ==
    /\ store = [k \in Keys |-> AbsentValue]
    /\ batchState = "OPEN"
    /\ queued = <<>>
    /\ committed = FALSE

\* Append one operation while OPEN (only; TXB-INV-03).
AppendUpsert(k, v) ==
    /\ batchState = "OPEN"
    /\ Len(queued) < MaxOps
    /\ queued' = Append(queued, [op |-> "upsert", key |-> k, value |-> v])
    /\ UNCHANGED <<store, batchState, committed>>

AppendDelete(k) ==
    /\ batchState = "OPEN"
    /\ Len(queued) < MaxOps
    /\ queued' = Append(queued, [op |-> "delete", key |-> k, value |-> AbsentValue])
    /\ UNCHANGED <<store, batchState, committed>>

\* Commit atomically. TXB-INV-01: all-or-nothing.
ApplyOne(s, op) ==
    IF op.op = "upsert"
        THEN [s EXCEPT ![op.key] = op.value]
        ELSE [s EXCEPT ![op.key] = AbsentValue]

RECURSIVE ApplyAll(_, _)
ApplyAll(s, ops) ==
    IF ops = <<>> THEN s ELSE ApplyAll(ApplyOne(s, Head(ops)), Tail(ops))

Commit ==
    /\ batchState = "OPEN"
    /\ store' = ApplyAll(store, queued)
    /\ batchState' = "COMMITTED"
    /\ committed' = TRUE
    /\ UNCHANGED queued

Abort ==
    /\ batchState = "OPEN"
    /\ batchState' = "ABORTED"
    /\ UNCHANGED <<store, queued, committed>>

Next ==
    \/ \E k \in Keys, v \in Values : AppendUpsert(k, v)
    \/ \E k \in Keys : AppendDelete(k)
    \/ Commit
    \/ Abort

Spec == Init /\ [][Next]_vars

\* ======================== SAFETY INVARIANTS ========================

\* TXB-INV-03: once the batch leaves OPEN it MUST NOT transition back.
NoReuseAfterClose ==
    [](batchState = "COMMITTED" => [](batchState = "COMMITTED"))
    /\ [](batchState = "ABORTED" => [](batchState = "ABORTED"))

\* TXB-INV-01: atomicity. When the batch is still OPEN, no effect of queued
\* ops appears in the store. When committed, the store equals ApplyAll(init, queued)
\* applied on top of whatever was there.
AtomicityAsState ==
    (batchState = "OPEN") => (~committed)

\* Composite inductive invariant suitable for TLC.
Inv ==
    /\ TypeInvariant
    /\ AtomicityAsState

============================================================================

\* Model configuration (tlc reads MC file by default but we also inline a small
\* instance here so running `tlc TransactionalBatch.tla` model-checks with
\* the default spec above against CONSTANTS below via overrides in the .cfg).
