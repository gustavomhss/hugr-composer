---- MODULE TransactionalOutbox ----
EXTENDS Naturals, FiniteSets

CONSTANTS Messages, Keys, MaxSeq

ASSUME MaxSeq \in Nat

Seqs == 0..MaxSeq

VARIABLES
    txn_state,      \* "none" | "active" | "committed" | "rolled_back"
    staged,         \* set of <<msg, key, seq>> staged inside the active txn
    store,          \* set of <<msg, key, seq>> durably committed
    msg_status,     \* function Messages -> {"none","pending","published","failed"}
    seq_counter     \* monotonic enqueue sequence (bounded for model checking)

vars == <<txn_state, staged, store, msg_status, seq_counter>>

TypeOK ==
    /\ txn_state \in {"none", "active", "committed", "rolled_back"}
    /\ staged \subseteq (Messages \X Keys \X Seqs)
    /\ store \subseteq (Messages \X Keys \X Seqs)
    /\ msg_status \in [Messages -> {"none", "pending", "published", "failed"}]
    /\ seq_counter \in Seqs

Init ==
    /\ txn_state = "none"
    /\ staged = {}
    /\ store = {}
    /\ msg_status = [m \in Messages |-> "none"]
    /\ seq_counter = 0

Begin ==
    /\ txn_state = "none"
    /\ txn_state' = "active"
    /\ staged' = {}
    /\ UNCHANGED <<store, msg_status, seq_counter>>

Enqueue(m, k) ==
    /\ txn_state = "active"
    /\ msg_status[m] = "none"
    /\ seq_counter + 1 \in Seqs
    /\ seq_counter' = seq_counter + 1
    /\ staged' = staged \cup {<<m, k, seq_counter + 1>>}
    /\ UNCHANGED <<txn_state, store, msg_status>>

StagedMessages(S) == {m \in Messages : \E k \in Keys, s \in Seqs : <<m, k, s>> \in S}

Commit ==
    /\ txn_state = "active"
    /\ txn_state' = "committed"
    /\ store' = store \cup staged
    /\ msg_status' = [m \in Messages |->
         IF m \in StagedMessages(staged)
         THEN "pending"
         ELSE msg_status[m]]
    /\ staged' = {}
    /\ UNCHANGED seq_counter

Rollback ==
    /\ txn_state = "active"
    /\ txn_state' = "rolled_back"
    /\ staged' = {}
    /\ UNCHANGED <<store, msg_status, seq_counter>>

Close ==
    \* Terminal transactions return to "none" so another begin is allowed.
    /\ txn_state \in {"committed", "rolled_back"}
    /\ txn_state' = "none"
    /\ UNCHANGED <<staged, store, msg_status, seq_counter>>

Publish(m) ==
    /\ msg_status[m] \in {"pending", "failed"}
    /\ msg_status' = [msg_status EXCEPT ![m] = "published"]
    /\ UNCHANGED <<txn_state, staged, store, seq_counter>>

Fail(m) ==
    /\ msg_status[m] = "pending"
    /\ msg_status' = [msg_status EXCEPT ![m] = "failed"]
    /\ UNCHANGED <<txn_state, staged, store, seq_counter>>

Next ==
    \/ Begin
    \/ \E m \in Messages, k \in Keys : Enqueue(m, k)
    \/ Commit
    \/ Rollback
    \/ Close
    \/ \E m \in Messages : Publish(m)
    \/ \E m \in Messages : Fail(m)

Spec == Init /\ [][Next]_vars

\* SAFETY: staged rows are ONLY visible in the store after a commit
\* (TXN-INV-01 — cross-transaction writes FORBIDDEN).
AtomicVisibility ==
    (txn_state = "active") => (\A t \in staged : t \notin store)

\* SAFETY: rolled-back transactions MUST have empty staged set
\* (TXN-INV-01 — failure discards staged rows).
RolledBackIsEmpty ==
    (txn_state = "rolled_back") => (staged = {})

\* SAFETY: status is bounded.
StatusBounded ==
    \A m \in Messages : msg_status[m] \in {"none", "pending", "published", "failed"}

====
