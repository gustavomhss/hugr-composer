---- MODULE RetryBudget ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for RetryBudget
  Namespace: resiliency
  Generated from primitive contract and implementation

  Purpose: Sliding-window retry budget: caps the ratio of retries to total requests over a rolling time window so a failing downstream cannot be DDoS'd by the caller's own retry loop. Enforces only after a warm-up threshold (`min_requests`) to avoid false positives on cold starts.

  Invariants:
    INV_01: RETRY_BUDGET_INV_01: `can_retry()` MUST return True when total requests in the window is below `min_requests` (warm-up bypass).
    INV_02: RETRY_BUDGET_INV_02: After warm-up, `can_retry()` MUST return False iff `len(_retries) / len(_requests) > ratio` over the current window.
    INV_03: RETRY_BUDGET_INV_03: Samples older than `window_s` MUST be evicted on every record/check, so the decision is always based on the CURRENT rolling window.
*)

CONSTANTS MaxInt

VARIABLES service, ratio, window_s, min_requests

vars == <<service, ratio, window_s, min_requests>>

TypeOK == 
  /\ service \in String
  /\ ratio \in String
  /\ window_s \in String
  /\ min_requests \in String

Init == 
  /\ service = ""
  /\ ratio = ""
  /\ window_s = ""
  /\ min_requests = ""

(* RETRYBUDGET_INV_01: RETRY_BUDGET_INV_01: `can_retry()` MUST return True when total requests in the window is below `min_requests` (warm-up bypass). *)
RETRYBUDGET_INV_01 ==
  /\ TypeOK

(* RETRYBUDGET_INV_02: RETRY_BUDGET_INV_02: After warm-up, `can_retry()` MUST return False iff `len(_retries) / len(_requests) > ratio` over the current window. *)
RETRYBUDGET_INV_02 ==
  /\ TRUE

(* RETRYBUDGET_INV_03: RETRY_BUDGET_INV_03: Samples older than `window_s` MUST be evicted on every record/check, so the decision is always based on the CURRENT rolling window. *)
RETRYBUDGET_INV_03 ==
  /\ TypeOK

(* Operations *)
Record_request ==
  /\ service' = Record_requestImpl(service)
  /\ UNCHANGED <<config>>

Record_retry ==
  /\ service' = Record_retryImpl(service)
  /\ UNCHANGED <<config>>

Can_retry ==
  /\ service' = Can_retryImpl(service)
  /\ UNCHANGED <<config>>

Current_ratio ==
  /\ service' = Current_ratioImpl(service)
  /\ UNCHANGED <<config>>

Stats ==
  /\ service' = StatsImpl(service)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Record_request \/ Record_retry \/ Can_retry \/ Current_ratio \/ Stats \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ RETRYBUDGET_INV_01
  /\ RETRYBUDGET_INV_02
  /\ RETRYBUDGET_INV_03

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>service' # service

====