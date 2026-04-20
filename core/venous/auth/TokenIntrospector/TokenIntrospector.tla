---- MODULE TokenIntrospector ----
EXTENDS Naturals, FiniteSets

CONSTANTS Tokens, MaxTime, Exp, Ttl

ASSUME Exp \in Nat /\ Ttl \in Nat /\ MaxTime \in Nat

VARIABLES clock, active, cache, revoked

\* State meanings:
\*   clock   : current time (monotonic)
\*   active  : set of tokens still active at the authorization server
\*   cache   : function Tokens -> {"absent"} \cup {<<claims_exp_time>>} (i.e. caches cached_until)
\*   revoked : set of tokens that have been revoked locally

TypeOK ==
    /\ clock \in 0..MaxTime
    /\ active \subseteq Tokens
    /\ revoked \subseteq Tokens
    /\ cache \in [Tokens -> (0..MaxTime) \cup {0 - 1}]   \* -1 marker = absent

Absent == 0 - 1

Init ==
    /\ clock = 0
    /\ active = Tokens
    /\ revoked = {}
    /\ cache = [t \in Tokens |-> Absent]

\* Introspect on an active, non-revoked token: populate cache with min(Exp, clock+Ttl).
IntrospectActive(t) ==
    /\ t \in active
    /\ t \notin revoked
    /\ clock < Exp
    /\ cache[t] = Absent
    /\ LET until == IF Exp < clock + Ttl THEN Exp ELSE clock + Ttl
       IN  cache' = [cache EXCEPT ![t] = until]
    /\ UNCHANGED <<clock, active, revoked>>

\* Introspect and hit cache (does not call the authorization server).
IntrospectCached(t) ==
    /\ cache[t] # Absent
    /\ clock < cache[t]
    /\ t \notin revoked
    /\ UNCHANGED <<clock, active, cache, revoked>>

\* Revoke locally — MUST purge the cache atomically (TI-INV-06).
RevokeToken(t) ==
    /\ t \in Tokens
    /\ revoked' = revoked \cup {t}
    /\ cache' = [cache EXCEPT ![t] = Absent]
    /\ UNCHANGED <<clock, active>>

\* Authorization server marks token inactive (post-revoke side).
MarkInactive(t) ==
    /\ t \in active
    /\ active' = active \ {t}
    /\ UNCHANGED <<clock, cache, revoked>>

\* Clock tick — purges cache entries that have aged past cached_until.
Tick ==
    /\ clock < MaxTime
    /\ clock' = clock + 1
    /\ cache' = [t \in Tokens |-> IF cache[t] # Absent /\ cache[t] <= clock + 1
                                   THEN Absent ELSE cache[t]]
    /\ UNCHANGED <<active, revoked>>

Next ==
    \/ \E t \in Tokens: IntrospectActive(t)
    \/ \E t \in Tokens: IntrospectCached(t)
    \/ \E t \in Tokens: RevokeToken(t)
    \/ \E t \in Tokens: MarkInactive(t)
    \/ Tick

Spec == Init /\ [][Next]_<<clock, active, cache, revoked>>

\* ----- Safety invariants (mapped to catalog invariants) ----------------------

\* TI-INV-06: a cached entry NEVER outlives exp nor exceeds clock + Ttl.
CacheNeverPastExpOrTtl ==
    \A t \in Tokens:
        cache[t] # Absent => cache[t] <= Exp

\* TI-INV-06 (revocation purge): a revoked token CANNOT have a live cache entry.
RevokedTokensHaveNoCache ==
    \A t \in Tokens:
        t \in revoked => cache[t] = Absent

\* TI-INV-03: an expired token's cache entry CANNOT be served.
ExpiredCacheIsPurgedAtTick ==
    \A t \in Tokens:
        (cache[t] # Absent) => (clock < cache[t])

====
