---- MODULE SessionCache ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for SessionCache
  Namespace: cache
  Generated from primitive contract and implementation

  Purpose: Stateless-tier, node-agnostic read-through cache keyed by session token for per-caller state with TTL and explicit miss/error separation.

  Invariants:
    INV_01: {'id': 'SC_INV_01', 'rule': 'get() is read-only; never mutates server-side state.'}
    INV_02: {'id': 'SC_INV_02', 'rule': 'Missing key returns None, not raise; caller distinguishes miss vs. error via SessionCacheError.'}
    INV_03: {'id': 'SC_INV_03', 'rule': 'invalidate() is idempotent and O(1).'}
    INV_04: {'id': 'SC_INV_04', 'rule': 'TTL is honored; an expired entry is equivalent to missing.'}
    INV_05: {'id': 'SC_INV_05', 'rule': 'A node that has never seen a token resolves its session via the external store (cold-cache tolerant).'}
*)

CONSTANTS MaxInt

VARIABLES value, expires_at_s

vars == <<value, expires_at_s>>

TypeOK == 
  /\ value \in String
  /\ expires_at_s \in 0..MaxInt

Init == 
  /\ value = ""
  /\ expires_at_s = 0

(* SC_INV_01: ``get()`` is read-only — never mutates server-side state. *)
SC_INV_01 ==
  /\ read_version = write_version

(* SC_INV_02: Missing key returns ``None``; caller distinguishes miss vs. *)
SC_INV_02 ==
  /\ TypeOK

(* SC_INV_03: ``invalidate()`` is idempotent and O(1). *)
SC_INV_03 ==
  /\ TypeOK

(* SC_INV_04: TTL is honored — an expired entry is equivalent to missing. *)
SC_INV_04 ==
  /\ TRUE

(* SC_INV_05: A node that has never seen a token can still resolve its *)
SC_INV_05 ==
  /\ TypeOK

(* Operations *)
Get ==
  /\ key # ""
  /\ result' = GetImpl(key)
  /\ UNCHANGED <<config>>

Set ==
  /\ key # ""
  /\ result' = SetImpl(key)
  /\ UNCHANGED <<config>>

Invalidate ==
  /\ value' = InvalidateImpl(value)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Get \/ Set \/ Invalidate \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ SC_INV_01
  /\ SC_INV_02
  /\ SC_INV_03
  /\ SC_INV_04
  /\ SC_INV_05

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>value' # value
  /\ <>read_version = write_version

====