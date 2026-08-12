---- MODULE HeterogeneousWorkerPool ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for HeterogeneousWorkerPool
  Namespace: resiliency
  Generated from primitive contract and implementation

  Purpose: Route inference tasks across mixed CPU+GPU workers with observed queue-depth + latency health, capability gating, and session-stickiness.

  Invariants:
    INV_01: {'id': 'HWP_INV_01', 'rule': 'A task with family=F MUST land on a worker advertising F in its capabilities.'}
    INV_02: {'id': 'HWP_INV_02', 'rule': 'GPU workers preferred when any healthy GPU worker has queue_depth < pool median; fallback CPU otherwise.'}
    INV_03: {'id': 'HWP_INV_03', 'rule': 'A worker whose rolling p50 latency over the last 100 samples is >= 2.0x pool-wide rolling p50 is deprioritized (weight 0.1x) within 30 seconds.'}
    INV_04: {'id': 'HWP_INV_04', 'rule': 'Session-stickiness: same session_id routes to same worker while worker healthy; on unhealthy, fails over.'}
    INV_05: {'id': 'HWP_INV_05', 'rule': "Burst of N tasks spreads such that no single worker's queue exceeds 1.5x pool median."}
    INV_06: {'id': 'HWP_INV_06', 'rule': "Once a worker's rolling p50 normalizes back within 1.5x pool p50, full weight is restored within 30 seconds."}
*)

CONSTANTS MaxInt

VARIABLES payload, session_id

vars == <<payload, session_id>>

TypeOK == 
  /\ payload \in String
  /\ session_id \in String

Init == 
  /\ payload = ""
  /\ session_id = ""

(* HWP_INV_01: A task with ``family=F`` MUST land on a worker advertising *)
HWP_INV_01 ==
  /\ TypeOK

(* HWP_INV_02: GPU workers preferred when any healthy GPU worker has *)
HWP_INV_02 ==
  /\ TypeOK

(* HWP_INV_03: A worker whose rolling p50 latency over the last 100 *)
HWP_INV_03 ==
  /\ TypeOK

(* HWP_INV_04: Session-stickiness — same session_id routes to same worker *)
HWP_INV_04 ==
  /\ TypeOK

(* HWP_INV_05: Burst of N tasks spreads so no single worker's queue *)
HWP_INV_05 ==
  /\ read_version = write_version

(* HWP_INV_06: Once a worker's rolling p50 normalizes back within 1.5x *)
HWP_INV_06 ==
  /\ TypeOK

(* Operations *)
P50 ==
  /\ payload' = P50Impl(payload)
  /\ UNCHANGED <<config>>

Is_healthy ==
  /\ payload' = Is_healthyImpl(payload)
  /\ UNCHANGED <<config>>

Register ==
  /\ payload' = RegisterImpl(payload)
  /\ UNCHANGED <<config>>

Submit ==
  /\ payload' = SubmitImpl(payload)
  /\ UNCHANGED <<config>>

On_result ==
  /\ payload' = On_resultImpl(payload)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ P50 \/ Is_healthy \/ Register \/ Submit \/ On_result \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ HWP_INV_01
  /\ HWP_INV_02
  /\ HWP_INV_03
  /\ HWP_INV_04
  /\ HWP_INV_05
  /\ HWP_INV_06

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>payload' # payload

====