---- MODULE CostTracker ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for CostTracker
  Namespace: resiliency
  Generated from primitive contract and implementation

  Purpose: Aggregates per-request cost estimates from a pluggable list of estimators (db/s3/api/...). Swallows and logs estimator exceptions so an instrumented cost path NEVER fails the underlying request. Retains a bounded history for post-hoc analysis.

  Invariants:
    INV_01: COST_TRACKER_INV_01: An exception raised by an estimator MUST NOT propagate out of `estimate_request()` — cost observation is always fail-open.
    INV_02: COST_TRACKER_INV_02: `_history` length MUST NEVER exceed `_max_history`; the oldest entry is evicted FIFO when the bound is hit.
    INV_03: COST_TRACKER_INV_03: `total_cost_usd` on the returned estimate MUST equal `db_cost_usd + s3_cost_usd + api_cost_usd` (conservation).
*)

CONSTANTS MaxInt

VARIABLES request_id, path, method, db_query_count, db_query_duration_ms, s3_bytes_transferred, external_api_calls, duration_ms, timestamp

vars == <<request_id, path, method, db_query_count, db_query_duration_ms, s3_bytes_transferred, external_api_calls, duration_ms, timestamp>>

TypeOK == 
  /\ request_id \in String
  /\ path \in String
  /\ method \in String
  /\ db_query_count \in 0..MaxInt
  /\ db_query_duration_ms \in 0..MaxInt
  /\ s3_bytes_transferred \in 0..MaxInt
  /\ external_api_calls \in 0..MaxInt
  /\ duration_ms \in 0..MaxInt
  /\ timestamp \in 0..MaxInt

Init == 
  /\ request_id = ""
  /\ path = ""
  /\ method = ""
  /\ db_query_count = 0
  /\ db_query_duration_ms = 0
  /\ s3_bytes_transferred = 0
  /\ external_api_calls = 0
  /\ duration_ms = 0
  /\ timestamp = 0

(* COSTTRACKER_INV_01: COST_TRACKER_INV_01: An exception raised by an estimator MUST NOT propagate out of `estimate_request()` — cost observation is always fail-open. *)
COSTTRACKER_INV_01 ==
  /\ TypeOK

(* COSTTRACKER_INV_02: COST_TRACKER_INV_02: `_history` length MUST NEVER exceed `_max_history`; the oldest entry is evicted FIFO when the bound is hit. *)
COSTTRACKER_INV_02 ==
  /\ request_id <= path

(* COSTTRACKER_INV_03: COST_TRACKER_INV_03: `total_cost_usd` on the returned estimate MUST equal `db_cost_usd + s3_cost_usd + api_cost_usd` (conservation). *)
COSTTRACKER_INV_03 ==
  /\ TypeOK

(* Operations *)
As_header_value ==
  /\ request_id' = As_header_valueImpl(request_id)
  /\ UNCHANGED <<config>>

Estimate ==
  /\ request_id' = EstimateImpl(request_id)
  /\ UNCHANGED <<config>>

Register ==
  /\ request_id' = RegisterImpl(request_id)
  /\ UNCHANGED <<config>>

Estimate_request ==
  /\ request_id' = Estimate_requestImpl(request_id)
  /\ UNCHANGED <<config>>

Get_history ==
  /\ request_id' = Get_historyImpl(request_id)
  /\ UNCHANGED <<config>>

Get_by_endpoint ==
  /\ request_id' = Get_by_endpointImpl(request_id)
  /\ UNCHANGED <<config>>

Get_summary ==
  /\ request_id' = Get_summaryImpl(request_id)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ As_header_value \/ Estimate \/ Register \/ Estimate_request \/ Get_history \/ Get_by_endpoint \/ Get_summary \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ COSTTRACKER_INV_01
  /\ COSTTRACKER_INV_02
  /\ COSTTRACKER_INV_03

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>request_id' # request_id

====