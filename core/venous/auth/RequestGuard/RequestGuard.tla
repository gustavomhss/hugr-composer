---- MODULE RequestGuard ----
EXTENDS Naturals, FiniteSets

CONSTANTS N
(* N = number of guards in the composite. *)

ASSUME N \in Nat /\ N >= 1

VARIABLES state, idx, outcome, handler_invoked

TypeOK ==
    /\ state \in {"open", "evaluating", "terminal_allow", "terminal_deny", "terminal_error"}
    /\ idx \in 0..N
    /\ outcome \in {"none", "allow", "deny", "error"}
    /\ handler_invoked \in BOOLEAN

Init ==
    /\ state = "open"
    /\ idx = 0
    /\ outcome = "none"
    /\ handler_invoked = FALSE

(* Begin evaluating *)
StartEval ==
    /\ state = "open"
    /\ state' = "evaluating"
    /\ UNCHANGED <<idx, outcome, handler_invoked>>

(* The current guard allows; advance to the next guard. *)
StepAllow ==
    /\ state = "evaluating"
    /\ idx < N
    /\ idx' = idx + 1
    /\ UNCHANGED <<state, outcome, handler_invoked>>

(* The current guard denies; terminate with deny. Handler NOT invoked. *)
StepDeny ==
    /\ state = "evaluating"
    /\ idx < N
    /\ idx' = idx + 1
    /\ state' = "terminal_deny"
    /\ outcome' = "deny"
    /\ UNCHANGED <<handler_invoked>>

(* The current guard raises; terminate with error. Handler NOT invoked. *)
StepError ==
    /\ state = "evaluating"
    /\ idx < N
    /\ idx' = idx + 1
    /\ state' = "terminal_error"
    /\ outcome' = "error"
    /\ UNCHANGED <<handler_invoked>>

(* All guards have been exhausted with allow → terminal_allow; handler runs. *)
FinishAllow ==
    /\ state = "evaluating"
    /\ idx = N
    /\ state' = "terminal_allow"
    /\ outcome' = "allow"
    /\ handler_invoked' = TRUE
    /\ UNCHANGED <<idx>>

(* Terminal stutter — no state transitions after terminal (RG-INV-04). *)
Terminal ==
    /\ state \in {"terminal_allow", "terminal_deny", "terminal_error"}
    /\ UNCHANGED <<state, idx, outcome, handler_invoked>>

Next ==
    \/ StartEval
    \/ StepAllow
    \/ StepDeny
    \/ StepError
    \/ FinishAllow
    \/ Terminal

Spec == Init /\ [][Next]_<<state, idx, outcome, handler_invoked>>

(* ------------------------------------------------------------------- *)
(* SAFETY INVARIANTS                                                    *)
(* ------------------------------------------------------------------- *)

(* RG-INV-01: a deny or error outcome NEVER coincides with a handler invocation. *)
DenyBlocksHandler ==
    (outcome \in {"deny", "error"}) => (handler_invoked = FALSE)

(* RG-INV-03: AND composition — handler runs iff every guard allowed. *)
AndComposition ==
    handler_invoked =>
        /\ state = "terminal_allow"
        /\ outcome = "allow"
        /\ idx = N

(* RG-INV-04: state is bounded — five discrete states, no others. *)
StateBounded ==
    state \in {"open", "evaluating", "terminal_allow", "terminal_deny", "terminal_error"}

(* RG-INV-05: error outcome and allow outcome are mutually exclusive. *)
ErrorDistinctFromAllow ==
    ~ (outcome = "allow" /\ state = "terminal_error")

====
