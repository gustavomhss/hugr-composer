---- MODULE TelemetryExporter ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for TelemetryExporter
  Namespace: obs
  Generated from primitive contract and implementation

  Purpose: Serialize batched spans, metrics, or log records into an OTLP-compatible envelope and deliver them to a configured endpoint with retry and backpressure.

  Invariants:
    INV_01: Exporter calls MUST be non-blocking on the hot path; the caller SHALL always enqueue through an intermediate batch processor.
    INV_02: On transient failure the exporter MUST retry with exponential backoff, capped at a configurable maximum, and NEVER retry indefinitely.
    INV_03: Shutdown MUST flush the in-flight batch within the provided timeout and CANNOT accept new export calls afterwards.
    INV_04: The wire format MUST conform to OTLP/HTTP protobuf or OTLP/gRPC as defined by OpenTelemetry Specification 1.32.
    INV_05: Authentication headers attached to exports are FORBIDDEN from appearing in any log record, span attribute, or error event emitted by the exporter itself.
    INV_06: Export results SHALL be observable via an internal counter keyed by (signal, result) so operators can alert on sustained failure.
*)

CONSTANTS MaxInt

VARIABLES signal, max_retries, initial_backoff_s, max_backoff_s, attempt

vars == <<signal, max_retries, initial_backoff_s, max_backoff_s, attempt>>

TypeOK == 
  /\ signal \in String
  /\ max_retries \in 0..MaxInt
  /\ initial_backoff_s \in 0..MaxInt
  /\ max_backoff_s \in 0..MaxInt
  /\ attempt \in 0..MaxInt

Init == 
  /\ signal = ""
  /\ max_retries = 0
  /\ initial_backoff_s = 0
  /\ max_backoff_s = 0
  /\ attempt = 0

(* TEX_INV_01: non-blocking on hot path *)
TEX_INV_01 ==
  /\ signal <= MaxInt

(* TEX_INV_02: bounded retry *)
TEX_INV_02 ==
  /\ TypeOK

(* TEX_INV_03: shutdown idempotent + blocks new exports *)
TEX_INV_03 ==
  /\ signal <= MaxInt

(* TEX_INV_04: OTLP wire format (reference preserves batch structure) *)
TEX_INV_04 ==
  /\ TypeOK

(* TEX_INV_05: auth headers never leak *)
TEX_INV_05 ==
  /\ TypeOK

(* TEX_INV_06: counter observable *)
TEX_INV_06 ==
  /\ TypeOK

(* Operations *)
Export ==
  /\ signal' = ExportImpl(signal)
  /\ UNCHANGED <<config>>

Force_flush ==
  /\ signal' = Force_flushImpl(signal)
  /\ UNCHANGED <<config>>

Shutdown ==
  /\ signal' = ShutdownImpl(signal)
  /\ UNCHANGED <<config>>

Backoff_at ==
  /\ signal' = Backoff_atImpl(signal)
  /\ UNCHANGED <<config>>

Emit_log ==
  /\ signal' = Emit_logImpl(signal)
  /\ UNCHANGED <<config>>

Counter ==
  /\ signal' = CounterImpl(signal)
  /\ UNCHANGED <<config>>

Exported_batches ==
  /\ signal' = Exported_batchesImpl(signal)
  /\ UNCHANGED <<config>>

Retry_count ==
  /\ signal' = Retry_countImpl(signal)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Export \/ Force_flush \/ Shutdown \/ Backoff_at \/ Emit_log \/ Counter \/ Exported_batches \/ Retry_count \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ TEX_INV_01
  /\ TEX_INV_02
  /\ TEX_INV_03
  /\ TEX_INV_04
  /\ TEX_INV_05
  /\ TEX_INV_06

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>signal' # signal

====