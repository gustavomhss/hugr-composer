---- MODULE DiContainer ----
EXTENDS Naturals, FiniteSets

CONSTANTS Ifaces, Scopes

VARIABLES registrations, singletons, scoped_map, disposed, resolving

TypeOK ==
    /\ registrations \in [Ifaces -> {"none"} \cup {"singleton", "scoped", "transient"}]
    /\ singletons \subseteq Ifaces
    /\ scoped_map \subseteq Ifaces
    /\ disposed \in {TRUE, FALSE}
    /\ resolving \subseteq Ifaces

Init ==
    /\ registrations = [i \in Ifaces |-> "none"]
    /\ singletons = {}
    /\ scoped_map = {}
    /\ disposed = FALSE
    /\ resolving = {}

Register(i, s) ==
    /\ ~disposed
    /\ registrations[i] = "none"
    /\ s \in {"singleton", "scoped", "transient"}
    /\ registrations' = [registrations EXCEPT ![i] = s]
    /\ UNCHANGED <<singletons, scoped_map, disposed, resolving>>

BeginResolve(i) ==
    /\ ~disposed
    /\ registrations[i] # "none"
    /\ i \notin resolving
    /\ resolving' = resolving \cup {i}
    /\ UNCHANGED <<registrations, singletons, scoped_map, disposed>>

FinishResolveSingleton(i) ==
    /\ ~disposed
    /\ i \in resolving
    /\ registrations[i] = "singleton"
    /\ singletons' = singletons \cup {i}
    /\ resolving' = resolving \ {i}
    /\ UNCHANGED <<registrations, scoped_map, disposed>>

FinishResolveScoped(i) ==
    /\ ~disposed
    /\ i \in resolving
    /\ registrations[i] = "scoped"
    /\ scoped_map' = scoped_map \cup {i}
    /\ resolving' = resolving \ {i}
    /\ UNCHANGED <<registrations, singletons, disposed>>

FinishResolveTransient(i) ==
    /\ ~disposed
    /\ i \in resolving
    /\ registrations[i] = "transient"
    /\ resolving' = resolving \ {i}
    /\ UNCHANGED <<registrations, singletons, scoped_map, disposed>>

Dispose ==
    /\ ~disposed
    /\ resolving = {}
    /\ scoped_map' = {}
    /\ disposed' = TRUE
    /\ UNCHANGED <<registrations, singletons, resolving>>

Next ==
    \/ \E i \in Ifaces, s \in {"singleton", "scoped", "transient"}: Register(i, s)
    \/ \E i \in Ifaces: BeginResolve(i)
    \/ \E i \in Ifaces: FinishResolveSingleton(i)
    \/ \E i \in Ifaces: FinishResolveScoped(i)
    \/ \E i \in Ifaces: FinishResolveTransient(i)
    \/ Dispose

Spec == Init /\ [][Next]_<<registrations, singletons, scoped_map, disposed, resolving>>

\* DI-INV-01: an iface CANNOT appear in resolving twice (no re-entry).
NoReentry == \A i \in Ifaces: (i \in resolving) => (registrations[i] # "none")

\* DI-INV-02: singletons only hold registrations that are singletons.
SingletonScopeConsistent ==
    \A i \in singletons: registrations[i] = "singleton"

\* DI-INV-03: after dispose, the scoped map is empty.
DisposedIsEmpty == disposed => (scoped_map = {})

\* DI-INV-04: a registration never transitions to a different scope once set.
RegistrationBounded ==
    \A i \in Ifaces: registrations[i] \in {"none", "singleton", "scoped", "transient"}

====
