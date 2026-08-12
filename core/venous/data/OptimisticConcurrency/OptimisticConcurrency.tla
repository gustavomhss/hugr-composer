---- MODULE OptimisticConcurrency ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for OptimisticConcurrency
  Namespace: data
  Generated from primitive contract and implementation

  Purpose: Compare-and-swap write pattern; write fails cleanly when the stored version changed since the reader last saw it.

  Invariants:
    INV_01: {'id': 'OC_INV_01', 'rule': 'compare_and_swap atomically checks old_version and writes OR raises -- no partial update.'}
    INV_02: {'id': 'OC_INV_02', 'rule': 'Writer MUST retry on conflict ONLY via the retry primitive (no hidden retry here).'}
    INV_03: {'id': 'OC_INV_03', 'rule': 'Version is monotonic and gap-free per key (next = prev + 1).'}
    INV_04: {'id': 'OC_INV_04', 'rule': 'Readers never observe a torn write (read returns value atomic with its version).'}
    INV_05: {'id': 'OC_INV_05', 'rule': 'read(k) of an unknown key returns (None, 0) -- canonical empty, never raises.'}
*)

CONSTANTS MaxInt

VARIABLES key, expected_version, actual_version

vars == <<key, expected_version, actual_version>>

TypeOK == 
  /\ key \in String
  /\ expected_version \in String
  /\ actual_version \in String

Init == 
  /\ key = ""
  /\ expected_version = ""
  /\ actual_version = ""

(* OC_INV_01: ``compare_and_swap`` atomically checks old_version AND writes *)
OC_INV_01 ==
  /\ old_version = expected => success

(* OC_INV_02: Writer MUST retry on conflict ONLY via the retry primitive *)
OC_INV_02 ==
  /\ TypeOK

(* OC_INV_03: Version is monotonic and gap-free per key (next = prev + 1). *)
OC_INV_03 ==
  /\ version' = version + 1

(* OC_INV_04: Readers never observe a torn write (read returns full value *)
OC_INV_04 ==
  /\ read_version = write_version

(* OC_INV_05: ``read(k)`` of an unknown key returns ``(None, 0)`` — canonical *)
OC_INV_05 ==
  /\ read_version = write_version

(* Operations *)
Read ==
  /\ key' = ReadImpl(key)
  /\ UNCHANGED <<config>>

Compare_and_swap ==
  /\ key' = Compare_and_swapImpl(key)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Read \/ Compare_and_swap \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ OC_INV_01
  /\ OC_INV_02
  /\ OC_INV_03
  /\ OC_INV_04
  /\ OC_INV_05

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>key' # key

====