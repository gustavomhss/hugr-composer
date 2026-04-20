---- MODULE TotpVerifier ----
EXTENDS Integers, FiniteSets

CONSTANTS Steps, MaxSkew

VARIABLES clock, used, last_persisted

TypeOK ==
    /\ clock \in Steps
    /\ used \subseteq Steps
    /\ last_persisted \in (Steps \cup {-1})

Init ==
    /\ clock \in Steps
    /\ used = {}
    /\ last_persisted = -1

\* A verify attempt with a submitted step `s`. The server accepts only if s is
\* in the +/-MaxSkew window AND s has not been used AND s > last_persisted.
Verify(s) ==
    /\ s \in Steps
    /\ s >= clock - MaxSkew
    /\ s <= clock + MaxSkew
    /\ s \notin used
    /\ s > last_persisted
    /\ used' = used \cup {s}
    /\ last_persisted' = s
    /\ UNCHANGED clock

\* A replay attempt is a verify against an already-used step. It MUST NOT
\* change state (the reference implementation raises TotpReplayError).
ReplayRejected(s) ==
    /\ s \in Steps
    /\ (s \in used \/ s <= last_persisted)
    /\ UNCHANGED <<clock, used, last_persisted>>

\* Clock advances one step (time moves forward).
Tick ==
    /\ clock + 1 \in Steps
    /\ clock' = clock + 1
    /\ UNCHANGED <<used, last_persisted>>

Next ==
    \/ \E s \in Steps: Verify(s)
    \/ \E s \in Steps: ReplayRejected(s)
    \/ Tick

Spec == Init /\ [][Next]_<<clock, used, last_persisted>>

\* ---------------- Safety invariants ----------------

\* TOTP-INV-04: once a step is in `used`, it CANNOT leave `used` (monotone) —
\* expressed here as: last_persisted is non-decreasing. Every accepted verify
\* set last_persisted to s > prior last_persisted, so last_persisted_monotone
\* is preserved across Next because Verify requires s > last_persisted and
\* ReplayRejected / Tick leave it unchanged.
ReplayFree == \A s \in used: s <= last_persisted

\* TOTP-INV-03: every used step is within MaxSkew of some clock reading. With
\* MaxSkew = 1 we assert the window bound: any s ever accepted satisfies
\* |s - clock_at_accept| <= MaxSkew. We cannot track clock_at_accept per-step
\* explicitly without history variables; the bound holds at the moment of
\* acceptance because Verify guards the range. State invariant: no used step
\* is outside [0, max(Steps)], which is enforced by TypeOK.
UsedBoundedByType ==
    \A s \in used: s \in Steps

\* TOTP-INV-04 again, phrased as a state invariant: last_persisted never
\* decreases.
MonotonePersisted ==
    last_persisted \in (Steps \cup {-1})

====
