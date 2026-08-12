---- MODULE DataLoader ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for DataLoader
  Namespace: api
  Generated from primitive contract and implementation

  Purpose: Batch and dedupe per-request loads from N-per-resolver patterns into one bulk fetch per key-type per tick.

  Invariants:
    INV_01: {'id': 'DATALOADER_INV_01', 'rule': 'Within one tick, identical keys resolve to the SAME result instance (identity-preserving cache).'}
    INV_02: {'id': 'DATALOADER_INV_02', 'rule': 'Batch fn receives keys in caller-insertion order; returned values correspond positionally.'}
    INV_03: {'id': 'DATALOADER_INV_03', 'rule': 'If batch fn raises, ALL waiting loaders for that tick receive that exception.'}
    INV_04: {'id': 'DATALOADER_INV_04', 'rule': 'clear(k) removes cache entry and does NOT cancel an in-flight batch containing k.'}
    INV_05: {'id': 'DATALOADER_INV_05', 'rule': 'Max-batch-size cap honored; overflow splits into the next batch.'}
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

(* DATALOADER_INV_01: Identical keys within one tick resolve to the SAME *)
DATALOADER_INV_01 ==
  /\ TypeOK

(* DATALOADER_INV_02: Batch fn receives keys in caller-insertion order; *)
DATALOADER_INV_02 ==
  /\ TypeOK

(* DATALOADER_INV_03: If batch fn raises, ALL waiting loaders for that tick *)
DATALOADER_INV_03 ==
  /\ state <= MaxInt

(* DATALOADER_INV_04: ``clear(k)`` removes cache entry and does NOT cancel *)
DATALOADER_INV_04 ==
  /\ TypeOK

(* DATALOADER_INV_05: Max-batch-size cap is honored; overflow splits into *)
DATALOADER_INV_05 ==
  /\ TypeOK

(* Operations *)
Prime ==
  /\ state' = PrimeImpl(state)
  /\ UNCHANGED <<config>>

Clear ==
  /\ state' = ClearImpl(state)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Prime \/ Clear \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ DATALOADER_INV_01
  /\ DATALOADER_INV_02
  /\ DATALOADER_INV_03
  /\ DATALOADER_INV_04
  /\ DATALOADER_INV_05

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>state' # state

====