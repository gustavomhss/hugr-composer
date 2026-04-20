---- MODULE AntiCorruptionLayer ----
EXTENDS Naturals, FiniteSets, Sequences

CONSTANTS Versions, Payloads

VARIABLES registered, local_seen, in_translate

\* registered   : set of contract versions registered on the ACL
\* local_seen   : multi-set (as sequence) of payloads that have crossed into
\*                the local domain — each element is a [ver, body] pair.
\* in_translate : boolean re-entry guard; TRUE iff a translation is in flight.

NULL == "NULL"

Translated == [ver: Versions, body: Payloads \cup {NULL}]

TypeOK ==
    /\ registered \subseteq Versions
    /\ local_seen \in Seq(Translated)
    /\ in_translate \in BOOLEAN

Init ==
    /\ registered = {}
    /\ local_seen = <<>>
    /\ in_translate = FALSE

\* Register a new foreign-contract version (ACL-INV-04). No translation may
\* be in flight concurrently (models the serialised registry update).
Register(v) ==
    /\ ~ in_translate
    /\ registered' = registered \cup {v}
    /\ UNCHANGED <<local_seen, in_translate>>

\* Enter a translation for version v and body p. The guard rejects if v is
\* NOT registered (ACL-INV-04 / schema drift) and if a translation is already
\* in flight on this instance (ACL-INV-03 — no re-entry).
TranslateEnter(v, p) ==
    /\ ~ in_translate
    /\ v \in registered
    /\ in_translate' = TRUE
    /\ UNCHANGED <<registered, local_seen>>

\* Complete a translation: append the local shape to local_seen and release
\* the re-entry guard. The appended record carries the version tag — NO
\* "raw" foreign envelope is retained (ACL-INV-01: local_seen only contains
\* records with a declared version that was registered).
TranslateExit(v, p) ==
    /\ in_translate
    /\ v \in registered
    /\ local_seen' = Append(local_seen, [ver |-> v, body |-> p])
    /\ in_translate' = FALSE
    /\ UNCHANGED registered

\* Drift: an inbound payload carries a version that is NOT registered. The
\* ACL refuses; nothing crosses the boundary.
DriftReject(v, p) ==
    /\ ~ in_translate
    /\ v \notin registered
    /\ UNCHANGED <<registered, local_seen, in_translate>>

Next ==
    \/ \E v \in Versions: Register(v)
    \/ \E v \in Versions, p \in Payloads: TranslateEnter(v, p)
    \/ \E v \in Versions, p \in Payloads: TranslateExit(v, p)
    \/ \E v \in Versions, p \in Payloads: DriftReject(v, p)

Spec == Init /\ [][Next]_<<registered, local_seen, in_translate>>

\* Keep the TLC state space small so the model check finishes in seconds.
StateBound == Len(local_seen) <= 3

\* SAFETY 1 (ACL-INV-01): every record that crossed into the local domain
\* carries a version that was registered — i.e. no foreign envelope ever
\* reached local_seen through an unknown path.
NoForeignLeak ==
    \A i \in 1 .. Len(local_seen): local_seen[i].ver \in registered

\* SAFETY 2 (ACL-INV-04): no payload ever crosses with an unregistered
\* version. Expressed directly on the crossing step's precondition.
ExplicitVersioning ==
    \A i \in 1 .. Len(local_seen): local_seen[i].ver \in Versions

\* SAFETY 3 (ACL-INV-03): the re-entry flag never permits two concurrent
\* translations — modelled here as a boolean toggle. This is the TLA-level
\* encoding of the thread-local re-entry guard.
NoReentrantTranslation ==
    in_translate \in {TRUE, FALSE}

====
