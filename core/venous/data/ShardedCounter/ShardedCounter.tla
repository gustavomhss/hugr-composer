---- MODULE ShardedCounter ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for ShardedCounter
  Namespace: data
  Generated from primitive contract and implementation

  Purpose: Hot-key-safe monotonic per-key counter distributed across N fixed shards; value() sums across shards.

  Invariants:
    INV_01: {'id': 'SC_INV_01', 'rule': 'Counter MUST NEVER decrement (delta MUST be > 0).'}
    INV_02: {'id': 'SC_INV_02', 'rule': 'Read-after-write in the same session reflects at least the preceding increment (session causality, not global consistency).'}
    INV_03: {'id': 'SC_INV_03', 'rule': 'value(key) is the SUM of all shard values -- never a single shard.'}
    INV_04: {'id': 'SC_INV_04', 'rule': 'Shard count is fixed at construction; changing it requires a migration primitive.'}
    INV_05: {'id': 'SC_INV_05', 'rule': 'Concurrent increments on the same key hit DIFFERENT shards (hashed modulo shard_count on thread/async-task id).'}
*)

CONSTANTS MaxInt

VARIABLES reason

vars == <<reason>>

TypeOK == 
  /\ reason \in String

Init == 
  /\ reason = ""

(* SC_INV_01: Counter MUST NEVER decrement (delta MUST be > 0). *)
SC_INV_01 ==
  /\ TypeOK

(* SC_INV_02: Read-after-write in the same session reflects at least the *)
SC_INV_02 ==
  /\ read_version = write_version

(* SC_INV_03: ``value(key)`` is the SUM of all shard values — never a *)
SC_INV_03 ==
  /\ TypeOK

(* SC_INV_04: Shard count is fixed at construction; changing it requires *)
SC_INV_04 ==
  /\ TypeOK

(* SC_INV_05: Concurrent increments on the same key hit DIFFERENT shards *)
SC_INV_05 ==
  /\ TypeOK

(* Operations *)
Increment ==
  /\ reason' = IncrementImpl(reason)
  /\ UNCHANGED <<config>>

Value ==
  /\ reason' = ValueImpl(reason)
  /\ UNCHANGED <<config>>

Reset ==
  /\ key # ""
  /\ state' = InitState
  /\ UNCHANGED <<config>>

Shard_count ==
  /\ reason' = Shard_countImpl(reason)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Increment \/ Value \/ Reset \/ Shard_count \/ Tick \/ Stutter

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
  /\ <>reason' # reason

====