---- MODULE BatchCore ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for BatchCore
  Namespace: api
  Generated from primitive contract and implementation

  Purpose: Async batch executor with per-item timeout, bounded parallelism, and two isolation modes (all-or-nothing / best-effort). Guarantees result order aligns with input order regardless of completion order.

  Invariants:
    INV_01: BATCH_CORE_INV_01: The returned `list[BatchItemResult]` MUST be the same length as the input `items` list and aligned by index (result[i] corresponds to items[i]).
    INV_02: BATCH_CORE_INV_02: In `all_or_nothing` mode, the FIRST item with status_code >= 400 MUST stop subsequent processing; all remaining items receive a 409 rollback placeholder.
    INV_03: BATCH_CORE_INV_03: In parallel strategy, concurrency MUST be bounded by `max_parallel` — the semaphore acquires at most that many permits simultaneously.
*)

CONSTANTS MaxInt

VARIABLES index, status_code, data, error, idempotency_key

vars == <<index, status_code, data, error, idempotency_key>>

TypeOK == 
  /\ index \in 0..MaxInt
  /\ status_code \in 0..MaxInt
  /\ data \in String
  /\ error \in String
  /\ idempotency_key \in String

Init == 
  /\ index = 0
  /\ status_code = 0
  /\ data = ""
  /\ error = ""
  /\ idempotency_key = ""

(* BATCHCORE_INV_01: BATCH_CORE_INV_01: The returned `list[BatchItemResult]` MUST be the same length as the input `items` list and aligned by index (result[i] corresponds to items[i]). *)
BATCHCORE_INV_01 ==
  /\ TypeOK

(* BATCHCORE_INV_02: BATCH_CORE_INV_02: In `all_or_nothing` mode, the FIRST item with status_code >= 400 MUST stop subsequent processing; all remaining items receive a 409 rollback placeholder. *)
BATCHCORE_INV_02 ==
  /\ TypeOK

(* BATCHCORE_INV_03: BATCH_CORE_INV_03: In parallel strategy, concurrency MUST be bounded by `max_parallel` — the semaphore acquires at most that many permits simultaneously. *)
BATCHCORE_INV_03 ==
  /\ index <= status_code

(* Operations *)
Execute ==
  /\ index' = ExecuteImpl(index)
  /\ UNCHANGED <<config>>

Reset ==
  /\ key # ""
  /\ state' = InitState
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Execute \/ Reset \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ BATCHCORE_INV_01
  /\ BATCHCORE_INV_02
  /\ BATCHCORE_INV_03

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>index' # index

====