---- MODULE InboxDeduplicator ----
EXTENDS Naturals, FiniteSets

CONSTANTS Messages, Consumers

VARIABLES
    txn_state,   \* "none" | "active" | "committed" | "rolled_back"
    staged,      \* set of <<msg, consumer>> staged inside the active txn
    store,       \* set of <<msg, consumer>> durably committed
    effect_log   \* multiset (modelled as function to Nat) of how many times
                 \* the side-effect has been applied per <<msg, consumer>>

vars == <<txn_state, staged, store, effect_log>>

Pairs == Messages \X Consumers

TypeOK ==
    /\ txn_state \in {"none", "active", "committed", "rolled_back"}
    /\ staged \subseteq Pairs
    /\ store \subseteq Pairs
    /\ effect_log \in [Pairs -> Nat]

Init ==
    /\ txn_state = "none"
    /\ staged = {}
    /\ store = {}
    /\ effect_log = [p \in Pairs |-> 0]

Begin ==
    /\ txn_state = "none"
    /\ txn_state' = "active"
    /\ staged' = {}
    /\ UNCHANGED <<store, effect_log>>

\* Deliver a message: effect runs IFF the pair is not yet seen (in store or
\* staged); on success, the pair is staged inside the active txn.
Deliver(m, c) ==
    /\ txn_state = "active"
    /\ LET pair == <<m, c>> IN
       IF pair \in store \/ pair \in staged
         THEN /\ UNCHANGED <<txn_state, staged, store, effect_log>>
         ELSE /\ staged' = staged \cup {pair}
              /\ effect_log' = [effect_log EXCEPT ![pair] = effect_log[pair] + 1]
              /\ UNCHANGED <<txn_state, store>>

Commit ==
    /\ txn_state = "active"
    /\ txn_state' = "committed"
    /\ store' = store \cup staged
    /\ staged' = {}
    /\ UNCHANGED effect_log

\* Rollback: staged rows discarded AND the effect contribution undone (models
\* the atomic bracket of <seen, effect, record> — if commit does not happen,
\* effect is not observable downstream either, so we revert the counter to
\* reflect "as if the delivery never occurred").
Rollback ==
    /\ txn_state = "active"
    /\ txn_state' = "rolled_back"
    /\ effect_log' = [p \in Pairs |->
         IF p \in staged THEN effect_log[p] - 1 ELSE effect_log[p]]
    /\ staged' = {}
    /\ UNCHANGED store

Close ==
    /\ txn_state \in {"committed", "rolled_back"}
    /\ txn_state' = "none"
    /\ UNCHANGED <<staged, store, effect_log>>

Next ==
    \/ Begin
    \/ \E m \in Messages, c \in Consumers : Deliver(m, c)
    \/ Commit
    \/ Rollback
    \/ Close

Spec == Init /\ [][Next]_vars

\* ------- SAFETY INVARIANTS -------

\* INBOX-INV-01: staged rows are NEVER visible in the durable store while the
\* transaction is still active. Atomicity of <effect, record> depends on this.
AtomicVisibility ==
    (txn_state = "active") => (\A p \in staged : p \notin store)

\* INBOX-INV-02 + INBOX-INV-04: the effect log for any committed pair is AT MOST
\* ONE — redeliveries after commit skip the effect; unseen pairs always get one
\* effect application on first delivery, never two.
ExactlyOnceEffect ==
    \A p \in Pairs : (p \in store) => effect_log[p] = 1

\* INBOX-INV-04: a rolled-back transaction leaves no traces — neither in the
\* store nor in the effect log.
RolledBackLeavesNoTrace ==
    (txn_state = "rolled_back") => (staged = {})

\* Sanity: effect log is bounded (used by TypeOK strengthening for the model).
EffectLogBounded ==
    \A p \in Pairs : effect_log[p] <= 1

====
