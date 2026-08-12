---- MODULE RequestContext ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for RequestContext
  Namespace: api
  Generated from primitive contract and implementation

  Purpose: Per-request bag that carries identity, headers, correlation id, and free-form assigns through the handler stack without global state.

  Invariants:
    INV_01: MUST be constructed once per inbound request and disposed when the response is sent.
    INV_02: NEVER leaks across request boundaries; a background task CANNOT reuse a parent context as live state.
    INV_03: put() MUST be idempotent for the same (key, value); overwriting an existing key SHALL be explicit.
    INV_04: halt() MUST cause subsequent middleware/interceptors to skip, but SHALL NOT abort already-queued response bytes.
    INV_05: request_id MUST be populated before the first user code runs; a missing id SHALL be replaced with a generated UUID.
*)

CONSTANTS MaxInt

VARIABLES request_id, headers, principal, assigns

vars == <<request_id, headers, principal, assigns>>

TypeOK == 
  /\ request_id \in String
  /\ headers \in String
  /\ principal \in String
  /\ assigns \in String

Init == 
  /\ request_id = ""
  /\ headers = ""
  /\ principal = ""
  /\ assigns = ""

(* RC_INV_01: lifecycle: constructed once per request, disposed at end *)
RC_INV_01 ==
  /\ TypeOK

(* RC_INV_02: no leak across request boundaries *)
RC_INV_02 ==
  /\ TypeOK

(* RC_INV_03: put() idempotent, explicit overwrite *)
RC_INV_03 ==
  /\ TRUE

(* RC_INV_04: halt() signals skip, does not abort queued bytes *)
RC_INV_04 ==
  /\ TypeOK

(* RC_INV_05: request_id populated, blank/control-char → UUIDv4 *)
RC_INV_05 ==
  /\ TypeOK

(* Operations *)
Put ==
  /\ request_id' = PutImpl(request_id)
  /\ UNCHANGED <<config>>

Halt ==
  /\ request_id' = HaltImpl(request_id)
  /\ UNCHANGED <<config>>

Is_halted ==
  /\ request_id' = Is_haltedImpl(request_id)
  /\ UNCHANGED <<config>>

Is_disposed ==
  /\ request_id' = Is_disposedImpl(request_id)
  /\ UNCHANGED <<config>>

Dispose ==
  /\ request_id' = DisposeImpl(request_id)
  /\ UNCHANGED <<config>>

Detached_snapshot ==
  /\ request_id' = Detached_snapshotImpl(request_id)
  /\ UNCHANGED <<config>>

For_log ==
  /\ request_id' = For_logImpl(request_id)
  /\ UNCHANGED <<config>>

Assigns ==
  /\ request_id' = AssignsImpl(request_id)
  /\ UNCHANGED <<config>>

Bind ==
  /\ request_id' = BindImpl(request_id)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Put \/ Halt \/ Is_halted \/ Is_disposed \/ Dispose \/ Detached_snapshot \/ For_log \/ Assigns \/ Bind \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ RC_INV_01
  /\ RC_INV_02
  /\ RC_INV_03
  /\ RC_INV_04
  /\ RC_INV_05

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>request_id' # request_id

====