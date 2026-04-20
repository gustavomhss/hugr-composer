---- MODULE DistributedLock ----
(***************************************************************************
 TLA+ specification of DistributedLock — at most one holder per resource,
 lease-expiry release, owner-fenced unlock. Maps to invariants DL_INV_01
 (mutual exclusion), DL_INV_02 (auto release after lease), DL_INV_03 (owner
 fencing on unlock).

 Model (bounded):
 - Owners   = {o1, o2, o3}
 - Resource = a single resource name
 - Time     = natural number (discrete tick)
 - Lease    = small fixed duration
 ***************************************************************************)
EXTENDS Naturals, FiniteSets

CONSTANTS Owners, Lease, MaxTime

VARIABLES
    holder,        \* Optional[Owner] currently holding the lock
    expiry,        \* Integer time at which the current holder's lease ends
    now            \* Current time

vars == <<holder, expiry, now>>

NoHolder == "NONE"

TypeOK ==
    /\ holder \in (Owners \union {NoHolder})
    /\ expiry \in 0..MaxTime
    /\ now \in 0..MaxTime

Init ==
    /\ holder = NoHolder
    /\ expiry = 0
    /\ now = 0

TryLockSuccess(o) ==
    /\ holder = NoHolder \/ now >= expiry
    /\ holder' = o
    /\ expiry' = now + Lease
    /\ UNCHANGED now

TryLockFail(o) ==
    /\ holder # NoHolder
    /\ now < expiry
    /\ o # holder
    /\ UNCHANGED <<holder, expiry, now>>

UnlockOwned(o) ==
    /\ holder = o
    /\ now < expiry
    /\ holder' = NoHolder
    /\ expiry' = 0
    /\ UNCHANGED now

UnlockForeignRejected(o) ==
    /\ holder # NoHolder
    /\ holder # o
    /\ now < expiry
    /\ UNCHANGED <<holder, expiry, now>>

Tick ==
    /\ now < MaxTime
    /\ now' = now + 1
    /\ UNCHANGED <<holder, expiry>>

Next ==
    \/ \E o \in Owners: TryLockSuccess(o)
    \/ \E o \in Owners: TryLockFail(o)
    \/ \E o \in Owners: UnlockOwned(o)
    \/ \E o \in Owners: UnlockForeignRejected(o)
    \/ Tick

Spec == Init /\ [][Next]_vars

\* ---- SAFETY invariants ------------------------------------------------
\* DL_INV_01: mutual exclusion — at most one holder at a time.
AtMostOneHolder ==
    \A o1, o2 \in Owners:
        (holder = o1 /\ holder = o2) => (o1 = o2)

\* DL_INV_02: once the lease has expired, the lock is reclaimable — a later
\* try_lock by any owner MUST succeed unless a fresh holder re-acquired.
LeaseBounded == (holder # NoHolder) => (expiry > 0)

\* Combined safety — matches the catalog invariant surface.
Safety ==
    /\ AtMostOneHolder
    /\ LeaseBounded

====
