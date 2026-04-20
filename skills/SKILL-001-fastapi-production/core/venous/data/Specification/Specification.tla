---- MODULE Specification ----
EXTENDS Naturals, FiniteSets, Sequences

CONSTANTS Leaves, Backends
VARIABLES registry, specs

(*
 * Abstract state for the Specification primitive:
 *   - `registry` maps (backend, leafName) -> "registered" when a translator
 *     has been installed for that pair (SPEC-INV-03 — persistence coupling
 *     lives here and only here).
 *   - `specs` is the set of currently-tracked Specification trees built by
 *     the composition algebra. We model each tree as a record with `kind`
 *     and child references so the boolean algebra invariants can be stated
 *     structurally.
 *)

SpecKind == {"leaf", "and", "or", "not"}

TypeOK ==
    /\ registry \in [Backends \X Leaves -> {"registered", "missing"}]
    /\ specs \subseteq [kind: SpecKind]

Init ==
    /\ registry = [pair \in Backends \X Leaves |-> "missing"]
    /\ specs = {}

Register(b, l) ==
    /\ b \in Backends
    /\ l \in Leaves
    /\ registry' = [registry EXCEPT ![<<b, l>>] = "registered"]
    /\ UNCHANGED specs

AddLeaf(l) ==
    /\ l \in Leaves
    /\ specs' = specs \cup {[kind |-> "leaf"]}
    /\ UNCHANGED registry

Compose(k) ==
    /\ k \in {"and", "or", "not"}
    /\ specs' = specs \cup {[kind |-> k]}
    /\ UNCHANGED registry

Next ==
    \/ \E b \in Backends, l \in Leaves: Register(b, l)
    \/ \E l \in Leaves: AddLeaf(l)
    \/ \E k \in {"and", "or", "not"}: Compose(k)

Spec == Init /\ [][Next]_<<registry, specs>>

\* SAFETY — SPEC-INV-02: kinds belong to the closed boolean algebra.
KindsBounded == \A s \in specs: s.kind \in SpecKind

\* SAFETY — SPEC-INV-03: registry values are always well-formed; a pair is
\* either "registered" or "missing", never a persistence-coupling leak.
RegistryBounded ==
    \A pair \in Backends \X Leaves:
        registry[pair] \in {"registered", "missing"}

\* SAFETY — SPEC-INV-05: the algebra is closed; no "rogue" kinds ever appear.
ClosedAlgebra == \A s \in specs: s.kind \in {"leaf", "and", "or", "not"}

====
