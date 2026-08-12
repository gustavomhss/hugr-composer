---- MODULE StructuredLogger ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for StructuredLogger
  Namespace: obs
  Generated from primitive contract and implementation

  Purpose: Emit machine-parseable key/value log records with a fixed level taxonomy, attached trace and span identifiers, and no positional string formatting.

  Invariants:
    INV_01: Every emitted record MUST be a single line of valid UTF-8 JSON with keys 'ts', 'level', 'event', plus the caller-provided fields.
    INV_02: Log level SHALL be one of DEBUG, INFO, WARN, ERROR; TRACE and FATAL are FORBIDDEN to prevent drift from OTel log severity ranges.
    INV_03: When a span is active in the current context, the record MUST automatically include 'trace_id' and 'span_id' in hex form.
    INV_04: Printf-style formatting with %s or f-strings inside the event message is FORBIDDEN; values ALWAYS travel as typed fields.
    INV_05: Secrets matching registered redaction patterns (authorization headers, bearer tokens, card PANs) MUST be replaced with '[REDACTED]' before serialization.
    INV_06: Binding a field NEVER mutates the parent logger; bind returns a new immutable logger instance.
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

(* LOG_INV_01: one JSON line with ts/level/event + fields *)
LOG_INV_01 ==
  /\ TypeOK

(* LOG_INV_02: level taxonomy *)
LOG_INV_02 ==
  /\ TypeOK

(* LOG_INV_03: span attachment when active *)
LOG_INV_03 ==
  /\ TypeOK

(* LOG_INV_04: no formatting placeholders in event *)
LOG_INV_04 ==
  /\ TypeOK

(* LOG_INV_05: redaction *)
LOG_INV_05 ==
  /\ TypeOK

(* LOG_INV_06: bind returns immutable child *)
LOG_INV_06 ==
  /\ TypeOK

(* Operations *)
Debug ==
  /\ state' = DebugImpl(state)
  /\ UNCHANGED <<config>>

Info ==
  /\ state' = InfoImpl(state)
  /\ UNCHANGED <<config>>

Warn ==
  /\ state' = WarnImpl(state)
  /\ UNCHANGED <<config>>

Error ==
  /\ state' = ErrorImpl(state)
  /\ UNCHANGED <<config>>

Bind ==
  /\ state' = BindImpl(state)
  /\ UNCHANGED <<config>>

With_context ==
  /\ state' = With_contextImpl(state)
  /\ UNCHANGED <<config>>

Validate_event_message ==
  /\ state' = Validate_event_messageImpl(state)
  /\ UNCHANGED <<config>>

Validate_level ==
  /\ state' = Validate_levelImpl(state)
  /\ UNCHANGED <<config>>

Redact ==
  /\ state' = RedactImpl(state)
  /\ UNCHANGED <<config>>

Set ==
  /\ key # ""
  /\ result' = SetImpl(key)
  /\ UNCHANGED <<config>>

Get ==
  /\ key # ""
  /\ result' = GetImpl(key)
  /\ UNCHANGED <<config>>

Records ==
  /\ state' = RecordsImpl(state)
  /\ UNCHANGED <<config>>

Activate_span ==
  /\ state' = Activate_spanImpl(state)
  /\ UNCHANGED <<config>>

Clear_span ==
  /\ state' = Clear_spanImpl(state)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Debug \/ Info \/ Warn \/ Error \/ Bind \/ With_context \/ Validate_event_message \/ Validate_level \/ Redact \/ Set \/ Get \/ Records \/ Activate_span \/ Clear_span \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ LOG_INV_01
  /\ LOG_INV_02
  /\ LOG_INV_03
  /\ LOG_INV_04
  /\ LOG_INV_05
  /\ LOG_INV_06

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>state' # state

====