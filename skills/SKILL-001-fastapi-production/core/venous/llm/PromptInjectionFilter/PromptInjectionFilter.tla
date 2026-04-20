---- MODULE PromptInjectionFilter ----
EXTENDS Naturals, Sequences, FiniteSets

CONSTANTS Kinds, Bodies
ASSUME Kinds = {"user", "retrieved", "tool_output"}

VARIABLES audit, lastKind, lastWrapped

TypeOK ==
    /\ audit \in Seq(Kinds)
    /\ lastKind \in (Kinds \cup {"none"})
    /\ lastWrapped \in BOOLEAN

Init ==
    /\ audit = <<>>
    /\ lastKind = "none"
    /\ lastWrapped = FALSE

Quarantine(k) ==
    /\ k \in Kinds
    /\ audit' = Append(audit, k)
    /\ lastKind' = k
    /\ lastWrapped' = TRUE

Next == \E k \in Kinds: Quarantine(k)

Spec == Init /\ [][Next]_<<audit, lastKind, lastWrapped>>

\* Safety: every audit entry references an allowed kind (PIF-INV-04).
AuditKindsValid ==
    \A i \in 1..Len(audit): audit[i] \in Kinds

\* Safety: once a quarantine has completed the output was wrapped (PIF-INV-01).
LastWrappedAfterQuarantine ==
    (lastKind # "none") => (lastWrapped = TRUE)

\* Safety: state components are bounded and well-typed.
StateBounded ==
    /\ lastKind \in (Kinds \cup {"none"})
    /\ lastWrapped \in BOOLEAN

====
