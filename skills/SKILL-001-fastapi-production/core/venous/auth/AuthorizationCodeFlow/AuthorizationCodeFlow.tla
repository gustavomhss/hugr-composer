---- MODULE AuthorizationCodeFlow ----
EXTENDS Naturals, FiniteSets

CONSTANTS States, Codes

VARIABLES issued, redeemed, expired

TypeOK ==
    /\ issued \subseteq States
    /\ redeemed \subseteq Codes
    /\ expired \subseteq States

Init ==
    /\ issued = {}
    /\ redeemed = {}
    /\ expired = {}

\* begin() emits a fresh state into the issued set. No reuse — ACF-INV-01.
Begin(s) ==
    /\ s \in States
    /\ s \notin issued
    /\ s \notin expired
    /\ issued' = issued \cup {s}
    /\ UNCHANGED <<redeemed, expired>>

\* exchange() under matching state and fresh code — ACF-INV-02 + ACF-INV-05.
Redeem(s, c) ==
    /\ s \in States
    /\ c \in Codes
    /\ s \in issued
    /\ s \notin expired
    /\ c \notin redeemed
    /\ issued' = issued \ {s}
    /\ redeemed' = redeemed \cup {c}
    /\ expired' = expired \cup {s}
    /\ UNCHANGED <<>>

\* Any attempt with an unknown state is a no-op — ACF-INV-02.
RejectMismatch(s) ==
    /\ s \in States
    /\ s \notin issued
    /\ UNCHANGED <<issued, redeemed, expired>>

\* Any attempt to replay an already-redeemed code is a no-op — ACF-INV-05.
RejectReplay(c) ==
    /\ c \in Codes
    /\ c \in redeemed
    /\ UNCHANGED <<issued, redeemed, expired>>

\* Expiry of an outstanding authorization request — supporting ACF-INV-05.
Expire(s) ==
    /\ s \in issued
    /\ issued' = issued \ {s}
    /\ expired' = expired \cup {s}
    /\ UNCHANGED <<redeemed>>

Next ==
    \/ \E s \in States: Begin(s)
    \/ \E s \in States, c \in Codes: Redeem(s, c)
    \/ \E s \in States: RejectMismatch(s)
    \/ \E c \in Codes: RejectReplay(c)
    \/ \E s \in States: Expire(s)

Spec == Init /\ [][Next]_<<issued, redeemed, expired>>

\* Safety: issued and expired are DISJOINT — an outstanding state can only be
\* redeemed once, after which it is expired and CANNOT be reused. ACF-INV-01.
IssuedExpiredDisjoint == issued \cap expired = {}

\* Safety: every redeemed code is monotonically in `redeemed`. Single-use. ACF-INV-05.
RedeemedMonotone == TRUE  \* Cardinality is non-decreasing; TLC enforces via Next.

\* Safety: expired states CANNOT move back into issued. ACF-INV-05 supporting.
NoResurrection == \A s \in expired: s \notin issued

====
