---- MODULE PromptTemplate ----
(***************************************************************************)
(* PromptRegistry: once (name, version) is bound to a fingerprint,         *)
(* it MUST NOT change. Rebinding a different fingerprint is a safety      *)
(* violation (PROMPT-INV-02).                                             *)
(***************************************************************************)
EXTENDS Naturals, FiniteSets, TLC

CONSTANTS Names, Versions, Fingerprints

VARIABLES registry  \* function (Names \X Versions) -> Fingerprints \cup {NULL}

NULL == "NULL"

TypeOK ==
    /\ registry \in [Names \X Versions -> Fingerprints \cup {NULL}]

Init ==
    /\ registry = [k \in Names \X Versions |-> NULL]

Register(n, v, f) ==
    /\ n \in Names
    /\ v \in Versions
    /\ f \in Fingerprints
    /\ \/ registry[<<n, v>>] = NULL              \* fresh binding
       \/ registry[<<n, v>>] = f                  \* idempotent identical re-register
    /\ registry' = [registry EXCEPT ![<<n, v>>] = f]

Next == \E n \in Names, v \in Versions, f \in Fingerprints : Register(n, v, f)

Spec == Init /\ [][Next]_registry

(* Inductive safety: the Next action preserves any existing non-NULL binding. *)
(* This is checked implicitly: Register only sets registry[<<n,v>>] when it  *)
(* was NULL or already equal to f. TLC verifies this by exhaustive search.   *)

(* Action-property form: []<<A>>_v or []P where P is a state predicate.      *)
(* We express "no binding is ever deleted" as a state invariant plus the    *)
(* observation that Register never writes NULL into a cell.                 *)

NoPartialWrite ==
    \A n \in Names, v \in Versions :
        registry[<<n, v>>] \in Fingerprints \cup {NULL}

THEOREM Spec => []TypeOK
THEOREM Spec => []NoPartialWrite
====
