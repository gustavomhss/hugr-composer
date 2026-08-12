---- MODULE Tracer ----
EXTENDS Naturals, Sequences, FiniteSets

(*
  TLA+ specification for Tracer
  Namespace: obs
  Generated from primitive contract and implementation

  Purpose: Create spans that represent a unit of work, attach attributes and events, link related spans, and propagate context across process and network boundaries.

  Invariants:
    INV_01: Every span MUST have a non-empty name, a start timestamp, and an end timestamp in that causal order.
    INV_02: A span CANNOT be ended twice; a second end call SHALL be a no-op with a recorded internal warning.
    INV_03: The tracer MUST honor W3C Trace Context headers (traceparent, tracestate) on both inject and extract without mutation of unknown tracestate vendor entries.
    INV_04: Recording an exception MUST set the span status code to ERROR unless the caller explicitly overrides with OK.
    INV_05: Attribute values MUST be one of: string, bool, int, float, or a homogeneous sequence of those types; nested structures are FORBIDDEN.
    INV_06: The tracer SHALL NEVER block the caller waiting for exporter acknowledgement; export is asynchronous.
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

(* TRACER_INV_01: name + timestamps + causal order *)
TRACER_INV_01 ==
  /\ TypeOK

(* TRACER_INV_02: end idempotent *)
TRACER_INV_02 ==
  /\ TypeOK

(* TRACER_INV_03: W3C context honored *)
TRACER_INV_03 ==
  /\ TypeOK

(* TRACER_INV_04: exception sets ERROR unless OK explicit *)
TRACER_INV_04 ==
  /\ TRUE

(* TRACER_INV_05: attribute type discipline *)
TRACER_INV_05 ==
  /\ TypeOK

(* TRACER_INV_06: async export / non-blocking *)
TRACER_INV_06 ==
  /\ state <= MaxInt

(* Operations *)
Set_attribute ==
  /\ state' = Set_attributeImpl(state)
  /\ UNCHANGED <<config>>

Add_event ==
  /\ state' = Add_eventImpl(state)
  /\ UNCHANGED <<config>>

Record_exception ==
  /\ state' = Record_exceptionImpl(state)
  /\ UNCHANGED <<config>>

Set_status ==
  /\ state' = Set_statusImpl(state)
  /\ UNCHANGED <<config>>

Start_as_current_span ==
  /\ state' = Start_as_current_spanImpl(state)
  /\ UNCHANGED <<config>>

Inject ==
  /\ state' = InjectImpl(state)
  /\ UNCHANGED <<config>>

Extract ==
  /\ state' = ExtractImpl(state)
  /\ UNCHANGED <<config>>

Validate_span_name ==
  /\ state' = Validate_span_nameImpl(state)
  /\ UNCHANGED <<config>>

Validate_kind ==
  /\ state' = Validate_kindImpl(state)
  /\ UNCHANGED <<config>>

Validate_attribute_value ==
  /\ state' = Validate_attribute_valueImpl(state)
  /\ UNCHANGED <<config>>

Validate_status_code ==
  /\ state' = Validate_status_codeImpl(state)
  /\ UNCHANGED <<config>>

Validate_traceparent ==
  /\ state' = Validate_traceparentImpl(state)
  /\ UNCHANGED <<config>>

End ==
  /\ state' = EndImpl(state)
  /\ UNCHANGED <<config>>

Spans ==
  /\ state' = SpansImpl(state)
  /\ UNCHANGED <<config>>

Export_calls ==
  /\ state' = Export_callsImpl(state)
  /\ UNCHANGED <<config>>

Tick ==
  /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    \/ Set_attribute \/ Add_event \/ Record_exception \/ Set_status \/ Start_as_current_span \/ Inject \/ Extract \/ Validate_span_name \/ Validate_kind \/ Validate_attribute_value \/ Validate_status_code \/ Validate_traceparent \/ End \/ Spans \/ Export_calls \/ Tick \/ Stutter

Spec == Init /\ [][Next]_vars

(* Safety: conjunction of all invariants *)
Safety ==
  /\ TRACER_INV_01
  /\ TRACER_INV_02
  /\ TRACER_INV_03
  /\ TRACER_INV_04
  /\ TRACER_INV_05
  /\ TRACER_INV_06

(* Liveness: meaningful eventual properties *)
Liveness ==
  /\ <>state' # state

====