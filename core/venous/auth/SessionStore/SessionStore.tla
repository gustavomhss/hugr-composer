---- MODULE SessionStore ----
EXTENDS Naturals, FiniteSets

CONSTANTS Sids, Subjects, MaxTime

VARIABLES live, revoked, owner, created, idleExp, absExp, now

TypeOK ==
    /\ live \subseteq Sids
    /\ revoked \subseteq Sids
    /\ owner \in [Sids -> (Subjects \cup {"_"})]
    /\ created \in [Sids -> 0..MaxTime]
    /\ idleExp \in [Sids -> 0..MaxTime]
    /\ absExp \in [Sids -> 0..MaxTime]
    /\ now \in 0..MaxTime

Init ==
    /\ live = {}
    /\ revoked = {}
    /\ owner = [s \in Sids |-> "_"]
    /\ created = [s \in Sids |-> 0]
    /\ idleExp = [s \in Sids |-> 0]
    /\ absExp = [s \in Sids |-> 0]
    /\ now = 0

\* Mint a fresh session: s must be unused (not live AND not revoked).
Create(s, sub) ==
    /\ s \notin live
    /\ s \notin revoked
    /\ sub \in Subjects
    /\ now + 1 <= MaxTime
    /\ now + 2 <= MaxTime
    /\ live' = live \cup {s}
    /\ owner' = [owner EXCEPT ![s] = sub]
    /\ created' = [created EXCEPT ![s] = now]
    /\ idleExp' = [idleExp EXCEPT ![s] = now + 1]
    /\ absExp' = [absExp EXCEPT ![s] = now + 2]
    /\ UNCHANGED <<revoked, now>>

\* Load renews idle, but never past absolute (SESSION-INV-06).
Load(s) ==
    /\ s \in live
    /\ now < idleExp[s]
    /\ now < absExp[s]
    /\ idleExp' = [idleExp EXCEPT ![s] =
            IF now + 1 < absExp[s] THEN now + 1 ELSE absExp[s]]
    /\ UNCHANGED <<live, revoked, owner, created, absExp, now>>

\* Natural expiry drops the record but does NOT add to the revoked tombstone
\* set (matches the impl's _drop_record_locked).
Expire(s) ==
    /\ s \in live
    /\ \/ now >= idleExp[s]
       \/ now >= absExp[s]
    /\ live' = live \ {s}
    /\ UNCHANGED <<revoked, owner, created, idleExp, absExp, now>>

\* Rotate: mint new, burn old (SESSION-INV-02). Absolute ceiling inherited.
Rotate(old, new) ==
    /\ old \in live
    /\ new \notin live
    /\ new \notin revoked
    /\ new /= old
    /\ now < idleExp[old]
    /\ now < absExp[old]
    /\ live' = (live \ {old}) \cup {new}
    /\ revoked' = revoked \cup {old}
    /\ owner' = [owner EXCEPT ![new] = owner[old], ![old] = "_"]
    /\ created' = [created EXCEPT ![new] = created[old]]
    /\ idleExp' = [idleExp EXCEPT ![new] =
            IF now + 1 < absExp[old] THEN now + 1 ELSE absExp[old]]
    /\ absExp' = [absExp EXCEPT ![new] = absExp[old]]
    /\ UNCHANGED <<now>>

\* Revoke: tombstone + drop from live (SESSION-INV-03).
Revoke(s) ==
    /\ live' = live \ {s}
    /\ revoked' = revoked \cup {s}
    /\ UNCHANGED <<owner, created, idleExp, absExp, now>>

\* Revoke every live session for subject sub (SESSION-INV-05).
RevokeAllForSubject(sub) ==
    /\ sub \in Subjects
    /\ live' = {x \in live : owner[x] /= sub}
    /\ revoked' = revoked \cup {x \in live : owner[x] = sub}
    /\ UNCHANGED <<owner, created, idleExp, absExp, now>>

Tick ==
    /\ now + 1 <= MaxTime
    /\ now' = now + 1
    /\ UNCHANGED <<live, revoked, owner, created, idleExp, absExp>>

Next ==
    \/ \E s \in Sids, sub \in Subjects: Create(s, sub)
    \/ \E s \in Sids: Load(s)
    \/ \E s \in Sids: Expire(s)
    \/ \E old \in Sids, new \in Sids: Rotate(old, new)
    \/ \E s \in Sids: Revoke(s)
    \/ \E sub \in Subjects: RevokeAllForSubject(sub)
    \/ Tick

Spec == Init /\ [][Next]_<<live, revoked, owner, created, idleExp, absExp, now>>

\* ---------- SAFETY INVARIANTS ----------

\* SAFETY-1 (SESSION-INV-02): live and revoked tombstones are disjoint at all
\* times; a rotated/revoked id cannot be simultaneously resolvable.
LiveRevokedDisjoint == live \cap revoked = {}

\* SAFETY-2 (SESSION-INV-06): every live session has idle <= absolute, i.e. the
\* absolute clock is a hard ceiling that sliding-window renew cannot breach.
IdleBoundedByAbsolute == \A s \in live : idleExp[s] <= absExp[s]

\* SAFETY-3 (SESSION-INV-03): live sessions are not past their absolute clock;
\* if now has reached absExp[s], the session MUST have been expired.
NoLivePastAbsolute == \A s \in live : now < absExp[s]

====
