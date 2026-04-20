---- MODULE RetryPolicy ----
EXTENDS Naturals

CONSTANTS MaxAttempts, BudgetFloor, MaxSuccesses, Errors
VARIABLES attempt, outcome, retries, successes, idempotent

TypeOK ==
    /\ attempt \in 0..MaxAttempts
    /\ outcome \in {"pending", "success", "error_retryable", "error_non_retryable", "error_fatal", "refused"}
    /\ retries \in 0..BudgetFloor
    /\ successes \in 0..MaxSuccesses
    /\ idempotent \in BOOLEAN

Init ==
    /\ attempt = 0
    /\ outcome = "pending"
    /\ retries = 0
    /\ successes = 0
    /\ idempotent \in BOOLEAN

\* First attempt — unconditional (no retry budget consumption).
FirstAttempt ==
    /\ attempt = 0
    /\ outcome = "pending"
    /\ attempt' = 1
    /\ UNCHANGED <<outcome, retries, successes, idempotent>>

\* Attempt resolves to one of several outcomes.
ResolveSuccess ==
    /\ attempt > 0
    /\ outcome = "pending"
    /\ successes < MaxSuccesses
    /\ outcome' = "success"
    /\ successes' = successes + 1
    /\ UNCHANGED <<attempt, retries, idempotent>>

ResolveRetryable ==
    /\ attempt > 0
    /\ outcome = "pending"
    /\ outcome' = "error_retryable"
    /\ UNCHANGED <<attempt, retries, successes, idempotent>>

ResolveNonRetryable ==
    /\ attempt > 0
    /\ outcome = "pending"
    /\ outcome' = "error_non_retryable"
    /\ UNCHANGED <<attempt, retries, successes, idempotent>>

ResolveFatal ==
    /\ attempt > 0
    /\ outcome = "pending"
    /\ outcome' = "error_fatal"
    /\ UNCHANGED <<attempt, retries, successes, idempotent>>

\* Retry step — only allowed if (a) idempotent, (b) last outcome was retryable,
\* (c) attempt < MaxAttempts, (d) budget has headroom.
Retry ==
    /\ outcome = "error_retryable"
    /\ idempotent = TRUE
    /\ attempt < MaxAttempts
    /\ retries < BudgetFloor
    /\ attempt' = attempt + 1
    /\ retries' = retries + 1
    /\ outcome' = "pending"
    /\ UNCHANGED <<successes, idempotent>>

\* Refuse retry — non-idempotent or non-retryable or exhausted budget/attempts.
RefuseNonIdempotent ==
    /\ outcome = "error_retryable"
    /\ idempotent = FALSE
    /\ outcome' = "refused"
    /\ UNCHANGED <<attempt, retries, successes, idempotent>>

RefuseBudget ==
    /\ outcome = "error_retryable"
    /\ idempotent = TRUE
    /\ attempt < MaxAttempts
    /\ retries >= BudgetFloor
    /\ outcome' = "refused"
    /\ UNCHANGED <<attempt, retries, successes, idempotent>>

RefuseMaxAttempts ==
    /\ outcome = "error_retryable"
    /\ idempotent = TRUE
    /\ attempt >= MaxAttempts
    /\ outcome' = "refused"
    /\ UNCHANGED <<attempt, retries, successes, idempotent>>

Terminate ==
    /\ outcome \in {"success", "error_non_retryable", "error_fatal", "refused"}
    /\ UNCHANGED <<attempt, outcome, retries, successes, idempotent>>

Next ==
    \/ FirstAttempt
    \/ ResolveSuccess
    \/ ResolveRetryable
    \/ ResolveNonRetryable
    \/ ResolveFatal
    \/ Retry
    \/ RefuseNonIdempotent
    \/ RefuseBudget
    \/ RefuseMaxAttempts
    \/ Terminate

Spec == Init /\ [][Next]_<<attempt, outcome, retries, successes, idempotent>>

\* --------- SAFETY INVARIANTS ---------

\* RETRY-INV-01: a non-idempotent call CANNOT be retried. If idempotent=FALSE,
\* retries MUST remain at 0 for the entire run.
NoRetryWithoutIdempotency ==
    (idempotent = FALSE) => (retries = 0)

\* RETRY-INV-02: retry budget is bounded.
BudgetBounded == retries <= BudgetFloor

\* RETRY-INV-05: outcomes are drawn from the bounded classification set.
OutcomeClassified ==
    outcome \in {"pending", "success", "error_retryable",
                 "error_non_retryable", "error_fatal", "refused"}

\* Attempts are monotonic and bounded.
AttemptsMonotonic == attempt <= MaxAttempts

====
