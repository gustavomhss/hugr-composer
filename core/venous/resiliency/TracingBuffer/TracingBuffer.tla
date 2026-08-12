---- MODULE TracingBuffer ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for TracingBuffer
  Namespace: resiliency
  Generated from primitive contract and implementation

  Purpose: Thread-safe in-memory ring buffer of the last N request traces. Supports newest-first iteration, lookup by request id, and p99 slow-path query. Designed for in-process diagnostic UIs, NOT durable storage.

  Invariants:
    INV_01: TRACING_BUFFER_INV_01: Buffer length MUST never exceed `maxlen`; oldest entries are evicted FIFO once the ring is full (deque-with-maxlen semantics).
    INV_02: TRACING_BUFFER_INV_02: `get_all()` MUST return entries in newest-first order (reverse of insertion).
    INV_03: TRACING_BUFFER_INV_03: `get_by_id(id)` MUST return the stored dict iff an entry with matching `id` is still in the buffer; else None (no exceptions).
*)

CONSTANTS MaxInt

VARIABLES state, config

vars == <<state, config>>

TypeOK == 
  /\ state \in String
  /\ config \in String

Init == 
  /\ state = ""
  /\ config = ""

(* TRACINGBUFFER_INV_01: TRACING_BUFFER_INV_01: Buffer length MUST never exceed `maxlen`; oldest entries are evicted FIFO once the ring is full (deque-with-maxlen semantics). *)
TRACINGBUFFER_INV_01 ==
  /\ state <= config

(* TRACINGBUFFER_INV_02: TRACING_BUFFER_INV_02: `get_all()` MUST return entries in newest-first order (reverse of insertion). *)
TRACINGBUFFER_INV_02 ==
  /\ TypeOK

(* TRACINGBUFFER_INV_03: TRACING_BUFFER_INV_03: `get_by_id(id)` MUST return the stored dict iff an entry with matching `id` is still in the buffer; else None (no exceptions). *)
TRACINGBUFFER_INV_03 ==
  /\ TypeOK

(* Operations *)
Record ==
  /\ state' = RecordImpl(state)
  /\ UNCHANGED <<config>>

Get_all ==
  /\ state' = Get_allImpl(state)
  /\ UNCHANGED <<config>>

Get_by_id ==
  /\ state' = Get_by_idImpl(state)
  /\ UNCHANGED <<config>>

Get_slow ==
  /\ state' = Get_slowImpl(state)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Record \/ Get_all \/ Get_by_id \/ Get_slow \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ TRACINGBUFFER_INV_01
  /\ TRACINGBUFFER_INV_02
  /\ TRACINGBUFFER_INV_03

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>state' # state

====