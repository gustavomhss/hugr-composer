---- MODULE IdempotentConsumer ----
EXTENDS Naturals, FiniteSets

CONSTANTS Keys, MaxDuplicates

VARIABLES
    cache,        \* set of keys for which a cached outcome exists (committed)
    inbox,        \* set of keys durably recorded (committed) in the inbox
    outbox,       \* set of keys that have produced ≥1 outbox message (bounded)
    effect_log,   \* set of keys whose business effect has run (bounded)
    duplicates    \* function: key -> 0..MaxDuplicates, bounded redelivery counter

vars == <<cache, inbox, outbox, effect_log, duplicates>>

TypeOK ==
    /\ cache \subseteq Keys
    /\ inbox \subseteq Keys
    /\ outbox \subseteq Keys
    /\ effect_log \subseteq Keys
    /\ duplicates \in [Keys -> 0..MaxDuplicates]

Init ==
    /\ cache = {}
    /\ inbox = {}
    /\ outbox = {}
    /\ effect_log = {}
    /\ duplicates = [k \in Keys |-> 0]

\* First delivery: key is not in the cache. The business effect runs, the
\* outbox row lands, the inbox record is written, the cache is updated —
\* ATOMICALLY (models the nested inbox/outbox transaction bracket).
FirstDeliver(k) ==
    /\ k \notin cache
    /\ cache' = cache \cup {k}
    /\ inbox' = inbox \cup {k}
    /\ outbox' = outbox \cup {k}
    /\ effect_log' = effect_log \cup {k}
    /\ UNCHANGED duplicates

\* Redelivery: key is in the cache. on_duplicate runs (bounded counter
\* increments). No new effect, no new outbox row, no new inbox record.
Redeliver(k) ==
    /\ k \in cache
    /\ duplicates[k] < MaxDuplicates
    /\ duplicates' = [duplicates EXCEPT ![k] = duplicates[k] + 1]
    /\ UNCHANGED <<cache, inbox, outbox, effect_log>>

\* Handler fault: first delivery attempt aborts ATOMICALLY. The cache,
\* inbox and outbox stay unchanged — a retry is equivalent to a fresh
\* first delivery.
Abort(k) ==
    /\ k \notin cache
    /\ UNCHANGED vars

\* Stutter step: once every key is cached and every duplicate counter is
\* maxed out, the system idles. Modelled explicitly so TLC does not flag a
\* deadlock at the saturated state.
Idle ==
    /\ cache = Keys
    /\ \A k \in Keys : duplicates[k] = MaxDuplicates
    /\ UNCHANGED vars

Next ==
    \/ \E k \in Keys : FirstDeliver(k)
    \/ \E k \in Keys : Redeliver(k)
    \/ \E k \in Keys : Abort(k)
    \/ Idle

Spec == Init /\ [][Next]_vars

\* ------- SAFETY INVARIANTS -------

\* IDC-INV-01: exactly-once effect per committed key. Keys not in the cache
\* have never had an effect. Keys in the cache have had exactly one.
ExactlyOnceEffect ==
    effect_log = cache

\* IDC-INV-02: inbox and cache agree — every cached key is inbox-recorded,
\* and vice versa. This is the catalog's 'inbox-gates-effect' contract.
InboxGatesCache ==
    cache = inbox

\* IDC-INV-04: every outbox row corresponds to a committed (cached) key;
\* outputs NEVER leak ahead of the inbox record.
OutboxNeverLeaks ==
    outbox \subseteq cache

\* IDC-INV-03: duplicate counter only grows for keys that have already
\* been cached (on_duplicate is a steady-state path).
DuplicatesOnlyAfterCache ==
    \A k \in Keys : (duplicates[k] > 0) => (k \in cache)

====
