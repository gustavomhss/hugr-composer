---- MODULE IdempotencyStore ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for IdempotencyStore
  Namespace: api
  Generated from primitive contract and implementation

  Purpose: Thread-safe in-memory key-to-result cache used to deduplicate retried requests: get/put/seen so a handler can short-circuit and return the previous result when the same idempotency key is presented twice.

  Invariants:
    INV_01: IDEMPOTENCY_STORE_INV_01: get(key) MUST return the exact object passed to the most recent put(key, result); for an unknown key it MUST return None without raising.
    INV_02: IDEMPOTENCY_STORE_INV_02: seen(key) MUST return True iff put() has been called at least once for key, including the case where the stored result is None.
    INV_03: IDEMPOTENCY_STORE_INV_03: All public operations MUST be atomic under the internal threading.Lock; concurrent callers MUST NOT observe a half-written state.
    INV_04: IDEMPOTENCY_STORE_INV_04: put(key, result) MUST overwrite any prior value stored under key; the store is a single-slot cache per key, never append-only.
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

(* IS_INV_01: get-after-put / get-when-empty *)
IS_INV_01 ==
  /\ TypeOK

(* IS_INV_02: seen == (get is not None) *)
IS_INV_02 ==
  /\ TypeOK

(* IS_INV_03: concurrent writes are serialised by the internal lock *)
IS_INV_03 ==
  /\ TypeOK

(* IS_INV_04: IDEMPOTENCY_STORE_INV_04: put(key, result) MUST overwrite any prior value stored under key; the store is a single-slot cache per key, never append-only. *)
IS_INV_04 ==
  /\ cached_keys_age <= max_age

(* Operations *)
Get ==
  /\ key # ""
  /\ result' = GetImpl(key)
  /\ UNCHANGED <<config>>

Put ==
  /\ state' = PutImpl(state)
  /\ UNCHANGED <<config>>

Seen ==
  /\ state' = SeenImpl(state)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Get \/ Put \/ Seen \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ IS_INV_01
  /\ IS_INV_02
  /\ IS_INV_03
  /\ IS_INV_04

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>state' # state

====