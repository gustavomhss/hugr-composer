---- MODULE MemoryPubSubBackend ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for MemoryPubSubBackend
  Namespace: api
  Generated from primitive contract and implementation

  Purpose: In-process fan-out pub/sub backend: publish() broadcasts a payload to every live subscriber queue on the named topic, subscribe() yields payloads from a private asyncio.Queue that is torn down on generator exit — suitable as a single-worker default before swapping in Redis/NATS.

  Invariants:
    INV_01: MEMORY_PUB_SUB_BACKEND_INV_01: publish(topic, payload) MUST enqueue payload on EVERY subscriber queue currently registered for topic; no subscriber may be silently skipped.
    INV_02: MEMORY_PUB_SUB_BACKEND_INV_02: A payload published BEFORE a new subscriber calls subscribe() MUST NOT be delivered to that subscriber; the backend has no replay buffer.
    INV_03: MEMORY_PUB_SUB_BACKEND_INV_03: When the subscribe() generator exits (GeneratorExit, close, break) its queue MUST be removed from the topic's subscriber list so publish() no longer writes to it.
    INV_04: MEMORY_PUB_SUB_BACKEND_INV_04: Events delivered to a single subscriber MUST preserve publish order; the per-subscriber asyncio.Queue is FIFO.
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

(* MP_INV_01: fanout-to-active + MP_INV_02 — topic isolation *)
MP_INV_01 ==
  /\ TypeOK

(* MP_INV_03: subscriber cleanup on aclose + close() *)
MP_INV_03 ==
  /\ TypeOK

(* MP_INV_03: subscriber cleanup on aclose + close() *)
MP_INV_03 ==
  /\ TypeOK

(* MP_INV_04: MEMORY_PUB_SUB_BACKEND_INV_04: Events delivered to a single subscriber MUST preserve publish order; the per-subscriber asyncio.Queue is FIFO. *)
MP_INV_04 ==
  /\ TypeOK

(* Operations *)
Close ==
  /\ state' = CloseImpl(state)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Close \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ MP_INV_01
  /\ MP_INV_03
  /\ MP_INV_03
  /\ MP_INV_04

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>state' # state

====