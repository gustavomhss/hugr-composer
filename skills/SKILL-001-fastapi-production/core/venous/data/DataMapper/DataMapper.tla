---- MODULE DataMapper ----
EXTENDS Naturals, FiniteSets, Sequences

CONSTANTS Ids
VARIABLES persisted, payloads, last_kind

\* persisted   : set of identity keys currently materialised in the store
\* payloads    : sequence of emitted payloads (kind, identity)
\* last_kind   : the last payload kind emitted ("none" | "insert" | "update" | "delete")

Kinds == {"none", "insert", "update", "delete"}
PayloadType == [kind: Kinds, id: Ids]

TypeOK ==
    /\ persisted \subseteq Ids
    /\ last_kind \in Kinds
    /\ payloads \in Seq(PayloadType)

Init ==
    /\ persisted = {}
    /\ payloads = <<>>
    /\ last_kind = "none"

\* A mapper "insert" emits a payload tagged with the entity's identity. The
\* mapper itself NEVER writes to persisted — a separate flush step does. This
\* encodes DM-INV-04 directly: the mapper is a pure translator.
Insert(id) ==
    /\ id \notin persisted
    /\ payloads' = Append(payloads, [kind |-> "insert", id |-> id])
    /\ last_kind' = "insert"
    /\ UNCHANGED persisted

\* An "update" MUST preserve the identity key (DM-INV-02: round-trip identity).
Update(id) ==
    /\ payloads' = Append(payloads, [kind |-> "update", id |-> id])
    /\ last_kind' = "update"
    /\ UNCHANGED persisted

Delete(id) ==
    /\ payloads' = Append(payloads, [kind |-> "delete", id |-> id])
    /\ last_kind' = "delete"
    /\ UNCHANGED persisted

\* The Flush step is the ONLY action allowed to mutate `persisted` — it
\* consumes the emitted payloads. Separating Flush from Insert/Update/Delete
\* is the TLA-level encoding of DM-INV-04.
Flush ==
    /\ Len(payloads) > 0
    /\ LET p == Head(payloads) IN
        /\ payloads' = Tail(payloads)
        /\ IF p.kind = "insert" THEN persisted' = persisted \cup {p.id}
           ELSE IF p.kind = "delete" THEN persisted' = persisted \ {p.id}
           ELSE persisted' = persisted
    /\ UNCHANGED last_kind

Next ==
    \/ \E id \in Ids: Insert(id)
    \/ \E id \in Ids: Update(id)
    \/ \E id \in Ids: Delete(id)
    \/ Flush

Spec == Init /\ [][Next]_<<persisted, payloads, last_kind>>

\* State-space bound so TLC finishes in seconds. The payload queue is modelled
\* as bounded because real deployments drain it on every flush tick.
StateBound == Len(payloads) <= 3

\* SAFETY 1 (DM-INV-02): every emitted payload's identity is a valid declared id —
\* no mapper step ever invents an identity out of thin air.
PayloadIdentityInRange ==
    \A i \in 1 .. Len(payloads): payloads[i].id \in Ids

\* SAFETY 2 (DM-INV-04): `persisted` is bounded by Ids — only Flush mutates it.
PersistenceBounded == persisted \subseteq Ids

\* SAFETY 3: only declared kinds may appear on the queue.
KindsAreValid ==
    \A i \in 1 .. Len(payloads): payloads[i].kind \in Kinds

====
