---- MODULE LifetimeScope ----
EXTENDS Naturals, FiniteSets, Sequences

CONSTANTS Keys, Scopes

VARIABLES registrations, singletons, scoped_map, scope_order, disposed

TypeOK ==
    /\ registrations \in [Keys -> {"none", "singleton", "scoped", "transient"}]
    /\ singletons \subseteq Keys
    /\ scoped_map \subseteq Keys
    /\ scope_order \in Seq(Keys)
    /\ disposed \in {TRUE, FALSE}

Init ==
    /\ registrations = [k \in Keys |-> "none"]
    /\ singletons = {}
    /\ scoped_map = {}
    /\ scope_order = <<>>
    /\ disposed = FALSE

Register(k, s) ==
    /\ ~disposed
    /\ registrations[k] = "none"
    /\ s \in {"singleton", "scoped", "transient"}
    /\ registrations' = [registrations EXCEPT ![k] = s]
    /\ UNCHANGED <<singletons, scoped_map, scope_order, disposed>>

ResolveSingleton(k) ==
    /\ ~disposed
    /\ registrations[k] = "singleton"
    /\ singletons' = singletons \cup {k}
    /\ UNCHANGED <<registrations, scoped_map, scope_order, disposed>>

ResolveScoped(k) ==
    /\ ~disposed
    /\ registrations[k] = "scoped"
    /\ k \notin scoped_map
    /\ scoped_map' = scoped_map \cup {k}
    /\ scope_order' = Append(scope_order, k)
    /\ UNCHANGED <<registrations, singletons, disposed>>

ResolveScopedCached(k) ==
    /\ ~disposed
    /\ registrations[k] = "scoped"
    /\ k \in scoped_map
    /\ UNCHANGED <<registrations, singletons, scoped_map, scope_order, disposed>>

ResolveTransient(k) ==
    /\ ~disposed
    /\ registrations[k] = "transient"
    /\ UNCHANGED <<registrations, singletons, scoped_map, scope_order, disposed>>

Dispose ==
    /\ ~disposed
    /\ scoped_map' = {}
    /\ scope_order' = <<>>
    /\ disposed' = TRUE
    /\ UNCHANGED <<registrations, singletons>>

Terminal ==
    /\ disposed = TRUE
    /\ UNCHANGED <<registrations, singletons, scoped_map, scope_order, disposed>>

Next ==
    \/ \E k \in Keys, s \in {"singleton", "scoped", "transient"}: Register(k, s)
    \/ \E k \in Keys: ResolveSingleton(k)
    \/ \E k \in Keys: ResolveScoped(k)
    \/ \E k \in Keys: ResolveScopedCached(k)
    \/ \E k \in Keys: ResolveTransient(k)
    \/ Dispose
    \/ Terminal

Spec == Init /\ [][Next]_<<registrations, singletons, scoped_map, scope_order, disposed>>

\* LS-INV-01: singletons only hold singleton-declared keys (identity consistency).
SingletonConsistent ==
    \A k \in singletons: registrations[k] = "singleton"

\* LS-INV-02: after disposal, the scope map is empty and scope_order is empty.
DisposedScopeEmpty ==
    disposed => (scoped_map = {} /\ scope_order = <<>>)

\* LS-INV-03: transients leave no trace in scoped_map or scope_order.
TransientLeavesNoTrace ==
    \A k \in Keys: (registrations[k] = "transient") => (k \notin scoped_map)

\* LS-INV-05: registration values are bounded by the closed enum.
RegistrationBounded ==
    \A k \in Keys: registrations[k] \in {"none", "singleton", "scoped", "transient"}

\* Scope order items are a subset of the scoped map (every queued dispose
\* has a corresponding live scoped instance) — supports LIFO correctness.
ScopeOrderSoundness ==
    \A i \in DOMAIN scope_order: scope_order[i] \in scoped_map

====
