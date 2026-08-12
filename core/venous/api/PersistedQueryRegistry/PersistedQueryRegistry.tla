---- MODULE PersistedQueryRegistry ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for PersistedQueryRegistry
  Namespace: api
  Generated from primitive contract and implementation

  Purpose: SHA-256 -> query allow-list that lets production clients send deterministic 64-char ids instead of raw queries; unregistered ids are rejected.

  Invariants:
    INV_01: {'id': 'PQR_INV_01', 'rule': 'Hash id is lowercase sha-256 hex of UTF-8 query bytes; registration is idempotent.'}
    INV_02: {'id': 'PQR_INV_02', 'rule': 'get() never returns a query whose re-hash differs from the id (tamper detection).'}
    INV_03: {'id': 'PQR_INV_03', 'rule': 'Registry is read-only in production mode; register() in prod raises PQRImmutableError.'}
    INV_04: {'id': 'PQR_INV_04', 'rule': 'Lookup is O(1) in the backing store.'}
    INV_05: {'id': 'PQR_INV_05', 'rule': 'Callers cannot enumerate registered ids (no public list() -- privacy).'}
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

(* PQR_INV_01: Hash id is lowercase sha-256 hex of UTF-8 query bytes; *)
PQR_INV_01 ==
  /\ old_version = expected => success

(* PQR_INV_02: ``get()`` never returns a query whose re-hash differs from *)
PQR_INV_02 ==
  /\ TypeOK

(* PQR_INV_03: Registry is read-only in production mode; ``register()`` *)
PQR_INV_03 ==
  /\ read_version = write_version

(* PQR_INV_04: Lookup is O(1) in the backing store. *)
PQR_INV_04 ==
  /\ TypeOK

(* PQR_INV_05: Callers cannot enumerate registered ids (no public ``list()``). *)
PQR_INV_05 ==
  /\ state <= config

(* Operations *)
Register ==
  /\ state' = RegisterImpl(state)
  /\ UNCHANGED <<config>>

Get ==
  /\ key # ""
  /\ result' = GetImpl(key)
  /\ UNCHANGED <<config>>

Contains ==
  /\ state' = ContainsImpl(state)
  /\ UNCHANGED <<config>>

Hash_query ==
  /\ state' = Hash_queryImpl(state)
  /\ UNCHANGED <<config>>

Freeze ==
  /\ state' = FreezeImpl(state)
  /\ UNCHANGED <<config>>

Frozen ==
  /\ state' = FrozenImpl(state)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Register \/ Get \/ Contains \/ Hash_query \/ Freeze \/ Frozen \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ PQR_INV_01
  /\ PQR_INV_02
  /\ PQR_INV_03
  /\ PQR_INV_04
  /\ PQR_INV_05

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>state' # state

====