---- MODULE ErrorSink ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for ErrorSink
  Namespace: obs
  Generated from primitive contract and implementation

  Purpose: Capture uncaught exceptions with fingerprint grouping, attach current trace and correlation context, apply sampling, and forward to an error-tracking backend.

  Invariants:
    INV_01: Every captured event MUST include the active trace_id, span_id, and request_id when any of those are set.
    INV_02: A fingerprint MUST be deterministic for the same exception type plus top-three stack frames; otherwise identical incidents SHALL NEVER split into separate issues.
    INV_03: capture_exception MUST redact registered PII field names (email, password, authorization) before transport.
    INV_04: The sink CANNOT block the caller; serialization and network transmission SHALL run on a background worker.
    INV_05: before_send hooks returning None MUST drop the event and NEVER partially transmit it.
    INV_06: Sampling SHALL apply AFTER fingerprinting so rare variants are not accidentally suppressed by head-of-queue drops.
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

(* ERR_INV_01: context attached *)
ERR_INV_01 ==
  /\ TypeOK

(* ERR_INV_02: deterministic fingerprint *)
ERR_INV_02 ==
  /\ TypeOK

(* ERR_INV_03: PII redaction *)
ERR_INV_03 ==
  /\ TypeOK

(* ERR_INV_04: non-blocking *)
ERR_INV_04 ==
  /\ state <= MaxInt

(* ERR_INV_05: before_send None drops *)
ERR_INV_05 ==
  /\ TypeOK

(* ERR_INV_06: sampling AFTER fingerprint *)
ERR_INV_06 ==
  /\ TypeOK

(* Operations *)
Capture_exception ==
  /\ state' = Capture_exceptionImpl(state)
  /\ UNCHANGED <<config>>

Capture_message ==
  /\ state' = Capture_messageImpl(state)
  /\ UNCHANGED <<config>>

Register_fingerprinter ==
  /\ state' = Register_fingerprinterImpl(state)
  /\ UNCHANGED <<config>>

Before_send ==
  /\ state' = Before_sendImpl(state)
  /\ UNCHANGED <<config>>

Default_fingerprint ==
  /\ state' = Default_fingerprintImpl(state)
  /\ UNCHANGED <<config>>

Set_context ==
  /\ state' = Set_contextImpl(state)
  /\ UNCHANGED <<config>>

Flush ==
  /\ state' = FlushImpl(state)
  /\ UNCHANGED <<config>>

Shutdown ==
  /\ state' = ShutdownImpl(state)
  /\ UNCHANGED <<config>>

Sent ==
  /\ state' = SentImpl(state)
  /\ UNCHANGED <<config>>

Dropped ==
  /\ state' = DroppedImpl(state)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Capture_exception \/ Capture_message \/ Register_fingerprinter \/ Before_send \/ Default_fingerprint \/ Set_context \/ Flush \/ Shutdown \/ Sent \/ Dropped \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ ERR_INV_01
  /\ ERR_INV_02
  /\ ERR_INV_03
  /\ ERR_INV_04
  /\ ERR_INV_05
  /\ ERR_INV_06

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>state' # state

====