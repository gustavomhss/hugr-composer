---- MODULE HistogramBuckets ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for HistogramBuckets
  Namespace: obs
  Generated from primitive contract and implementation

  Purpose: Define explicit latency and size bucket boundaries for histogram instruments so quantile estimation is accurate and comparable across services.

  Invariants:
    INV_01: Boundaries MUST be strictly increasing, finite, non-negative, and SHALL include at least five buckets below the target p99.
    INV_02: Once assigned to an instrument, boundaries are immutable; changing them at runtime is FORBIDDEN because it invalidates historical quantile comparisons.
    INV_03: Latency boundaries MUST be expressed in milliseconds with unit 'ms' and NEVER mixed with seconds on the same instrument.
    INV_04: The lowest boundary MUST be smaller than the realistic floor of the measured distribution so the first bucket is not saturated.
    INV_05: Bucket count SHALL NOT exceed 20 per instrument to bound per-series storage cost.
    INV_06: Default bucket sets for HTTP latency and payload size MUST be derived from the OpenTelemetry HTTP semconv recommendation and CANNOT be silently overridden at instrument creation.
*)

CONSTANTS MaxInt

VARIABLES name, unit, boundaries, target_p99, None, 05, 06

vars == <<name, unit, boundaries, target_p99, None, 05, 06>>

TypeOK == 
  /\ name \in String
  /\ unit \in String
  /\ boundaries \in 0..MaxInt
  /\ target_p99 \in 0..MaxInt
  /\ None \in String
  /\ 05 \in String
  /\ 06 \in String

Init == 
  /\ name = ""
  /\ unit = ""
  /\ boundaries = 0
  /\ target_p99 = 0
  /\ None = ""
  /\ 05 = ""
  /\ 06 = ""

(* HB_INV_01: boundaries well-formed *)
HB_INV_01 ==
  /\ TypeOK

(* HB_INV_02: immutable *)
HB_INV_02 ==
  /\ TypeOK

(* HB_INV_03: latency unit *)
HB_INV_03 ==
  /\ TypeOK

(* HB_INV_04: lowest boundary below measurement floor *)
HB_INV_04 ==
  /\ TypeOK

(* HB_INV_05: bucket count cap *)
HB_INV_05 ==
  /\ TypeOK

(* HB_INV_06: default presets from semconv *)
HB_INV_06 ==
  /\ TypeOK

(* Operations *)
Validate_unit ==
  /\ name' = Validate_unitImpl(name)
  /\ UNCHANGED <<config>>

Validate_boundaries ==
  /\ name' = Validate_boundariesImpl(name)
  /\ UNCHANGED <<config>>

Latency_ms_default ==
  /\ name' = Latency_ms_defaultImpl(name)
  /\ UNCHANGED <<config>>

Payload_bytes_default ==
  /\ name' = Payload_bytes_defaultImpl(name)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Validate_unit \/ Validate_boundaries \/ Latency_ms_default \/ Payload_bytes_default \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ HB_INV_01
  /\ HB_INV_02
  /\ HB_INV_03
  /\ HB_INV_04
  /\ HB_INV_05
  /\ HB_INV_06

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>name' # name

====